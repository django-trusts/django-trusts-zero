"""Trust-as-content registration and ``permitted`` (issue #70).

Swapping the live registry was removed with Core's catalog.
``register_zero_relations`` is idempotent on a fresh recorder, and the
compiled catalog answers ``has_perm`` and ``permitted``.
"""

from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db.models.query import QuerySet
from django.test import SimpleTestCase, TestCase

from tests.apps import (
    catalog_from_recorder, isolated_recorder, live_catalog, root_records,
)
from tests.legacy.helpers import enable_local_group_grant, get_or_create_root_user
from trusts.zero.models import (
    Trust,
    TrustGroup,
    TrustGroupPermission,
    TrustUserPermission,
)
from trusts.zero.registration import register_zero_relations


def _pks(qs):
    return set(qs.values_list('pk', flat=True))


def _perm(model, codename):
    return Permission.objects.get(
        content_type=ContentType.objects.get_for_model(model),
        codename=codename,
    )


def _tup(catalog):
    return root_records(catalog, TrustUserPermission, Trust)[0]


class TrustRelationRegistrationTest(SimpleTestCase):
    def test_register_zero_relations_is_idempotent_on_a_fresh_recorder(self):
        recorder = isolated_recorder()
        register_zero_relations(recorder)
        register_zero_relations(recorder)
        donated = catalog_from_recorder(recorder)
        self.assertEqual(len(root_records(donated, TrustUserPermission, Trust)), 1)
        catalog = live_catalog()
        self.assertEqual(len(root_records(catalog, TrustUserPermission, Trust)), 1)
        self.assertEqual(
            {record.root for record in catalog.records},
            {TrustUserPermission, TrustGroup, TrustGroupPermission},
        )
        self.assertEqual(len(catalog.plan_for(Trust).records), 3)
        rev = Trust._meta.get_field('trust').remote_field.get_accessor_name()
        record = _tup(catalog)
        self.assertIs(record.content_model, Trust._meta.concrete_model)
        self.assertEqual(record.content_field, 'trust__%s' % rev)
        self.assertNotEqual(record.content_field, 'trust')
        self.assertEqual(record.user_field, 'entity')
        self.assertEqual(record.permission_field, 'permission')

    def test_live_trust_plan_uses_the_parent_reverse(self):
        catalog = live_catalog()
        rev = Trust._meta.get_field('trust').remote_field.get_accessor_name()
        record = _tup(catalog)
        self.assertEqual(record.content_field, 'trust__%s' % rev)
        self.assertTrue(catalog.plan_for(Trust).records)


