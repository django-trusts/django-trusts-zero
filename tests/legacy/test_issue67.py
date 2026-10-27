"""Category relation plan and ``permitted`` (issue #67).

Registry swapping and sentinel identity were removed with Core's catalog.
Registration shape is an isolated recorder compiled to a catalog. Runtime
checks use the live catalog.
"""

from django.apps import apps
from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db.models.query import QuerySet
from django.test import SimpleTestCase, TestCase
from django.test.utils import isolate_apps

from tests.apps import TEST_BACKEND, ZERO_BACKEND, trust_rows
from tests.legacy.helpers import enable_local_group_grant, get_or_create_root_user
from tests.models import Category
from trusts.zero.apps import zero_config
from trusts.zero.models import Trust, TrustGroup, TrustGroupPermission, TrustUserPermission
from trusts.errors import TrustsConfigurationError


def _pks(qs):
    return set(qs.values_list('pk', flat=True))


def _perm(model, codename):
    return Permission.objects.get(
        content_type=ContentType.objects.get_for_model(model),
        codename=codename,
    )


class CategoryRegistrationShapeTest(SimpleTestCase):
    def test_reenter_contributor_ready_keeps_the_policy(self):
        from tests.backends import TestsBackend

        before = trust_rows(Category, backend=TEST_BACKEND)
        apps.get_app_config('trusts_zero_tests').ready()
        self.assertEqual(trust_rows(Category, backend=TEST_BACKEND), before)
        with self.assertRaises(TrustsConfigurationError):
            TestsBackend().get_registry().add_named_filter(
                Category, 'late', lambda u, p, o: False,
            )
        self.assertEqual(trust_rows(Category, backend=TEST_BACKEND), before)

    def test_live_declaration_uses_meta_reverse(self):
        rev = Category._meta.get_field('trust').remote_field.get_accessor_name()
        record = trust_rows(Category, TrustUserPermission, TEST_BACKEND)[0]
        self.assertNotEqual(rev, 'tests_category_content')
        self.assertEqual(record['content']['path'], 'trust__%s' % rev)
        self.assertEqual(record['user']['path'], 'entity')
        self.assertEqual(record['permission']['path'], 'permission')
        self.assertEqual(record['root'], 'trusts.TrustUserPermission')
        self.assertEqual(record['content']['model'], Category._meta.label)
        roots = {row['root'] for row in trust_rows(Category, backend=TEST_BACKEND)}
        self.assertEqual(
            roots, {
                'trusts.TrustUserPermission',
                'trusts.TrustGroup',
                'trusts.TrustGroupPermission',
            },
        )
        self.assertEqual(len(trust_rows(Category, backend=TEST_BACKEND)), 3)
        self.assertTrue(trust_rows(Trust))


