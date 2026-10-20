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

import tests as tests_module
from tests.apps import TestsConfig, build_catalog, live_catalog, live_config
from tests.legacy.helpers import enable_local_group_grant, get_or_create_root_user
from tests.models import Category
from trusts.zero.models import Trust, TrustGroup, TrustGroupPermission, TrustUserPermission
from trusts.zero.registration import register_zero_content


def _pks(qs):
    return set(qs.values_list('pk', flat=True))


def _perm(model, codename):
    return Permission.objects.get(
        content_type=ContentType.objects.get_for_model(model),
        codename=codename,
    )


def _tup(catalog, model):
    matches = [
        record for record in catalog.plan_for(model).records
        if record.root is TrustUserPermission
    ]
    return matches[0]


class CategoryRegistrationShapeTest(SimpleTestCase):
    def test_reenter_contributor_ready_leaves_the_live_catalog(self):
        catalog = live_catalog()
        before = catalog.records
        apps.get_app_config('trusts_zero_tests').ready()
        self.assertIs(live_catalog(), catalog)
        self.assertEqual(live_catalog().records, before)

    def test_isolated_recorder_compiles_category_tup_shape(self):
        def contribute(recorder):
            register_zero_content(recorder, Category)

        catalog = build_catalog(contribute)
        rev = Category._meta.get_field('trust').remote_field.get_accessor_name()
        self.assertNotEqual(rev, 'tests_category_content')
        record = _tup(catalog, Category)
        self.assertIs(record.root, TrustUserPermission)
        self.assertIs(record.content_model, Category._meta.concrete_model)
        self.assertEqual(record.content_field, 'trust__%s' % rev)
        self.assertEqual(record.user_field, 'entity')
        self.assertEqual(record.permission_field, 'permission')
        roots = {row.root for row in catalog.records}
        self.assertEqual(
            roots, {TrustUserPermission, TrustGroup, TrustGroupPermission},
        )
        self.assertEqual(len(catalog.plan_for(Category).records), 3)

    def test_live_declaration_uses_meta_reverse(self):
        catalog = live_catalog()
        rev = Category._meta.get_field('trust').remote_field.get_accessor_name()
        record = _tup(catalog, Category)
        self.assertEqual(record.content_field, 'trust__%s' % rev)
        self.assertEqual(record.user_field, 'entity')
        self.assertEqual(record.permission_field, 'permission')
        self.assertTrue(catalog.plan_for(Category).records)
        self.assertTrue(catalog.plan_for(Trust).records)


@isolate_apps(
    'tests',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    attr_name='isolated_apps',
)
class IsolatedAppsDoesNotDonateToLiveCatalogTest(SimpleTestCase):
    def test_isolate_apps_ready_does_not_touch_live_catalog(self):
        catalog = live_catalog()
        before = catalog.records
        self.assertFalse(self.isolated_apps.is_installed('trusts'))
        contributor = TestsConfig('tests', tests_module)
        contributor.apps = self.isolated_apps
        contributor.ready()
        self.assertIs(live_catalog(), catalog)
        self.assertEqual(live_catalog().records, before)
        self.assertEqual(len([
            record for record in live_catalog().records
            if record.root is TrustUserPermission
            and record.content_model is Category._meta.concrete_model
        ]), 1)


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
        catalog = live_catalog()
        self.assertTrue(catalog.plan_for(Category).records)
        TrustUserPermission.objects.all().delete()
        self._reload()
        self.assertTrue(catalog.plan_for(Category).records)
        self.assertFalse(self.alice.has_perm(self.change_code, self.cat_a1))
        self.assertFalse(
            Category.objects.permitted(self.change_code, self.alice).exists()
        )
        self.assertEqual(
            _pks(Category.objects.permitted(self.change_code, self.carol)),
            {self.cat_a1.pk, self.cat_a2.pk},
        )

    def test_named_condition_constrains_the_complete_grant(self):
        def contribute(recorder):
            register_zero_content(recorder, Category)
            recorder.add_named_filter(
                Category, 'named', lambda u, p, o: o.name == 'keep',
            )

        catalog = build_catalog(contribute)
        conditioned = '%s:named' % self.change_code
        self.assertTrue(catalog.has_perm(self.alice, conditioned, self.cat_a1))
        self.assertFalse(catalog.has_perm(self.alice, conditioned, self.cat_a2))
        self.assertTrue(catalog.has_perm(self.carol, conditioned, self.cat_a1))
        self.assertFalse(catalog.has_perm(self.carol, conditioned, self.cat_a2))
        overlay = catalog.compile_registered_condition_q(
            Category, conditioned, self.alice,
        )
        alice_pks = set(
            catalog.filter_authorized(
                Category.objects.all(), self.alice, self.change,
            ).filter(overlay).values_list('pk', flat=True)
        )
        carol_overlay = catalog.compile_registered_condition_q(
            Category, conditioned, self.carol,
        )
        carol_pks = set(
            catalog.filter_authorized(
                Category.objects.all(), self.carol, self.change,
            ).filter(carol_overlay).values_list('pk', flat=True)
        )
        self.assertEqual(alice_pks, {self.cat_a1.pk})
        self.assertEqual(carol_pks, {self.cat_a1.pk})
        direct = {
            obj.pk for obj in Category.objects.all()
            if catalog.has_perm(self.alice, conditioned, obj)
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

    def test_ready_again_does_not_replace_the_catalog(self):
        catalog = live_catalog()
        before = catalog.records
        live_config().ready()
        self.assertIs(live_catalog(), catalog)
        self.assertEqual(live_catalog().records, before)
