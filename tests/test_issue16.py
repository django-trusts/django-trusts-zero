"""Zero #16: donate Meta conditions to the configured backend.

Paired against the exact django-trusts candidate
``f898123987569817bc93e31e34505211e1c61b82``.
"""

import inspect

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import models
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.test.utils import isolate_apps

from trusts.inspect.checks import (
    CHECK_ID_OBSOLETE_CALLBACK_SETTING,
    check_obsolete_legacy_callback_setting,
    check_permission_conditions,
    iter_live_permission_conditions,
)
from trusts.conditions import (
    PermissionConditionError,
    PermissionConditionNotQueryable,
)
from trusts.errors import TrustsConfigurationError
from trusts.zero.apps import zero_config
from trusts.zero.models import (
    Content,
    Junction,
    Trust,
    TrustUserPermission,
)
from trusts.zero.registration import (
    donate_content_permission_conditions,
    donate_installed_permission_conditions,
    donate_junction_content_permission_conditions,
)
from tests.apps import (
    IsolatedTarget,
    isolated_backend,
    live_backend,
    live_registry,
    publish_permission_condition,
    tests_config,
    tests_registry,
)
from tests.models import Category, Ticket, ticket_own


REMOVED_STATIC = (
    'register_permission_condition',
    'register_content',
    'get_permission_condition_record',
    'get_permission_condition_func',
    'iter_permission_conditions',
    'register_junction',
)


def _zero_registry():
    return live_registry()


def _tests_registry():
    return tests_registry()


def _staticmethods(cls):
    return [
        name for name, val in cls.__dict__.items()
        if isinstance(val, staticmethod)
    ]


def _condition_rows(registry, model, cond_code):
    return [
        (found, code, record)
        for found, code, record in registry.iter_permission_conditions()
        if found is model and code == cond_code
    ]


class _BuilderLog(object):
    def __init__(self, impl=None):
        self.impl = impl or (lambda u, p, o: u == o.owner)
        self.calls = []

    def __call__(self, u, p, o):
        self.calls.append((u, p, o))
        return self.impl(u, p, o)


class ZeroConditionSurfaceTests(SimpleTestCase):
    def test_no_content_condition_lookup_or_static_registration(self):
        import trusts.zero.models as zero_models

        self.assertFalse(hasattr(zero_models, 'ContentConditionLookup'))
        self.assertFalse(hasattr(Content, '_conditions'))
        self.assertFalse(hasattr(zero_models, 'legacy_permission_callbacks_allowed'))
        self.assertFalse(hasattr(zero_models, 'condition_refs'))
        self.assertFalse(hasattr(zero_models, '_ConditionRecord'))
        for name in REMOVED_STATIC:
            self.assertFalse(hasattr(Content, name), name)
            self.assertFalse(hasattr(Junction, name), name)
        self.assertEqual(_staticmethods(Content), [])
        self.assertEqual(_staticmethods(Junction), [])
        source = inspect.getsource(zero_models)
        self.assertNotIn('class ContentConditionLookup', source)
        self.assertNotIn('@staticmethod', source)
        self.assertFalse(hasattr(zero_models, 'PermissionConditionNotQueryable'))
        self.assertTrue(issubclass(PermissionConditionNotQueryable, Exception))

    def test_live_registry_has_self_bound_lookup(self):
        backend = live_backend()
        registry = backend.registry
        lookup = registry.condition_lookup
        self.assertIsNotNone(lookup)
        self.assertIs(lookup.conditions, registry.conditions)
        own = registry.get_permission_condition_record(Trust, 'own')
        self.assertIsNotNone(own)
        self.assertIsNotNone(own.expr)
        self.assertTrue(callable(backend.add_named_filter))


