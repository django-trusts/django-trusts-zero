"""Copied from django-trusts@948d6666342377b9472debb57d4a1e26e81402d1 ``trusts/test_issue67.py`` for issue #37 Zero-first coverage.

Final-state adaptations: Zero test app label, core registry APIs, no Content._conditions.
"""

"""Child H: first historical TUP→Trust←Category reader (issue #67).

Migrates the trustee half of ``ContentQuerySet.permitted`` for the
explicitly registered Category terminal. Backend ``has_perm`` stays on
the old path. Isolated core tests keep constructing their own
``IsolatedTarget()``. Trust-as-content is S1 (``test_issue70``).
Ticket is S2 (``test_issue72``).
"""

from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import models
from django.db.models.query import QuerySet
from django.test import SimpleTestCase, TestCase
from django.test.utils import isolate_apps

from tests.apps import (
    TestsConfig,
    isolated_owner,
    live_config,
    live_registry,
    publish_permission_condition,
    register_tests_terminals,
    tests_catalog,
    tests_registry,
)
import tests as tests_module
from tests.models import Category, Ticket
from trusts.zero.models import (
    Content,
    Trust,
    TrustGroup,
    TrustGroupPermission,
    TrustUserPermission,
)
from trusts.zero.query import filter_by_permitted_content
from tests.legacy.helpers import (
    enable_local_group_grant,
    forget_condition,
    get_or_create_root_user,
)
from trusts.plan.relations import RelationPlan
from trusts.errors import TrustsConfigurationError
from trusts.zero.registration import register_zero_content
from tests.apps import IsolatedTarget


def _pks(qs):
    return set(qs.values_list('pk', flat=True))


def _perm(model, codename):
    return Permission.objects.get(
        content_type=ContentType.objects.get_for_model(model),
        codename=codename,
    )


def _new_contributor(apps_registry):
    contributor = TestsConfig('tests', tests_module)
    contributor.apps = apps_registry
    return contributor


class TrustsRegistryOwnershipTest(SimpleTestCase):
    def test_catalog_is_built_in_ready_and_reentry_keeps_it(self):
        config = isolated_owner()
        with self.assertRaises(TrustsConfigurationError) as ctx:
            config.registry
        self.assertIn('catalog not built yet', str(ctx.exception))
        config.ready()
        first = config.get_catalog()
        self.assertEqual(first.records, ())
        config.ready()
        self.assertIs(config.get_catalog(), first)

        live = live_config()
        before = live.get_catalog()
        live.ready()
        self.assertIs(live.get_catalog(), before)
        self.assertTrue(before.plan_for(Trust).records)

    def test_reader_obtains_registry_via_app_config_not_package_root(self):
        import trusts

        live = live_registry()
        self.assertIsInstance(live.records, tuple)
        self.assertTrue(live.plan_for(Trust).records)
        self.assertFalse(live.plan_for(Category).records)
        self.assertIsNone(getattr(trusts, 'registry', None))
        self.assertIsNone(getattr(trusts, 'TrustsRegistry', None))
        self.assertIsNone(getattr(trusts, 'RelationPlan', None))
        self.assertIsNone(getattr(trusts, 'TrustsImplementationConfig', None))

    def test_isolated_core_registries_stay_independent(self):
        live = live_registry()
        isolated = IsolatedTarget()
        self.assertIsNot(isolated, live)
        self.assertEqual(isolated.records, ())
        self.assertTrue(live.records)

    def test_core_module_is_gone(self):
        with self.assertRaises(ModuleNotFoundError):
            import trusts.core  # noqa: F401

    def test_trusts_does_not_import_or_discover_tests_category(self):
        import trusts.apps as trusts_apps
        import trusts.models as trusts_models

        for module in (trusts_apps, trusts_models):
            self.assertNotIn('Category', vars(module))
            self.assertNotIn('Ticket', vars(module))


