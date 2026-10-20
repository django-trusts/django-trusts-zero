"""Condition donation and live terminal parity (issue #87).

The static content map is gone. Meta conditions are donated onto a
recorder and read from the compiled catalog. Live ``has_perm`` still
covers Category, Ticket, Trust, and Group.
"""

from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import models
from django.test import SimpleTestCase, TestCase

from tests.apps import build_catalog, forget_models, live_catalog
from tests.legacy.helpers import enable_local_group_grant, get_or_create_root_user
from tests.models import Category, Organization, TestGroupJunction, Ticket
from trusts.inspect.checks import check_permission_conditions
from trusts.zero.backends import TrustModelBackend
from trusts.zero.models import Content, Junction, Trust, TrustUserPermission
from trusts.zero.registration import (
    donate_content_permission_conditions,
    donate_junction_content_permission_conditions,
)


def _sheet_own(u, p, o):
    return o.trust != None


def _junc_own(u, p, o):
    return o.trust != None


def _perm(model, codename):
    ct, _created = ContentType.objects.get_or_create(
        app_label=model._meta.app_label,
        model=model._meta.model_name,
    )
    permission, _created = Permission.objects.get_or_create(
        content_type=ct,
        codename=codename,
        defaults={'name': codename},
    )
    return permission


class DonatedConditionCatalogTest(SimpleTestCase):
    def test_content_meta_lands_on_an_isolated_catalog(self):
        class IsolatedSheet(Content):
            title = models.CharField(max_length=40)

            class Meta:
                app_label = 'trusts_zero_tests'
                managed = False
                permission_conditions = (
                    ('sheet_own', _sheet_own),
                )

        try:
            def contribute(recorder):
                donate_content_permission_conditions(recorder, IsolatedSheet)
                donate_content_permission_conditions(recorder, IsolatedSheet)

            catalog = build_catalog(contribute)
            record = catalog.get_permission_condition_record(IsolatedSheet, 'sheet_own')
            self.assertIsNotNone(record)
            self.assertIs(record.model, IsolatedSheet)
            self.assertIsNotNone(record.expr)
            self.assertFalse(live_catalog().plan_for(IsolatedSheet).records)
            codes = [
                code for model, code, _record in catalog.iter_permission_conditions()
                if model is IsolatedSheet
            ]
            self.assertEqual(codes, ['sheet_own'])
        finally:
            forget_models(IsolatedSheet)

    def test_junction_meta_lands_on_an_isolated_catalog(self):
        class IsolatedJunction(Junction):
            content = models.ForeignKey(
                Group, unique=True, on_delete=models.CASCADE,
            )

            class Meta:
                app_label = 'trusts_zero_tests'
                managed = False
                content_permission_conditions = (
                    ('junc_own', _junc_own),
                )

        try:
            before = live_catalog().plan_for(Group).records

            def contribute(recorder):
                donate_junction_content_permission_conditions(
                    recorder, IsolatedJunction,
                )

            catalog = build_catalog(contribute)
            record = catalog.get_permission_condition_record(
                IsolatedJunction, 'junc_own',
            )
            self.assertIsNotNone(record)
            self.assertIs(record.model, IsolatedJunction)
            self.assertIsNotNone(record.expr)
            self.assertEqual(live_catalog().plan_for(Group).records, before)
        finally:
            forget_models(IsolatedJunction)

    def test_duplicate_named_filter_keeps_the_last_expression(self):
        def contribute(recorder):
            recorder.add_named_filter(
                Ticket, 'meta_own', lambda u, p, o: o.title == 'first',
            )
            recorder.add_named_filter(
                Ticket, 'meta_own', lambda u, p, o: u == o.owner,
            )

        catalog = build_catalog(contribute)
        record = catalog.get_permission_condition_record(Ticket, 'meta_own')
        self.assertIs(record.model, Ticket)
        self.assertEqual(
            record.expr.to_tuple(),
            ('eq', ('ref', 'principal', ()), ('ref', 'object', ('owner',))),
        )


class LiveConditionTest(TestCase):
    def test_trust_own_and_ticket_meta_own_remain(self):
        catalog = live_catalog()
        own = catalog.get_permission_condition_record(Trust, 'own')
        self.assertIsNotNone(own)
        self.assertIs(own.model, Trust)
        self.assertIsNotNone(own.expr)
        meta_own = catalog.get_permission_condition_record(Ticket, 'meta_own')
        self.assertIsNotNone(meta_own)
        self.assertIs(meta_own.model, Ticket)
        self.assertIsNotNone(meta_own.expr)
        messages = check_permission_conditions(None)
        self.assertEqual([message for message in messages if message.id == 'trusts.E001'], [])