class TrustPermittedTest(TestCase):
    def setUp(self):
        super().setUp()
        call_command('create_trust_root')
        get_or_create_root_user(self)

        self.alice = User.objects.create_user('alice', 'alice@example.com', 'x')
        self.bob = User.objects.create_user('bob', 'bob@example.com', 'x')
        self.carol = User.objects.create_user('carol', 'carol@example.com', 'x')
        self.dave = User.objects.create_user('dave', 'dave@example.com', 'x')
        for user in (self.alice, self.bob, self.carol, self.dave):
            user.is_active = True
            user.save()

        root = Trust.objects.get_root()
        self.trust_a = Trust(settlor=self.alice, trust=root, title='Trust A')
        self.trust_a.save()
        self.trust_b = Trust(settlor=self.bob, trust=root, title='Trust B')
        self.trust_b.save()

        self.child_a1 = Trust(
            settlor=self.alice, trust=self.trust_a, title='Child A1',
        )
        self.child_a1.save()
        self.child_a2 = Trust(
            settlor=self.carol, trust=self.trust_a, title='Child A2',
        )
        self.child_a2.save()
        self.child_b = Trust(
            settlor=self.bob, trust=self.trust_b, title='Child B',
        )
        self.child_b.save()

        self.change = _perm(Trust, 'change_trust')
        self.add = _perm(Trust, 'add_trust')
        self.change_code = 'trusts.change_trust'
        self.add_code = 'trusts.add_trust'
        self.change_own = 'trusts.change_trust:own'

        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).save()

        self.carol_group = Group.objects.create(name='carol-group')
        self.carol.groups.add(self.carol_group)
        self.change.group_set.add(self.carol_group)
        enable_local_group_grant(self.trust_a, self.carol_group, self.change)
        self._reload()

    def _reload(self):
        self.alice = User.objects.get(pk=self.alice.pk)
        self.bob = User.objects.get(pk=self.bob.pk)
        self.carol = User.objects.get(pk=self.carol.pk)
        self.dave = User.objects.get(pk=self.dave.pk)

    def _direct_pks(self, perm, user):
        return {obj.pk for obj in Trust.objects.all() if user.has_perm(perm, obj)}

    def test_alice_tup_grants_sibling_children_on_trust_a_not_b(self):
        qs = Trust.objects.permitted(self.change_code, self.alice)
        self.assertEqual(_pks(qs), {self.child_a1.pk, self.child_a2.pk})
        self.assertTrue(self.alice.has_perm(self.change_code, self.child_a1))
        self.assertTrue(self.alice.has_perm(self.change_code, self.child_a2))
        self.assertFalse(self.alice.has_perm(self.change_code, self.child_b))
        self.assertFalse(self.alice.has_perm(self.change_code, self.trust_a))
        self.assertFalse(self.alice.has_perm(self.change_code, self.trust_b))

    def test_bob_without_tup_is_denied(self):
        self.assertFalse(self.bob.has_perm(self.change_code, self.child_a1))
        self.assertFalse(Trust.objects.permitted(self.change_code, self.bob).exists())

    def test_wrong_permission_is_denied(self):
        self.assertFalse(self.alice.has_perm(self.add_code, self.child_a1))
        self.assertFalse(Trust.objects.permitted(self.add_code, self.alice).exists())

    def test_carol_group_only_grant_is_not_erased_by_trustee_branch(self):
        self.assertFalse(
            TrustUserPermission.objects.filter(entity=self.carol).exists()
        )
        self.assertTrue(self.carol.has_perm(self.change_code, self.child_a1))
        self.assertTrue(self.carol.has_perm(self.change_code, self.child_a2))
        self.assertFalse(self.carol.has_perm(self.change_code, self.child_b))
        self.assertEqual(
            _pks(Trust.objects.permitted(self.change_code, self.carol)),
            {self.child_a1.pk, self.child_a2.pk},
        )

    def test_has_perm_and_permitted_are_result_equivalent(self):
        for user, perm in (
            (self.alice, self.change_code),
            (self.bob, self.change_code),
            (self.carol, self.change_code),
            (self.alice, self.add_code),
            (self.alice, self.change_own),
            (self.carol, self.change_own),
            (self.bob, self.change_own),
        ):
            self.assertEqual(
                _pks(Trust.objects.permitted(perm, user)),
                self._direct_pks(perm, user),
                (user.username, perm),
            )

    def test_permitted_is_lazy_paginated_and_one_query(self):
        qs = Trust.objects.permitted(self.change_code, self.alice)
        self.assertIsInstance(qs, QuerySet)
        self.assertIsNone(qs._result_cache)
        with self.assertNumQueries(1):
            self.assertEqual(_pks(qs), {self.child_a1.pk, self.child_a2.pk})
        page = Trust.objects.permitted(
            self.change_code, self.alice,
        ).order_by('pk')[:1]
        self.assertIsNone(page._result_cache)
        with self.assertNumQueries(1):
            self.assertEqual(list(page), [self.child_a1])

    def test_no_tup_rows_deny_without_changing_registration(self):
        catalog = live_catalog()
        self.assertTrue(catalog.plan_for(Trust).records)
        TrustUserPermission.objects.all().delete()
        self._reload()
        self.assertTrue(catalog.plan_for(Trust).records)
        self.assertFalse(self.alice.has_perm(self.change_code, self.child_a1))
        self.assertFalse(
            Trust.objects.permitted(self.change_code, self.alice).exists()
        )
        self.assertEqual(
            _pks(Trust.objects.permitted(self.change_code, self.carol)),
            {self.child_a1.pk, self.child_a2.pk},
        )

    def test_own_is_condition_overlay_and_does_not_create_a_grant(self):
        self.assertTrue(self.alice.has_perm(self.change_own, self.child_a1))
        self.assertFalse(self.alice.has_perm(self.change_own, self.child_a2))
        self.assertFalse(self.carol.has_perm(self.change_own, self.child_a1))
        self.assertTrue(self.carol.has_perm(self.change_own, self.child_a2))
        self.assertEqual(
            _pks(Trust.objects.permitted(self.change_own, self.alice)),
            {self.child_a1.pk},
        )
        self.assertEqual(
            _pks(Trust.objects.permitted(self.change_own, self.carol)),
            {self.child_a2.pk},
        )
        self.assertFalse(
            Trust.objects.permitted(self.change_own, self.bob).exists()
        )

        child_dave = Trust(
            settlor=self.dave, trust=self.trust_a, title='Child Dave',
        )
        child_dave.save()
        self.assertFalse(self.dave.has_perm(self.change_code, child_dave))
        self.assertFalse(self.dave.has_perm(self.change_own, child_dave))
        self.assertFalse(
            Trust.objects.permitted(self.change_own, self.dave).exists()
        )

        TrustUserPermission.objects.filter(entity=self.alice).delete()
        self._reload()
        self.assertFalse(self.alice.has_perm(self.change_own, self.child_a1))
        self.assertFalse(
            Trust.objects.permitted(self.change_own, self.alice).exists()
        )
        self.assertEqual(
            _pks(Trust.objects.permitted(self.change_own, self.carol)),
            {self.child_a2.pk},
        )

    def test_sibling_and_mixed_parent_isolation(self):
        TrustUserPermission(
            trust=self.trust_b, entity=self.alice, permission=self.add,
        ).save()
        self._reload()
        self.assertEqual(
            _pks(Trust.objects.permitted(self.change_code, self.alice)),
            {self.child_a1.pk, self.child_a2.pk},
        )
        self.assertEqual(
            _pks(Trust.objects.permitted(self.add_code, self.alice)),
            {self.child_b.pk},
        )
        self.assertNotIn(
            self.child_b.pk,
            _pks(Trust.objects.permitted(self.change_code, self.alice)),
        )
        self.assertNotIn(
            self.child_a1.pk,
            _pks(Trust.objects.permitted(self.add_code, self.alice)),
        )

    def test_create_under_trust_filters_parent_rows(self):
        pks = _pks(Trust.objects.filter_by_user_content_perm(
            self.alice, Trust, 'change_trust',
        ))
        self.assertIn(self.trust_a.pk, pks)
        self.assertNotIn(self.child_a1.pk, pks)
        self.assertNotIn(self.child_a2.pk, pks)
        self.assertNotIn(self.trust_b.pk, pks)
        self.assertNotIn(self.child_b.pk, pks)

    def test_inactive_and_anonymous_remain_empty(self):
        self.alice.is_active = False
        self.alice.save()
        self._reload()
        self.assertFalse(
            Trust.objects.permitted(self.change_code, self.alice).exists()
        )
        self.assertFalse(self.alice.has_perm(self.change_code, self.child_a1))
        self.assertFalse(
            Trust.objects.permitted(self.change_code, AnonymousUser()).exists()
        )
