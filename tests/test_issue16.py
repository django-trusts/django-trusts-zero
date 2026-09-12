"""Zero #16: donate Meta conditions to the core handle registry.

Paired against django-trusts#118 merge
``948d6666342377b9472debb57d4a1e26e81402d1``.
"""

import inspect

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import models
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import isolate_apps

from trusts.checks import (
    CHECK_ID_OBSOLETE_CALLBACK_SETTING,
    check_obsolete_legacy_callback_setting,
    check_permission_conditions,
    iter_live_permission_conditions,
)
from trusts.conditions import (
    ConditionRecord,
    ConditionRegistry,
    PermissionConditionError,
    PermissionConditionNotQueryable as CoreNotQueryable,
    Ref,
    RegistryConditionLookup,
)
from trusts.core import TrustsConfigurationError, TrustsRegistry
from trusts.zero.apps import CANONICAL_BACKEND_PATH, zero_config
from trusts.zero.models import (
    Content,
    Junction,
    Trust,
    TrustUserPermission,
)
from trusts.conditions import PermissionConditionNotQueryable
from trusts.zero.registration import (
    donate_content_permission_conditions,
    donate_installed_permission_conditions,
    donate_junction_content_permission_conditions,
)
from tests.apps import live_handle, publish_permission_condition
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
    return zero_config().configured_backend(CANONICAL_BACKEND_PATH).registry


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

    def saw_only_refs(self):
        return all(
            isinstance(arg, Ref) for call in self.calls for arg in call
        )


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
        self.assertIs(PermissionConditionNotQueryable, CoreNotQueryable)

    def test_zero_binds_generic_registry_lookup(self):
        handle = live_handle()
        registry = handle.registry
        lookup = registry.condition_lookup
        self.assertIsInstance(lookup, RegistryConditionLookup)
        self.assertIs(lookup.conditions, registry.conditions)
        self.assertTrue(callable(handle.register_permission_condition))


class MetaDonationOnceTests(SimpleTestCase):
    def test_trust_own_content_meta_and_junction_meta_register_once(self):
        registry = _zero_registry()
        own = _condition_rows(registry, Trust, 'own')
        self.assertEqual(len(own), 1)
        self.assertIsNotNone(own[0][2].expr)

        ticket_own = _condition_rows(registry, Ticket, 'own')
        self.assertEqual(len(ticket_own), 1)
        self.assertIsNotNone(ticket_own[0][2].expr)

        donate_installed_permission_conditions(registry)
        self.assertEqual(len(_condition_rows(registry, Trust, 'own')), 1)
        self.assertEqual(len(_condition_rows(registry, Ticket, 'own')), 1)

        live = [
            (model, code)
            for model, code, _record in iter_live_permission_conditions()
            if (model is Trust and code == 'own') or (model is Ticket and code == 'own')
        ]
        self.assertEqual(len(live), 2)

    @isolate_apps('tests', 'django.contrib.auth', 'django.contrib.contenttypes')
    def test_junction_meta_helper_registers_exactly_once(self):
        def via_memo(u, p, o):
            return u == o.owner

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

        isolated = TrustsRegistry()
        donate_junction_content_permission_conditions(isolated, MemoJunction)
        donate_junction_content_permission_conditions(isolated, MemoJunction)
        rows = _condition_rows(isolated, MemoJunction, 'via_memo')
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0][2].expr)
        self.assertFalse(hasattr(rows[0][2], 'func'))
        self.assertIsNone(_zero_registry().get_permission_condition_record(
            MemoJunction, 'via_memo',
        ))