class CategoryPermittedTest(TestCase):
    def setUp(self):
        super().setUp()
        call_command('create_trust_root')
        get_or_create_root_user(self)

        self.alice = User.objects.create_user('alice', 'alice@example.com', 'x')
        self.bob = User.objects.create_user('bob', 'bob@example.com', 'x')
        self.carol = User.objects.create_user('carol', 'carol@example.com', 'x')
        for user in (self.alice, self.bob, self.carol):
            user.is_active = True
            user.save()

        root = Trust.objects.get_root()
        self.trust_a = Trust(settlor=self.alice, trust=root, title='Trust A')
        self.trust_a.save()
        self.trust_b = Trust(settlor=self.bob, trust=root, title='Trust B')
        self.trust_b.save()

        self.cat_a1 = Category.objects.create(trust=self.trust_a, name='keep')
        self.cat_a2 = Category.objects.create(trust=self.trust_a, name='drop')
        self.cat_b = Category.objects.create(trust=self.trust_b, name='other')

        self.change = _perm(Category, 'change_category')
        self.add = _perm(Category, 'add_category')
        self.change_code = 'trusts_zero_tests.change_category'
        self.add_code = 'trusts_zero_tests.add_category'

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

    def _direct_pks(self, perm, user):
        return {
            obj.pk for obj in Category.objects.all()
            if user.has_perm(perm, obj)
        }

    def test_alice_tup_grants_sibling_categories_on_trust_a_not_b(self):
        qs = Category.objects.permitted(self.change_code, self.alice)
        self.assertEqual(_pks(qs), {self.cat_a1.pk, self.cat_a2.pk})
        self.assertTrue(self.alice.has_perm(self.change_code, self.cat_a1))
        self.assertTrue(self.alice.has_perm(self.change_code, self.cat_a2))
        self.assertFalse(self.alice.has_perm(self.change_code, self.cat_b))

    def test_bob_without_tup_is_denied(self):
        self.assertFalse(self.bob.has_perm(self.change_code, self.cat_a1))
        self.assertFalse(Category.objects.permitted(self.change_code, self.bob).exists())

    def test_wrong_permission_is_denied(self):
        self.assertFalse(self.alice.has_perm(self.add_code, self.cat_a1))
        self.assertFalse(Category.objects.permitted(self.add_code, self.alice).exists())

    def test_carol_group_only_grant_is_not_erased_by_trustee_branch(self):
        self.assertFalse(
            TrustUserPermission.objects.filter(entity=self.carol).exists()
        )
        self.assertTrue(self.carol.has_perm(self.change_code, self.cat_a1))
        self.assertTrue(self.carol.has_perm(self.change_code, self.cat_a2))
        self.assertFalse(self.carol.has_perm(self.change_code, self.cat_b))
        self.assertEqual(
            _pks(Category.objects.permitted(self.change_code, self.carol)),
            {self.cat_a1.pk, self.cat_a2.pk},
        )

    def test_has_perm_and_permitted_are_result_equivalent(self):
        for user, perm in (
            (self.alice, self.change_code),
            (self.bob, self.change_code),
            (self.carol, self.change_code),
            (self.alice, self.add_code),
        ):
            self.assertEqual(
                _pks(Category.objects.permitted(perm, user)),
                self._direct_pks(perm, user),
                (user.username, perm),
            )

    def test_permitted_is_lazy_paginated_and_one_query(self):
        qs = Category.objects.permitted(self.change_code, self.alice)
        self.assertIsInstance(qs, QuerySet)
        self.assertIsNone(qs._result_cache)
        with self.assertNumQueries(1):
            self.assertEqual(_pks(qs), {self.cat_a1.pk, self.cat_a2.pk})
        page = Category.objects.permitted(
            self.change_code, self.alice,
        ).order_by('pk')[:1]
        self.assertIsNone(page._result_cache)
        with self.assertNumQueries(1):
            self.assertEqual(list(page), [self.cat_a1])

    def test_no_tup_rows_deny_without_changing_registration(self):
        self.assertTrue(trust_rows(Category, backend=TEST_BACKEND))
        TrustUserPermission.objects.all().delete()
        self._reload()
        self.assertTrue(trust_rows(Category, backend=TEST_BACKEND))
        self.assertFalse(self.alice.has_perm(self.change_code, self.cat_a1))
        self.assertFalse(
            Category.objects.permitted(self.change_code, self.alice).exists()
        )
        self.assertEqual(
            _pks(Category.objects.permitted(self.change_code, self.carol)),
            {self.cat_a1.pk, self.cat_a2.pk},
        )

    def test_named_condition_constrains_the_complete_grant(self):
        conditioned = '%s:spy' % self.change_code
        self.assertTrue(self.alice.has_perm(conditioned, self.cat_a1))
        self.assertFalse(self.alice.has_perm(conditioned, self.cat_a2))
        self.assertTrue(self.carol.has_perm(conditioned, self.cat_a1))
        self.assertFalse(self.carol.has_perm(conditioned, self.cat_a2))
        alice_pks = _pks(Category.objects.permitted(conditioned, self.alice))
        carol_pks = _pks(Category.objects.permitted(conditioned, self.carol))
        self.assertEqual(alice_pks, {self.cat_a1.pk})
        self.assertEqual(carol_pks, {self.cat_a1.pk})
        direct = {
            obj.pk for obj in Category.objects.all()
            if self.alice.has_perm(conditioned, obj)
        }
        self.assertEqual(alice_pks, direct)

    def test_inactive_and_anonymous_remain_empty(self):
        self.alice.is_active = False
        self.alice.save()
        self._reload()
        self.assertFalse(
            Category.objects.permitted(self.change_code, self.alice).exists()
        )
        self.assertFalse(self.alice.has_perm(self.change_code, self.cat_a1))
        self.assertFalse(
            Category.objects.permitted(self.change_code, AnonymousUser()).exists()
        )

    def test_ready_again_keeps_the_policy(self):
        from trusts.zero.backends import TrustModelBackend

        before = trust_rows(Trust, backend=ZERO_BACKEND)
        zero_config().ready()
        self.assertEqual(trust_rows(Trust, backend=ZERO_BACKEND), before)
        with self.assertRaises(TrustsConfigurationError):
            TrustModelBackend().get_registry().add_named_filter(
                Trust, 'late', lambda u, p, o: u == o.settlor,
            )
        self.assertEqual(trust_rows(Trust, backend=ZERO_BACKEND), before)
