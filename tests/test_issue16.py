"""Zero #16: donate Meta conditions onto a recorder, then read the catalog.

Paired against the exact django-trusts candidate
``3aad8c25f34469f4ecb03e9cd441d9e6315d4f0f``.
"""

import inspect

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import models
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.test.utils import isolate_apps

from trusts.conditions import (
    PermissionConditionError,
    PermissionConditionNotQueryable,
)
from trusts.inspect.checks import (
    CHECK_ID_OBSOLETE_CALLBACK_SETTING,
    check_obsolete_legacy_callback_setting,
    check_permission_conditions,
    iter_live_permission_conditions,
)
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
    register_zero_content,
)
from tests.apps import (
    build_catalog,
    isolated_recorder,
    live_catalog,
    live_recorder,
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


def _staticmethods(cls):
    return [
        name for name, val in cls.__dict__.items()
        if isinstance(val, staticmethod)
    ]


def _condition_rows(catalog, model, cond_code):
    return [
        (found, code, record)
        for found, code, record in catalog.iter_permission_conditions()
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

    def test_live_catalog_has_trust_own(self):
        catalog = live_catalog()
        own = catalog.get_permission_condition_record(Trust, 'own')
        self.assertIsNotNone(own)
        self.assertIsNotNone(own.expr)
        self.assertTrue(callable(live_recorder().add_named_filter))


class MetaDonationOnceTests(SimpleTestCase):
    def test_trust_own_content_meta_and_junction_meta_register_once(self):
        catalog = live_catalog()
        own = _condition_rows(catalog, Trust, 'own')
        self.assertEqual(len(own), 1)
        self.assertIsNotNone(own[0][2].expr)

        ticket_rows = _condition_rows(catalog, Ticket, 'own')
        self.assertEqual(len(ticket_rows), 1)
        self.assertIsNotNone(ticket_rows[0][2].expr)

        donate_installed_permission_conditions(live_recorder())
        self.assertEqual(len(_condition_rows(catalog, Trust, 'own')), 1)
        self.assertEqual(len(_condition_rows(catalog, Ticket, 'own')), 1)

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

        def contribute(recorder):
            donate_junction_content_permission_conditions(recorder, MemoJunction)
            donate_junction_content_permission_conditions(recorder, MemoJunction)

        catalog = build_catalog(contribute)
        rows = _condition_rows(catalog, MemoJunction, 'via_memo')
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0][2].expr)
        self.assertFalse(hasattr(rows[0][2], 'func'))
        self.assertIsNone(live_catalog().get_permission_condition_record(
            MemoJunction, 'via_memo',
        ))