class MetaDonationOnceTests(SimpleTestCase):
    def test_trust_own_content_meta_and_junction_meta_register_once(self):
        registry = _zero_registry()
        own = _condition_rows(registry, Trust, 'own')
        self.assertEqual(len(own), 1)
        self.assertIsNotNone(own[0][2].expr)

        ticket_own = _condition_rows(_tests_registry(), Ticket, 'own')
        self.assertEqual(len(ticket_own), 1)
        self.assertIsNotNone(ticket_own[0][2].expr)

        donate_installed_permission_conditions(live_backend())
        self.assertEqual(len(_condition_rows(registry, Trust, 'own')), 1)
        self.assertEqual(len(_condition_rows(_tests_registry(), Ticket, 'own')), 1)

        live = [
            (model, code)
            for model, code, _record in iter_live_permission_conditions()
            if (model is Trust and code == 'own') or (model is Ticket and code == 'own')
        ]
        self.assertEqual(len(live), 2)

    @isolate_apps('tests', 'django.contrib.auth', 'django.contrib.contenttypes')
    def test_junction_meta_helper_registers_exactly_once(self):
        def via_memo(u, p, o):
            return u == o.content.owner

        class Memo(models.Model):
            owner = models.ForeignKey(User, on_delete=models.CASCADE)

            class Meta:
                app_label = 'trusts_zero_tests'

        class MemoJunction(Junction):
            content = models.ForeignKey(Memo, unique=True, on_delete=models.CASCADE)

            class Meta:
                app_label = 'trusts_zero_tests'
                content_permission_conditions = (
                    ('via_memo', via_memo),
                )

        isolated = isolated_backend()
        donate_junction_content_permission_conditions(isolated, MemoJunction)
        donate_junction_content_permission_conditions(isolated, MemoJunction)
        rows = _condition_rows(isolated.registry, MemoJunction, 'via_memo')
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0][2].expr)
        self.assertFalse(hasattr(rows[0][2], 'func'))
        self.assertIsNone(_zero_registry().get_permission_condition_record(
            MemoJunction, 'via_memo',
        ))


class OwnerIsolationTests(SimpleTestCase):
    def test_owners_do_not_share_or_overwrite_and_new_registry_is_empty(self):
        left = IsolatedTarget()
        right = IsolatedTarget()
        self.assertIsNot(left.condition_lookup, right.condition_lookup)
        self.assertIs(left.condition_lookup.conditions, left.conditions)
        self.assertIs(right.condition_lookup.conditions, right.conditions)
        self.assertIsNot(left.conditions, right.conditions)
        left.register_permission_condition(
            Ticket, 'own', lambda u, p, o: u == o.owner,
        )
        right.register_permission_condition(
            Ticket, 'own', lambda u, p, o: o.title == 'keep',
        )
        left_expr = left.get_permission_condition_record(Ticket, 'own').expr
        right_expr = right.get_permission_condition_record(Ticket, 'own').expr
        self.assertEqual(
            left_expr.to_tuple(),
            ('eq', ('ref', 'principal', ()), ('ref', 'object', ('owner',))),
        )
        self.assertEqual(
            right_expr.to_tuple(),
            ('eq', ('ref', 'object', ('title',)), ('const', 'keep')),
        )
        live = _tests_registry().get_permission_condition_record(Ticket, 'own')
        self.assertIsNot(live, left.get_permission_condition_record(Ticket, 'own'))
        self.assertIsNot(live.expr, left_expr)
        self.assertIsNot(live.expr, right_expr)

        fresh = IsolatedTarget()
        self.assertIsNotNone(fresh.condition_lookup)
        self.assertIs(fresh.condition_lookup.conditions, fresh.conditions)
        self.assertEqual(list(fresh.iter_permission_conditions()), [])
        self.assertIsNone(fresh.get_permission_condition_record(Trust, 'own'))
        self.assertIsNone(fresh.get_permission_condition_record(Ticket, 'own'))
        fresh.register_permission_condition(
            Ticket, 'own', lambda u, p, o: u == o.owner,
        )
        compiled = fresh.condition_lookup.compile_q(
            Ticket, 'trusts_zero_tests.read_ticket:own', None,
        )
        self.assertIsNotNone(fresh.get_permission_condition_record(Ticket, 'own'))
        self.assertEqual(
            [
                (model, code)
                for model, code, _record in fresh.iter_permission_conditions()
            ],
            [(Ticket, 'own')],
        )
        self.assertIsNotNone(compiled)
        self.assertIsNot(
            live,
            fresh.get_permission_condition_record(Ticket, 'own'),
        )


