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
    CHECK_ID_LEGACY_CALLBACK,
    CHECK_ID_LEGACY_CALLBACK_WARNING,
    check_permission_conditions,
    iter_live_permission_conditions,
)
from trusts.conditions import (
    ConditionRecord,
    ConditionRegistry,
    PermissionConditionError,
    PermissionConditionNotQueryable as CoreNotQueryable,
    RegistryConditionLookup,
    condition_refs,
    legacy_permission_callbacks_allowed,
)
from trusts.core import TrustsRegistry
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
from tests.models import Category, Ticket


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


class _CallLog(object):
    def __init__(self, impl=None):
        self.impl = impl or (lambda user, perm, obj: True)
        self.calls = []

    def __call__(self, user, perm, obj):
        self.calls.append((user, perm, obj))
        return self.impl(user, perm, obj)


class ZeroConditionSurfaceTests(SimpleTestCase):
    def test_no_content_condition_lookup_or_static_registration(self):
        import trusts.zero.models as zero_models

        self.assertFalse(hasattr(zero_models, 'ContentConditionLookup'))
        self.assertFalse(hasattr(Content, '_conditions'))
        self.assertFalse(hasattr(zero_models, 'legacy_permission_callbacks_allowed'))
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
        registry = _zero_registry()
        lookup = registry.condition_lookup
        self.assertIsInstance(lookup, RegistryConditionLookup)
        self.assertIs(lookup.conditions, registry.conditions)


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
        u, _p, o = condition_refs()

        class Memo(models.Model):
            owner = models.ForeignKey(User, on_delete=models.CASCADE)

            class Meta:
                app_label = 'trusts_zero_tests'

        class MemoJunction(Junction):
            content = models.ForeignKey(Memo, unique=True, on_delete=models.CASCADE)

            class Meta:
                app_label = 'trusts_zero_tests'
                content_permission_conditions = (
                    ('via_memo', u == o.owner),
                )

        isolated = TrustsRegistry()
        donate_junction_content_permission_conditions(isolated, MemoJunction)
        donate_junction_content_permission_conditions(isolated, MemoJunction)
        rows = _condition_rows(isolated, MemoJunction, 'via_memo')
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0][2].expr)
        self.assertIsNone(_zero_registry().get_permission_condition_record(
            MemoJunction, 'via_memo',
        ))


class OwnerIsolationTests(SimpleTestCase):
    def test_owners_do_not_share_or_overwrite_and_new_registry_is_empty(self):
        u, _p, o = condition_refs()
        left = TrustsRegistry()
        right = TrustsRegistry()
        expr_a = u == o.owner
        expr_b = o.title == 'keep'
        left.register_permission_condition(Ticket, 'own', expr_a)
        right.register_permission_condition(Ticket, 'own', expr_b)
        self.assertIs(left.get_permission_condition_record(Ticket, 'own').expr, expr_a)
        self.assertIs(right.get_permission_condition_record(Ticket, 'own').expr, expr_b)
        live = _zero_registry().get_permission_condition_record(Ticket, 'own')
        self.assertIsNot(live, left.get_permission_condition_record(Ticket, 'own'))
        self.assertIsNot(live.expr, expr_a)
        self.assertIsNot(live.expr, expr_b)

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

        registry = _zero_registry()
        u, _p, o = condition_refs()
        registry.register_permission_condition(Ticket, 'typo16', u == o.nope)
        try:
            with self.assertRaises(PermissionConditionError) as typo:
                list(Ticket.objects.permitted('read:typo16', user))
            self.assertIn('nope', str(typo.exception))
            with self.assertRaises(PermissionConditionError):
                user.has_perm('trusts_zero_tests.read_ticket:typo16', self.ticket)

            empty = ConditionRecord(model=Ticket)
            registry.conditions._records[(Ticket._meta.label, 'empty16')] = empty
            with self.assertRaises(PermissionConditionError) as unbound:
                registry.evaluate_permission_condition(
                    Ticket, 'empty16', user, 'trusts_zero_tests.read_ticket',
                    self.ticket,
                )
            self.assertIn('unbound', str(unbound.exception))
            with self.assertRaises(PermissionConditionError):
                user.has_perm('trusts_zero_tests.read_ticket:empty16', self.ticket)
        finally:
            registry.conditions._records.pop((Ticket._meta.label, 'typo16'), None)
            registry.conditions._records.pop((Ticket._meta.label, 'empty16'), None)


class CallableGateTests(TestCase):
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
        self.log = _CallLog(lambda user, perm, obj: obj.name == 'keep')
        self.registry.register_permission_condition(Category, 'spy16', self.log)

    def tearDown(self):
        self.registry.conditions._records.pop((Category._meta.label, 'spy16'), None)

    def test_default_rejects_callable_without_invoking(self):
        self.assertFalse(legacy_permission_callbacks_allowed())
        user = User.objects.get(pk=self.user.pk)
        with self.assertRaises(PermissionConditionNotQueryable):
            list(Category.objects.permitted('read:spy16', user))
        with self.assertRaises(PermissionConditionError) as ctx:
            user.has_perm('trusts_zero_tests.read_category:spy16', self.keep)
        self.assertIn('TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS', str(ctx.exception))
        self.assertEqual(self.log.calls, [])

    @override_settings(TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS=True)
    def test_opt_in_callback_is_object_only(self):
        self.assertTrue(legacy_permission_callbacks_allowed())
        user = User.objects.get(pk=self.user.pk)
        with self.assertRaises(PermissionConditionNotQueryable):
            list(Category.objects.permitted('read:spy16', user))
        self.assertEqual(self.log.calls, [])
        self.assertTrue(user.has_perm('trusts_zero_tests.read_category:spy16', self.keep))
        self.assertFalse(user.has_perm('trusts_zero_tests.read_category:spy16', self.drop))
        self.assertEqual(len(self.log.calls), 2)
        self.assertEqual(self.log.calls[0][2], self.keep)
        self.assertEqual(self.log.calls[1][2], self.drop)

    def test_checks_never_invoke_callables(self):
        exploding = _CallLog(lambda user, perm, obj: (_ for _ in ()).throw(
            AssertionError('callable must not run during checks')
        ))
        self.registry.register_permission_condition(Category, 'boom16', exploding)
        try:
            messages = check_permission_conditions(None)
            self.assertEqual(exploding.calls, [])
            ids = [m.id for m in messages]
            self.assertIn(CHECK_ID_LEGACY_CALLBACK, ids)
            self.assertNotIn(CHECK_ID_LEGACY_CALLBACK_WARNING, ids)
        finally:
            self.registry.conditions._records.pop((Category._meta.label, 'boom16'), None)

    @override_settings(TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS=True)
    def test_opt_in_check_is_warning_without_invoking(self):
        messages = check_permission_conditions(None)
        self.assertEqual(self.log.calls, [])
        ids = [m.id for m in messages]
        self.assertIn(CHECK_ID_LEGACY_CALLBACK_WARNING, ids)
        self.assertNotIn(CHECK_ID_LEGACY_CALLBACK, ids)


class HelperDonationTests(SimpleTestCase):
    def test_content_meta_helper_is_not_a_second_store(self):
        u, _p, o = condition_refs()
        isolated = TrustsRegistry()
        donate_content_permission_conditions(isolated, Ticket)
        donate_content_permission_conditions(isolated, Ticket)
        rows = _condition_rows(isolated, Ticket, 'own')
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(isolated.get_permission_condition_record(Ticket, 'own').expr)
        self.assertFalse(hasattr(Content, '_conditions'))