class _UsersMixin(object):
    def _make_users(self, suffix):
        get_or_create_root_user(self)
        call_command('create_trust_root')
        self.alice = User.objects.create_user(
            'alice-%s' % suffix, 'alice-%s@example.com' % suffix, 'x',
        )
        self.bob = User.objects.create_user(
            'bob-%s' % suffix, 'bob-%s@example.com' % suffix, 'x',
        )
        self.carol = User.objects.create_user(
            'carol-%s' % suffix, 'carol-%s@example.com' % suffix, 'x',
        )
        for user in (self.alice, self.bob, self.carol):
            user.is_active = True
            user.save()
        root = Trust.objects.get_root()
        self.trust_a = Trust(settlor=self.alice, trust=root, title='S7 A %s' % suffix)
        self.trust_a.save()
        self.trust_b = Trust(settlor=self.alice, trust=root, title='S7 B %s' % suffix)
        self.trust_b.save()

    def _reload(self):
        self.alice = User.objects.get(pk=self.alice.pk)
        self.bob = User.objects.get(pk=self.bob.pk)
        self.carol = User.objects.get(pk=self.carol.pk)


class LiveTerminalParityTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('parity')
        self.cat = Category.objects.create(trust=self.trust_a, name='s7-cat')
        self.change_cat = _perm(Category, 'change_category')
        self.cat_code = 'trusts_zero_tests.change_category'
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change_cat,
        ).save()
        self.carol_group = Group.objects.create(name='carol-s7-parity')
        self.carol.groups.add(self.carol_group)
        self.change_cat.group_set.add(self.carol_group)
        enable_local_group_grant(self.trust_a, self.carol_group, self.change_cat)
        self.group = Group.objects.create(name='s7-protected')
        TestGroupJunction.objects.create(
            trust=self.trust_a, content=self.group, name='s7-j',
        )
        self.change_group = _perm(Group, 'change_group')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change_group,
        ).save()
        self._reload()

    def test_category_ticket_trust_group_allow_deny(self):
        self.assertTrue(self.alice.has_perm(self.cat_code, self.cat))
        self.assertTrue(self.carol.has_perm(self.cat_code, self.cat))
        self.assertFalse(self.bob.has_perm(self.cat_code, self.cat))
        backend = TrustModelBackend()
        self.assertFalse(backend.has_perm(self.alice, self.cat_code))
        qs = Category.objects.filter(pk=self.cat.pk)
        self.assertTrue(self.alice.has_perm(self.cat_code, qs))
        self.assertIn(self.cat_code, self.alice.get_all_permissions(self.cat))
        self.assertNotIn(self.cat_code, self.alice.get_group_permissions(self.cat))
        self.assertIn(self.cat_code, self.carol.get_group_permissions(self.cat))
        self.assertTrue(self.alice.has_perm('auth.change_group', self.group))
        child = Trust(settlor=self.alice, trust=self.trust_a, title='s7-child')
        child.save()
        change_trust = _perm(Trust, 'change_trust')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=change_trust,
        ).save()
        org = Organization.objects.create(name='s7-org', manager=self.alice)
        ticket = Ticket.objects.create(
            trust=self.trust_a, title='s7-t', owner=self.alice,
            organization=org, status='open',
        )
        ticket_change = _perm(Ticket, 'change_ticket')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=ticket_change,
        ).save()
        self._reload()
        self.assertTrue(self.alice.has_perm('trusts.change_trust', child))
        self.assertTrue(self.alice.has_perm('trusts.change_trust:own', child))
        self.assertFalse(self.bob.has_perm('trusts.change_trust', child))
        self.assertTrue(self.alice.has_perm('trusts_zero_tests.change_ticket', ticket))
        self.assertTrue(
            self.alice.has_perm('trusts_zero_tests.change_ticket:meta_own', ticket)
        )
        self.assertFalse(self.bob.has_perm('trusts_zero_tests.change_ticket', ticket))
        self.alice.is_active = False
        self.alice.save()
        self._reload()
        self.assertFalse(self.alice.has_perm(self.cat_code, self.cat))
        self.assertFalse(AnonymousUser().has_perm(self.cat_code, self.cat))


class UnknownTerminalTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('unk')
        self._reload()

    def test_unknown_user_and_dict_fail_closed(self):
        backend = TrustModelBackend()
        self.assertEqual(backend.get_group_permissions(self.alice, {}), set())
        self.assertEqual(backend.get_all_permissions(self.alice, {}), set())
        self.assertFalse(backend.has_perm(self.alice, 'auth.change_user', self.alice))
        self.assertFalse(live_catalog().plan_for(User).records)
