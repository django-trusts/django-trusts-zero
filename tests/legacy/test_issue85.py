"""Junction-backed Group authorization (issue #85).

Swapped registries and mixin fan-out were removed with Core's catalog.
Group grants use the live catalog. The junction path is compiled from
an isolated recorder.
"""

from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from tests.apps import (
    junction_content_field,
    live_catalog,
)
from tests.legacy.helpers import enable_local_group_grant, get_or_create_root_user
from tests.models import Category, Organization, TestGroupJunction, Ticket
from trusts.backends import compile_permitted_users
from trusts.zero.backends import TrustModelBackend
from trusts.zero.models import Trust, TrustUserPermission
def _pks(qs):
    return set(qs.values_list('pk', flat=True))


def _perm(model, codename):
    return Permission.objects.get(
        content_type=ContentType.objects.get_for_model(model),
        codename=codename,
    )


def _tup(catalog):
    return [
        record for record in catalog.plan_for(Group).records
        if record.root is TrustUserPermission
    ][0]


class GroupRegistrationShapeTest(SimpleTestCase):
    def test_live_declaration_is_the_junction_path(self):
        catalog = live_catalog()
        rev = TestGroupJunction._meta.get_field('trust').remote_field.get_accessor_name()
        content_name = junction_content_field(TestGroupJunction).name
        record = _tup(catalog)
        self.assertEqual(record.content_path, ('trust', rev, content_name))
        self.assertEqual(record.content_field, 'trust__%s__%s' % (rev, content_name))
        self.assertIs(record.content_model, Group._meta.concrete_model)
        self.assertFalse(catalog.plan_for(TestGroupJunction).records)


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
        self.trust_a = Trust(settlor=self.alice, trust=root, title='S6 A %s' % suffix)
        self.trust_a.save()
        self.trust_b = Trust(settlor=self.alice, trust=root, title='S6 B %s' % suffix)
        self.trust_b.save()

    def _reload(self):
        self.alice = User.objects.get(pk=self.alice.pk)
        self.bob = User.objects.get(pk=self.bob.pk)
        self.carol = User.objects.get(pk=self.carol.pk)


class GroupAuthorizationTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('auth')
        self.group_a1 = Group.objects.create(name='s6-a1')
        self.group_a2 = Group.objects.create(name='s6-a2')
        self.group_b = Group.objects.create(name='s6-b')
        TestGroupJunction.objects.create(
            trust=self.trust_a, content=self.group_a1, name='j-a1',
        )
        TestGroupJunction.objects.create(
            trust=self.trust_a, content=self.group_a2, name='j-a2',
        )
        TestGroupJunction.objects.create(
            trust=self.trust_b, content=self.group_b, name='j-b',
        )
        self.change = _perm(Group, 'change_group')
        self.add = _perm(Group, 'add_group')
        self.change_code = 'auth.change_group'
        self.add_code = 'auth.add_group'
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).save()
        self.carol_group = Group.objects.create(name='carol-s6')
        self.carol.groups.add(self.carol_group)
        self.change.group_set.add(self.carol_group)
        enable_local_group_grant(self.trust_a, self.carol_group, self.change)
        self.cat_a = Category.objects.create(trust=self.trust_a, name='s6-cat')
        self.cat_change = _perm(Category, 'change_category')
        self.cat_code = 'trusts_zero_tests.change_category'
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.cat_change,
        ).save()
        self._reload()

    def test_direct_trustee_allow_and_deny(self):
        self.assertTrue(self.alice.has_perm(self.change_code, self.group_a1))
        self.assertTrue(self.alice.has_perm(self.change_code, self.group_a2))
        self.assertFalse(self.alice.has_perm(self.change_code, self.group_b))
        self.assertFalse(self.alice.has_perm(self.add_code, self.group_a1))
        self.assertFalse(self.bob.has_perm(self.change_code, self.group_a1))

    def test_group_only_grant_allow_and_deny(self):
        self.assertFalse(
            TrustUserPermission.objects.filter(entity=self.carol).exists()
        )
        self.assertTrue(self.carol.has_perm(self.change_code, self.group_a1))
        self.assertTrue(self.carol.has_perm(self.change_code, self.group_a2))
        self.assertFalse(self.carol.has_perm(self.change_code, self.group_b))
        self.assertFalse(self.carol.has_perm(self.add_code, self.group_a1))

    def test_instance_and_queryset_has_perm_has_perms(self):
        qs = Group.objects.filter(pk__in=[self.group_a1.pk, self.group_a2.pk])
        self.assertTrue(self.alice.has_perm(self.change_code, qs))
        self.assertTrue(self.alice.has_perms((self.change_code,), self.group_a1))
        self.assertTrue(self.alice.has_perms((self.change_code,), qs))
        self.assertFalse(self.alice.has_perms((self.add_code,), self.group_a1))
        self.assertFalse(self.alice.has_perms((self.change_code, self.add_code), qs))
        self.assertFalse(
            self.alice.has_perm(
                self.change_code,
                Group.objects.filter(pk__in=[self.group_a1.pk, self.group_b.pk]),
            )
        )

    def test_mixed_trust_all_match_denies(self):
        mixed = Group.objects.filter(pk__in=[self.group_a1.pk, self.group_b.pk])
        self.assertFalse(self.alice.has_perm(self.change_code, mixed))
        self.assertFalse(self.carol.has_perm(self.change_code, mixed))
        self.assertFalse(self.bob.has_perm(self.change_code, mixed))

    def test_enumeration_parity_and_direct_vs_group_split(self):
        alice_all = self.alice.get_all_permissions(self.group_a1)
        alice_group = self.alice.get_group_permissions(self.group_a1)
        self.assertIn(self.change_code, alice_all)
        self.assertNotIn(self.change_code, alice_group)
        self.assertEqual(alice_group, set())
        carol_all = self.carol.get_all_permissions(self.group_a1)
        carol_group = self.carol.get_group_permissions(self.group_a1)
        self.assertIn(self.change_code, carol_all)
        self.assertIn(self.change_code, carol_group)
        self.assertNotIn(self.add_code, carol_all)
        qs = Group.objects.filter(pk__in=[self.group_a1.pk, self.group_a2.pk])
        self.assertIn(self.change_code, self.alice.get_all_permissions(qs))
        self.assertEqual(self.alice.get_group_permissions(qs), set())
        self.assertIn(self.change_code, self.carol.get_group_permissions(qs))
        self.assertEqual(self.bob.get_all_permissions(self.group_a1), set())
        self.assertEqual(self.alice.get_all_permissions(self.group_b), set())

    def test_wrong_user_perm_sibling_inactive_anonymous_obj_none(self):
        self.assertFalse(self.bob.has_perm(self.change_code, self.group_a1))
        self.assertFalse(self.alice.has_perm(self.add_code, self.group_a1))
        self.assertFalse(self.alice.has_perm(self.change_code, self.group_b))
        backend = TrustModelBackend()
        self.assertFalse(backend.has_perm(self.alice, self.change_code))
        self.assertEqual(backend.get_all_permissions(self.alice), set())
        self.assertEqual(backend.get_group_permissions(self.alice), set())
        self.alice.is_active = False
        self.alice.save()
        self._reload()
        self.assertFalse(self.alice.has_perm(self.change_code, self.group_a1))
        self.assertEqual(self.alice.get_all_permissions(self.group_a1), set())
        anon = AnonymousUser()
        self.assertFalse(anon.has_perm(self.change_code, self.group_a1))
        self.assertEqual(anon.get_all_permissions(self.group_a1), set())

    def test_category_ticket_trust_unchanged(self):
        self.assertTrue(self.alice.has_perm(self.cat_code, self.cat_a))
        self.assertFalse(self.bob.has_perm(self.cat_code, self.cat_a))
        child = Trust(settlor=self.alice, trust=self.trust_a, title='s6-child')
        child.save()
        change_trust = _perm(Trust, 'change_trust')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=change_trust,
        ).save()
        org = Organization.objects.create(name='s6-org', manager=self.alice)
        ticket = Ticket.objects.create(
            trust=self.trust_a, title='s6-t', owner=self.alice,
            organization=org, status='open',
        )
        ticket_change = _perm(Ticket, 'change_ticket')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=ticket_change,
        ).save()
        self._reload()
        self.assertTrue(self.alice.has_perm('trusts.change_trust', child))
        self.assertFalse(self.bob.has_perm('trusts.change_trust', child))
        self.assertTrue(self.alice.has_perm('trusts_zero_tests.change_ticket', ticket))
        self.assertFalse(self.bob.has_perm('trusts_zero_tests.change_ticket', ticket))

    def test_protected_group_membership_is_not_a_category_trustee(self):
        self.alice.groups.add(self.group_a1)
        self._reload()
        lonely = Category.objects.create(trust=self.trust_b, name='lonely')
        self.assertFalse(self.alice.has_perm(self.cat_code, lonely))
        self.assertTrue(self.alice.has_perm(self.change_code, self.group_a1))

    def test_one_sql_grant_all_match_and_enumeration(self):
        extras = [Group.objects.create(name='s6-extra-%s' % i) for i in range(8)]
        for extra in extras:
            TestGroupJunction.objects.create(
                trust=self.trust_a, content=extra, name='j-%s' % extra.pk,
            )
        qs = Group.objects.filter(
            pk__in=[self.group_a1.pk, self.group_a2.pk] + [g.pk for g in extras],
        )
        with self.assertNumQueries(1):
            self.assertTrue(self.alice.has_perm(self.change_code, self.group_a1))
        with self.assertNumQueries(1):
            self.assertTrue(self.alice.has_perm(self.change_code, qs))
        with self.assertNumQueries(1):
            self.assertIn(self.change_code, self.alice.get_all_permissions(qs))
        with self.assertNumQueries(1):
            self.assertIn(self.change_code, self.carol.get_group_permissions(qs))

    def test_concrete_trustee_keeps_historical_group(self):
        self.alice.groups.add(self.carol_group)
        self._reload()
        backend = TrustModelBackend()
        self.assertTrue(backend.has_perm(self.alice, self.change_code, self.group_a1))
        self.assertIn(
            self.change_code,
            backend.get_group_permissions(self.alice, self.group_a1),
        )
        self.assertIn(
            self.alice.pk,
            _pks(compile_permitted_users(self.group_a1, self.change_code)),
        )
        TrustUserPermission.objects.filter(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).delete()
        self._reload()
        self.assertFalse(
            TrustUserPermission.objects.filter(
                entity=self.alice, permission=self.change,
            ).exists()
        )
        self.assertTrue(self.alice.has_perm(self.change_code, self.group_a1))
        self.assertIn(
            self.change_code,
            self.alice.get_group_permissions(self.group_a1),
        )
        self.assertIn(
            self.alice.pk,
            _pks(compile_permitted_users(self.group_a1, self.change)),
        )

    def test_create_under_trust_gate_opens_for_declared_group(self):
        pks = _pks(Trust.objects.filter_by_user_content_perm(
            self.alice, Group, 'change_group',
        ))
        self.assertEqual(pks, {self.trust_a.pk})
        self.assertFalse(
            Trust.objects.filter_by_user_content_perm(
                self.bob, Group, 'change_group',
            ).exists()
        )