class ContributorIdempotenceTest(SimpleTestCase):
    def setUp(self):
        self.live_contributor = apps.get_app_config('trusts_zero_tests')
        self.installed = tests_catalog()

    def test_reenter_same_contributor_ready_is_noop(self):
        self.assertTrue(self.live_contributor.recorder.frozen)
        before = self.installed.records
        self.live_contributor.ready()
        self.assertIs(self.live_contributor.get_catalog(), self.installed)
        self.assertEqual(self.installed.records, before)
        self.assertTrue(self.installed.plan_for(Category).records)

    def test_different_root_category_registration_does_not_suppress_tup(self):
        class OtherCategoryGrant(models.Model):
            category = models.ForeignKey(Category, on_delete=models.CASCADE)
            user = models.ForeignKey(User, on_delete=models.CASCADE)
            permission = models.ForeignKey(Permission, on_delete=models.CASCADE)

            class Meta:
                app_label = 'trusts_zero_tests'

        isolated = IsolatedTarget()
        isolated.register(
            trust=OtherCategoryGrant,
            content='category',
            user='user',
            permission='permission',
        )
        register_tests_terminals(isolated)
        catalog = isolated.compile()
        self.assertEqual(len(catalog.records), 10)
        roots = {record.root for record in catalog.records}
        self.assertEqual(
            roots,
            {OtherCategoryGrant, TrustUserPermission, TrustGroup, TrustGroupPermission},
        )
        plan = catalog.plan_for(Category)
        self.assertEqual(len(plan.records), 4)
        self.assertEqual(self.installed.records, tests_catalog().records)

    def test_conflicting_contribution_reaches_register_and_fails_closed(self):
        isolated = IsolatedTarget()
        rev = Category._meta.get_field('trust').remote_field.get_accessor_name()
        isolated.register(
            trust=TrustUserPermission,
            content='trust__%s' % rev,
            user='permission',
            permission='entity',
        )
        with self.assertRaises(TrustsConfigurationError):
            register_zero_content(isolated, Category)
        self.assertEqual(len(isolated.records), 1)
        self.assertEqual(self.live_contributor.get_catalog().records, self.installed.records)

    def test_new_appconfig_registry_receives_declaration_again(self):
        before = self.installed.records
        contributor = _new_contributor(apps)
        contributor.ready()
        built = contributor.get_catalog()
        self.assertIsNot(built, self.installed)
        self.assertEqual(self.installed.records, before)
        self.assertEqual(len(built.records), 9)
        terminals = {record.content_model for record in built.records}
        self.assertEqual(
            terminals,
            {
                Category._meta.concrete_model,
                Ticket._meta.concrete_model,
                Group._meta.concrete_model,
            },
        )
        roots = {record.root for record in built.records}
        self.assertEqual(
            roots, {TrustUserPermission, TrustGroup, TrustGroupPermission},
        )
        self.assertEqual(
            len([
                record for record in built.records
                if record.root is TrustUserPermission
            ]),
            3,
        )


@isolate_apps(
    'tests',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    attr_name='isolated_apps',
)
class IsolatedAppsDoesNotDonateToLiveRegistryTest(SimpleTestCase):
    def test_isolate_apps_ready_does_not_touch_live_registry(self):
        live = live_registry()
        host = tests_registry()
        before_live = live.records
        before_host = host.records
        tup_category = [
            record for record in host.records
            if record.root is TrustUserPermission
            and record.content_model is Category._meta.concrete_model
        ]
        self.assertEqual(len(tup_category), 1)
        self.assertFalse(live.plan_for(Category).records)
        self.assertFalse(self.isolated_apps.is_installed('trusts'))
        contributor = TestsConfig('tests', tests_module)
        contributor.apps = self.isolated_apps
        contributor.ready()
        self.assertIsNone(getattr(contributor, '_trusts_tup_category_registry_id', None))
        self.assertIsNone(getattr(contributor, '_trusts_tup_ticket_registry_id', None))
        self.assertIsNone(getattr(contributor, '_trusts_tup_group_registry_id', None))
        self.assertEqual(live.records, before_live)
        self.assertEqual(host.records, before_host)
        self.assertTrue(contributor.get_catalog().plan_for(Category).records)
        self.assertIsNot(contributor.get_catalog(), host._catalog)