class ExprParityTests(TestCase):
    def setUp(self):
        call_command('create_trust_root')
        self.user = User.objects.create_user('alice-16', 'alice-16@example.com', 'x')
        self.other = User.objects.create_user('bob-16', 'bob-16@example.com', 'x')
        self.root = Trust.objects.get(pk=1)
        self.org = Trust(settlor=self.user, title='Org16', trust=self.root)
        self.org.save()
        self.child = Trust(settlor=self.user, title='Child16', trust=self.org)
        self.child.save()
        self.isolated = Trust(settlor=self.other, title='Iso16', trust=self.root)
        self.isolated.save()
        ct = ContentType.objects.get_for_model(Trust)
        self.change = Permission.objects.get(content_type=ct, codename='change_trust')
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=self.change,
        ).save()
        self.ticket = Ticket(title='mine', owner=self.user, trust=self.org)
        self.ticket.save()
        self.other_ticket = Ticket(title='theirs', owner=self.other, trust=self.org)
        self.other_ticket.save()
        read = Ticket.objects.get_permission('read')
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=read,
        ).save()

    def test_has_perm_and_permitted_parity_for_registered_expr(self):
        user = User.objects.get(pk=self.user.pk)
        permitted_trusts = set(Trust.objects.permitted('change:own', user))
        evaluated_trusts = {
            row for row in Trust.objects.all()
            if user.has_perm('trusts.change_trust:own', row)
        }
        self.assertEqual(permitted_trusts, evaluated_trusts)
        self.assertIn(self.child, permitted_trusts)
        self.assertNotIn(self.isolated, permitted_trusts)

        permitted_tickets = set(Ticket.objects.permitted('read:own', user))
        evaluated_tickets = {
            row for row in Ticket.objects.all()
            if user.has_perm('trusts_zero_tests.read_ticket:own', row)
        }
        self.assertEqual(permitted_tickets, evaluated_tickets)
        self.assertEqual(permitted_tickets, {self.ticket})

    def test_unknown_malformed_and_unbound_fail_closed(self):
        user = User.objects.get(pk=self.user.pk)
        with self.assertRaises(AttributeError) as missing:
            list(Ticket.objects.permitted('read:nope16', user))
        self.assertIn('nope16', str(missing.exception))
        with self.assertNumQueries(0):
            self.assertFalse(
                user.has_perm('trusts_zero_tests.read_ticket:nope16', self.ticket),
            )

        isolated = IsolatedTarget()
        with self.assertNumQueries(0):
            with self.assertRaises(PermissionConditionError) as typo:
                isolated.register_permission_condition(
                    Ticket, 'typo16', lambda u, p, o: u == o.nope,
                )
        self.assertIn('nope', str(typo.exception))
        self.assertIsNone(isolated.get_permission_condition_record(Ticket, 'typo16'))
        self.assertEqual(list(isolated.iter_permission_conditions()), [])

        registry = _tests_registry()
        key = (Ticket._meta.label, 'own')
        saved = registry.conditions._records[key]
        try:
            with self.assertNumQueries(0):
                registry.conditions._records.pop(key)
            self.assertIsNone(registry.get_permission_condition_record(Ticket, 'own'))
            with self.assertNumQueries(0):
                self.assertFalse(
                    user.has_perm('trusts_zero_tests.read_ticket:own', self.ticket),
                )
            with self.assertRaises(AttributeError) as unbound:
                list(Ticket.objects.permitted('read:own', user))
            self.assertIn('own', str(unbound.exception))
        finally:
            registry.conditions._records[key] = saved
        self.assertIs(
            _tests_registry().get_permission_condition_record(Ticket, 'own'),
            saved,
        )
        self.assertTrue(user.has_perm('trusts_zero_tests.read_ticket:own', self.ticket))
        self.assertIn(self.ticket, set(Ticket.objects.permitted('read:own', user)))