class OwnerIsolationTests(SimpleTestCase):
    def test_catalogs_do_not_share_condition_records(self):
        def left_contribute(recorder):
            recorder.add_named_filter(
                Ticket, 'own', lambda u, p, o: u == o.owner,
            )

        def right_contribute(recorder):
            recorder.add_named_filter(
                Ticket, 'own', lambda u, p, o: o.title == 'keep',
            )

        left = build_catalog(left_contribute, path='tests.left')
        right = build_catalog(right_contribute, path='tests.right')
        left_record = left.get_permission_condition_record(Ticket, 'own')
        right_record = right.get_permission_condition_record(Ticket, 'own')
        self.assertEqual(
            left_record.expr.to_tuple(),
            ('eq', ('ref', 'principal', ()), ('ref', 'object', ('owner',))),
        )
        self.assertEqual(
            right_record.expr.to_tuple(),
            ('eq', ('ref', 'object', ('title',)), ('const', 'keep')),
        )
        live = live_catalog().get_permission_condition_record(Ticket, 'own')
        self.assertIsNot(live, left_record)
        self.assertIsNot(live.expr, left_record.expr)
        self.assertIsNot(live.expr, right_record.expr)

        empty = build_catalog(path='tests.empty')
        self.assertEqual(list(empty.iter_permission_conditions()), [])
        self.assertIsNone(empty.get_permission_condition_record(Trust, 'own'))
        self.assertIsNone(empty.get_permission_condition_record(Ticket, 'own'))
        compiled = left.compile_registered_condition_q(
            Ticket, 'trusts_zero_tests.read_ticket:own', None,
        )
        self.assertIsNotNone(compiled)
        self.assertEqual(
            [
                (model, code)
                for model, code, _record in left.iter_permission_conditions()
            ],
            [(Ticket, 'own')],
        )
        self.assertIsNot(
            live,
            left.get_permission_condition_record(Ticket, 'own'),
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

        def contribute(recorder):
            recorder.add_named_filter(
                Ticket, 'typo16', lambda u, p, o: u == o.nope,
            )

        with self.assertNumQueries(0):
            with self.assertRaises(PermissionConditionError) as typo:
                build_catalog(contribute)
        self.assertIn('nope', str(typo.exception))
        self.assertIsNone(
            live_catalog().get_permission_condition_record(Ticket, 'typo16')
        )

        self.assertTrue(
            user.has_perm('trusts_zero_tests.read_ticket:own', self.ticket)
        )
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
        self.log = _BuilderLog(lambda u, p, o: o.name == 'keep')

        def contribute(recorder):
            register_zero_content(recorder, Category)
            recorder.add_named_filter(Category, 'spy16', self.log)

        self.catalog = build_catalog(contribute)

    def test_builder_once_object_and_queryset_parity(self):
        self.assertEqual(len(self.log.calls), 1)
        user = User.objects.get(pk=self.user.pk)
        code = 'trusts_zero_tests.read_category:spy16'
        read = Category.objects.get_permission('read')
        granted = self.catalog.filter_authorized(
            Category.objects.all(), user, read,
        )
        overlay = self.catalog.compile_registered_condition_q(
            Category, code, user,
        )
        permitted = set(granted.filter(overlay))
        self.assertEqual(permitted, {self.keep})
        self.assertTrue(self.catalog.has_perm(user, code, self.keep))
        self.assertFalse(self.catalog.has_perm(user, code, self.drop))
        self.assertEqual(len(self.log.calls), 1)

    def test_catalog_build_invokes_builder_once(self):
        late = _BuilderLog(lambda u, p, o: o.name == 'keep')

        def contribute(recorder):
            recorder.add_named_filter(Category, 'late16', late)
            self.assertEqual(len(late.calls), 0)

        catalog = build_catalog(contribute)
        self.assertEqual(len(late.calls), 1)
        self.assertIsNotNone(
            catalog.get_permission_condition_record(Category, 'late16')
        )
        catalog.compile_registered_condition_q(
            Category, 'trusts_zero_tests.read_category:late16', None,
        )
        self.assertEqual(len(late.calls), 1)

    def test_checks_never_reinvoke_builder(self):
        self.assertEqual(len(self.log.calls), 1)
        messages = check_permission_conditions(None)
        self.assertEqual(len(self.log.calls), 1)
        self.assertEqual(
            [m.id for m in messages if m.id == CHECK_ID_OBSOLETE_CALLBACK_SETTING],
            [],
        )

    def test_boolean_builder_fails_at_build(self):
        exploding = _BuilderLog(lambda u, p, o: (_ for _ in ()).throw(
            AssertionError('callable must not run during checks')
        ))

        def contribute(recorder):
            recorder.add_named_filter(Category, 'boom16', exploding)

        with self.assertRaises(PermissionConditionError) as ctx:
            build_catalog(contribute)
        self.assertIn('AssertionError', str(ctx.exception))
        self.assertEqual(len(exploding.calls), 1)

    @override_settings(TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS=True)
    def test_leftover_setting_is_error_and_does_not_enable_callbacks(self):
        messages = check_obsolete_legacy_callback_setting(None)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].id, CHECK_ID_OBSOLETE_CALLBACK_SETTING)
        self.assertIn('does not enable', messages[0].msg)
        user = User.objects.get(pk=self.user.pk)
        self.assertTrue(self.catalog.has_perm(
            user, 'trusts_zero_tests.read_category:spy16', self.keep,
        ))
        self.assertEqual(len(self.log.calls), 1)


class HelperDonationTests(TransactionTestCase):
    def test_content_meta_helper_is_not_a_second_store(self):
        recorder = isolated_recorder()
        donate_content_permission_conditions(recorder, Ticket)
        donate_content_permission_conditions(recorder, Ticket)
        catalog = build_catalog(recorder=recorder)
        rows = _condition_rows(catalog, Ticket, 'own')
        self.assertEqual(len(rows), 1)
        record = catalog.get_permission_condition_record(Ticket, 'own')
        self.assertIsNotNone(record.expr)
        self.assertFalse(hasattr(record, 'func'))
        self.assertEqual(
            record.expr.to_tuple(),
            ('eq', ('ref', 'principal', ()), ('ref', 'object', ('owner',))),
        )
        self.assertIs(Ticket._meta.permission_conditions[0][1], ticket_own)
        self.assertFalse(hasattr(Content, '_conditions'))

    def test_trust_own_builder_donation_is_zero_sql(self):
        code, builder = Trust._meta.permission_conditions[0]
        self.assertEqual(code, 'own')
        self.assertTrue(callable(builder))
        recorder = isolated_recorder()
        with self.assertNumQueries(0):
            donate_content_permission_conditions(recorder, Trust)
            catalog = build_catalog(recorder=recorder)
        record = catalog.get_permission_condition_record(Trust, 'own')
        self.assertIsNotNone(record)
        self.assertFalse(hasattr(record, 'func'))
        self.assertEqual(
            record.expr.to_tuple(),
            ('eq', ('ref', 'principal', ()), ('ref', 'object', ('settlor',))),
        )