class CategoryPermittedRegistryTest(TestCase):
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

        publish_permission_condition(
            Category, 'named', lambda u, p, o: o.name == 'keep',
        )
        self.addCleanup(lambda: forget_condition(Category, 'named'))

    def _reload(self):
        self.alice = User.objects.get(pk=self.alice.pk)
        self.bob = User.objects.get(pk=self.bob.pk)
        self.carol = User.objects.get(pk=self.carol.pk)

    def _direct_pks(self, perm, user):
        return {
            obj.pk for obj in Category.objects.all()
            if user.has_perm(perm, obj)
        }

    def test_live_declaration_uses_meta_reverse_not_hardcoded_accessor(self):
        registry = tests_registry()
        rev = Category._meta.get_field('trust').remote_field.get_accessor_name()
        self.assertNotEqual(rev, 'tests_category_content')
        record = registry.plan_for(Category).records[0]
        self.assertIs(record.root, TrustUserPermission)
        self.assertIs(record.content_model, Category._meta.concrete_model)
        self.assertEqual(record.content_field, 'trust__%s' % rev)
        self.assertEqual(record.user_field, 'entity')
        self.assertEqual(record.permission_field, 'permission')

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
        registry = tests_registry()
        self.assertTrue(registry.plan_for(Category).records)
        TrustUserPermission.objects.all().delete()
        self._reload()
        self.assertTrue(registry.plan_for(Category).records)
        self.assertFalse(self.alice.has_perm(self.change_code, self.cat_a1))
        self.assertFalse(
            Category.objects.permitted(self.change_code, self.alice).exists()
        )
        self.assertEqual(
            _pks(Category.objects.permitted(self.change_code, self.carol)),
            {self.cat_a1.pk, self.cat_a2.pk},
        )

    def test_named_condition_constrains_the_complete_grant(self):
        conditioned = '%s:named' % self.change_code
        self.assertTrue(self.alice.has_perm(conditioned, self.cat_a1))
        self.assertFalse(self.alice.has_perm(conditioned, self.cat_a2))
        self.assertTrue(self.carol.has_perm(conditioned, self.cat_a1))
        self.assertFalse(self.carol.has_perm(conditioned, self.cat_a2))
        self.assertEqual(
            _pks(Category.objects.permitted(conditioned, self.alice)),
            {self.cat_a1.pk},
        )
        self.assertEqual(
            _pks(Category.objects.permitted(conditioned, self.carol)),
            {self.cat_a1.pk},
        )
        self.assertEqual(
            _pks(Category.objects.permitted(conditioned, self.alice)),
            self._direct_pks(conditioned, self.alice),
        )

    def test_registered_terminals_skip_scope_rows(self):
        host = tests_registry()
        zero = live_registry()
        self.assertTrue(host.plan_for(Category).records)
        self.assertTrue(zero.plan_for(Trust).records)
        self.assertTrue(host.plan_for(Ticket).records)
        self.assertTrue(host.plan_for(Group).records)
        self.assertFalse(zero.plan_for(Category).records)

        from tests.models import Organization

        org = Organization.objects.create(name='Org', manager=self.alice)
        ticket = Ticket.objects.create(
            trust=self.trust_a, title='t', owner=self.alice,
            organization=org, status='open',
        )
        TrustUserPermission(
            trust=self.trust_a,
            entity=self.alice,
            permission=_perm(Ticket, 'change_ticket'),
        ).save()
        self._reload()

        with patch('trusts.zero.query.filter_by_permitted_content', wraps=filter_by_permitted_content) as grant_q:
            list(Category.objects.permitted(self.change_code, self.alice))
            self.assertEqual(grant_q.call_count, 0)
            list(Trust.objects.permitted('trusts.change_trust', self.alice))
            self.assertEqual(grant_q.call_count, 0)
            list(Ticket.objects.permitted('trusts_zero_tests.change_ticket', self.alice))
            self.assertEqual(grant_q.call_count, 0)
        self.assertIn(ticket.pk, _pks(
            Ticket.objects.permitted('trusts_zero_tests.change_ticket', self.alice)
        ))

    def test_reader_uses_content_exists_not_filter_authorized(self):
        registry = tests_registry()
        plan = registry.plan_for(
            Category.objects.all(), user=self.carol, permission=self.change,
        )
        with patch.object(registry, 'filter_authorized') as filtered:
            with patch.object(
                RelationPlan, 'content_exists', wraps=plan.content_exists,
            ) as exists:
                list(Category.objects.permitted(self.change_code, self.carol))
        filtered.assert_not_called()
        self.assertEqual(exists.call_count, 1)

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