class OwnerIsolationTests(SimpleTestCase):
    def test_owners_do_not_share_or_overwrite_and_new_registry_is_empty(self):
        left = TrustsRegistry()
        right = TrustsRegistry()
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
        live = _zero_registry().get_permission_condition_record(Ticket, 'own')
        self.assertIsNot(live, left.get_permission_condition_record(Ticket, 'own'))
        self.assertIsNot(live.expr, left_expr)
        self.assertIsNot(live.expr, right_expr)

        fresh = TrustsRegistry()
        self.assertEqual(list(fresh.iter_permission_conditions()), [])
        self.assertIsInstance(ConditionRegistry(), ConditionRegistry)
        self.assertIsNone(fresh.get_permission_condition_record(Trust, 'own'))
        self.assertIsNone(fresh.get_permission_condition_record(Ticket, 'own'))


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
        with self.assertRaises(AttributeError):
            user.has_perm('trusts_zero_tests.read_ticket:nope16', self.ticket)

        isolated = TrustsRegistry()
        with self.assertRaises(PermissionConditionError) as typo:
            isolated.register_permission_condition(
                Ticket, 'typo16', lambda u, p, o: u == o.nope,
            )
        self.assertIn('nope', str(typo.exception))
        self.assertIsNone(isolated.get_permission_condition_record(Ticket, 'typo16'))

        registry = _zero_registry()
        empty = ConditionRecord(model=Ticket)
        registry.conditions._records[(Ticket._meta.label, 'empty16')] = empty
        try:
            with self.assertRaises(PermissionConditionError) as unbound:
                registry.evaluate_permission_condition(
                    Ticket, 'empty16', user, 'trusts_zero_tests.read_ticket',
                    self.ticket,
                )
            self.assertIn('unbound', str(unbound.exception))
            with self.assertRaises(PermissionConditionError):
                user.has_perm('trusts_zero_tests.read_ticket:empty16', self.ticket)
        finally:
            registry.conditions._records.pop((Ticket._meta.label, 'empty16'), None)


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
        self.registry = _zero_registry()
        self.log = _BuilderLog(lambda u, p, o: o.name == 'keep')
        publish_permission_condition(Category, 'spy16', self.log)

    def tearDown(self):
        self.registry.conditions._records.pop((Category._meta.label, 'spy16'), None)

    def test_builder_once_object_and_queryset_parity(self):
        self.assertEqual(len(self.log.calls), 1)
        self.assertTrue(self.log.saw_only_refs())
        user = User.objects.get(pk=self.user.pk)
        permitted = set(Category.objects.permitted('read:spy16', user))
        self.assertEqual(permitted, {self.keep})
        self.assertTrue(user.has_perm('trusts_zero_tests.read_category:spy16', self.keep))
        self.assertFalse(user.has_perm('trusts_zero_tests.read_category:spy16', self.drop))
        self.assertEqual(len(self.log.calls), 1)

    def test_frozen_live_register_is_before_builder(self):
        late = _BuilderLog(lambda u, p, o: o.name == 'keep')
        with self.assertRaises(TrustsConfigurationError):
            live_handle().register_permission_condition(Category, 'late16', late)
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
        isolated = TrustsRegistry()
        exploding = _BuilderLog(lambda u, p, o: (_ for _ in ()).throw(
            AssertionError('callable must not run during checks')
        ))
        with self.assertRaises(AssertionError):
            isolated.register_permission_condition(Category, 'boom16', exploding)
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


class HelperDonationTests(SimpleTestCase):
    def test_content_meta_helper_is_not_a_second_store(self):
        isolated = TrustsRegistry()
        donate_content_permission_conditions(isolated, Ticket)
        donate_content_permission_conditions(isolated, Ticket)
        rows = _condition_rows(isolated, Ticket, 'own')
        self.assertEqual(len(rows), 1)
        record = isolated.get_permission_condition_record(Ticket, 'own')
        self.assertIsNotNone(record.expr)
        self.assertFalse(hasattr(record, 'func'))
        self.assertEqual(
            record.expr.to_tuple(),
            ('eq', ('ref', 'principal', ()), ('ref', 'object', ('owner',))),
        )
        self.assertIs(Ticket._meta.permission_conditions[0][1], ticket_own)
        self.assertFalse(hasattr(Content, '_conditions'))

    def test_trust_own_builder_donation_is_zero_sql(self):
        from trusts.zero.models import trust_own

        self.assertEqual(Trust._meta.permission_conditions, (('own', trust_own),))
        isolated = TrustsRegistry()
        with self.assertNumQueries(0):
            donate_content_permission_conditions(isolated, Trust)
        record = isolated.get_permission_condition_record(Trust, 'own')
        self.assertIsNotNone(record)
        self.assertFalse(hasattr(record, 'func'))
        self.assertEqual(
            record.expr.to_tuple(),
            ('eq', ('ref', 'principal', ()), ('ref', 'object', ('settlor',))),
        )