class BuilderOnceTests(TestCase):
    def setUp(self):
        call_command('create_trust_root')
        self.user = User.objects.create_user('cb-16', 'cb-16@example.com', 'x')
        self.root = Trust.objects.get(pk=1)
        self.org = Trust(settlor=self.user, title='CB16', trust=self.root)
        self.org.save()
        self.keep = Category(name='keep', trust=self.org)
        self.keep.save()
        self.drop = Category(name='drop', trust=self.org)
        self.drop.save()
        read = Category.objects.get_permission('read')
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=read,
        ).save()
        self.registry = _tests_registry()
        self.log = _BuilderLog(lambda u, p, o: o.name == 'keep')
        publish_permission_condition(Category, 'spy16', self.log)

    def tearDown(self):
        self.registry.conditions._records.pop((Category._meta.label, 'spy16'), None)

    def test_builder_once_object_and_queryset_parity(self):
        self.assertEqual(len(self.log.calls), 1)
        user = User.objects.get(pk=self.user.pk)
        permitted = set(Category.objects.permitted('read:spy16', user))
        self.assertEqual(permitted, {self.keep})
        self.assertTrue(user.has_perm('trusts_zero_tests.read_category:spy16', self.keep))
        self.assertFalse(user.has_perm('trusts_zero_tests.read_category:spy16', self.drop))
        self.assertEqual(len(self.log.calls), 1)

    def test_frozen_live_register_is_before_builder(self):
        late = _BuilderLog(lambda u, p, o: o.name == 'keep')
        with self.assertRaises(TrustsConfigurationError):
            tests_config().recorder.add_named_filter(Category, 'late16', late)
        self.assertEqual(late.calls, [])

    def test_checks_never_reinvoke_builder(self):
        self.assertEqual(len(self.log.calls), 1)
        messages = check_permission_conditions(None)
        self.assertEqual(len(self.log.calls), 1)
        self.assertEqual(
            [m.id for m in messages if m.id == CHECK_ID_OBSOLETE_CALLBACK_SETTING],
            [],
        )

    def test_boolean_builder_fails_at_register(self):
        isolated = IsolatedTarget()
        exploding = _BuilderLog(lambda u, p, o: (_ for _ in ()).throw(
            AssertionError('callable must not run during checks')
        ))
        with self.assertRaises(PermissionConditionError) as ctx:
            isolated.register_permission_condition(Category, 'boom16', exploding)
        self.assertIn('AssertionError', str(ctx.exception))
        self.assertEqual(len(exploding.calls), 1)
        self.assertIsNone(isolated.get_permission_condition_record(Category, 'boom16'))

    @override_settings(TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS=True)
    def test_leftover_setting_is_error_and_does_not_enable_callbacks(self):
        messages = check_obsolete_legacy_callback_setting(None)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].id, CHECK_ID_OBSOLETE_CALLBACK_SETTING)
        self.assertIn('does not enable', messages[0].msg)
        user = User.objects.get(pk=self.user.pk)
        self.assertTrue(user.has_perm('trusts_zero_tests.read_category:spy16', self.keep))
        self.assertEqual(len(self.log.calls), 1)


class HelperDonationTests(TransactionTestCase):
    def test_content_meta_helper_is_not_a_second_store(self):
        isolated = isolated_backend()
        donate_content_permission_conditions(isolated, Ticket)
        self.assertIsNone(isolated.registry.get_permission_condition_record(Ticket, 'own'))
        isolated.add_named_filter(Ticket, 'own', ticket_own)
        isolated.add_named_filter(Ticket, 'own', ticket_own)
        rows = _condition_rows(isolated.registry, Ticket, 'own')
        self.assertEqual(len(rows), 1)
        record = isolated.registry.get_permission_condition_record(Ticket, 'own')
        self.assertIsNotNone(record.expr)
        self.assertFalse(hasattr(record, 'func'))
        self.assertEqual(
            record.expr.to_tuple(),
            ('eq', ('ref', 'principal', ()), ('ref', 'object', ('owner',))),
        )
        self.assertFalse(hasattr(Ticket._meta, 'permission_conditions'))
        self.assertFalse(hasattr(Content, '_conditions'))

    def test_trust_own_builder_donation_is_zero_sql(self):
        from trusts.zero.registration import trust_settlor_owns

        isolated = isolated_backend()
        with self.assertNumQueries(0):
            donate_content_permission_conditions(isolated, Trust)
            self.assertIsNone(
                isolated.registry.get_permission_condition_record(Trust, 'own'),
            )
            isolated.add_named_filter(Trust, 'own', trust_settlor_owns)
        record = isolated.registry.get_permission_condition_record(Trust, 'own')
        self.assertIsNotNone(record)
        self.assertFalse(hasattr(record, 'func'))
        self.assertEqual(
            record.expr.to_tuple(),
            ('eq', ('ref', 'principal', ()), ('ref', 'object', ('settlor',))),
        )
