"""S3a: path-scoped registries and aggregate list authorization (issue #75).

Backend ``has_perm`` / enumeration stay on the historical path. Structural
and behavioral tests only — no source-token or ``inspect.getsource``
assertions.

Copied from django-trusts ``948d6666342377b9472debb57d4a1e26e81402d1`` ``trusts/test_issue75.py``.
"""

from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.checks import Error, run_checks
from django.core.management import call_command
from django.db.models.query import QuerySet
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import isolate_apps

from tests.apps import (
    TestsConfig,
    apply_zero_trust_donation,
    install_writable_registry,
    isolate_live_registry,
    isolated_owner,
    clear_backend_cache,
    live_config,
    live_registry,
    override_apps_ready,
)
from tests.backends import (
    HostTrustModelBackend,
    MalformedCompilerBackend,
    MixinOnlyBackend,
    MissingCompilerBackend,
    RaisingCompilerBackend,
)
import tests as tests_module
from tests.models import Category, Organization, Ticket
from trusts.backends import TrustModelBackendMixin
from trusts.zero.backends import TrustModelBackend
from trusts.zero.models import Content, Trust, TrustUserPermission
from tests.legacy.helpers import (
    enable_local_group_grant,
    get_or_create_root_user,
)
from trusts.plan.relations import PlanQueryCompiler, RelationPlan
from trusts.compile.nodes import Ref
from trusts.errors import TrustsConfigurationError
from trusts.plan.contents import granted
from tests.apps import IsolatedTarget, configured_backend


CONCRETE = 'trusts.zero.backends.TrustModelBackend'
MIXIN = 'tests.backends.MixinOnlyBackend'
HOST = 'tests.backends.HostTrustModelBackend'
ALIASED = 'tests.backends.AliasedTrustModelBackend'
MISSING = 'tests.backends.MissingCompilerBackend'
MALFORMED = 'tests.backends.MalformedCompilerBackend'
RAISING = 'tests.backends.RaisingCompilerBackend'


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


def _contribute_category(registry):
    rev = Category._meta.get_field('trust').remote_field.get_accessor_name()
    registry.register(
        trust=TrustUserPermission,
        content='trust__%s' % rev,
        user='entity',
        permission='permission',
    )


def _contribute_ticket(registry):
    rev = Ticket._meta.get_field('trust').remote_field.get_accessor_name()
    registry.register(
        trust=TrustUserPermission,
        content='trust__%s' % rev,
        user='entity',
        permission='permission',
    )


def _category_rows(registry):
    return [
        record for record in registry.records
        if record.root is TrustUserPermission
        and record.content_model is Category._meta.concrete_model
    ]


def _trust_rows(registry):
    return [
        record for record in registry.records
        if record.root is TrustUserPermission
        and record.content_model is Trust._meta.concrete_model
    ]


def _evaluate(handle, queryset, user, permission):
    plan = handle.registry.plan_for(
        queryset, user=user, permission=permission,
    )
    return handle.compiler.complete_exists(plan, queryset, user, permission)


class _RegistryRestoreMixin(object):
    def setUp(self):
        super().setUp()
        self.live = live_config()
        self.saved_registries = dict(self.live.registries)
        self.saved_trust_sentinel = getattr(
            self.live, '_trusts_tup_trust_registry_id', None
        )
        self.saved_trust_ids = getattr(
            self.live, '_trusts_tup_trust_registry_ids', None
        )
        self.live_contributor = apps.get_app_config('trusts_zero_tests')
        self.saved_category_sentinel = getattr(
            self.live_contributor, '_trusts_tup_category_registry_id', None
        )
        self.saved_ticket_sentinel = getattr(
            self.live_contributor, '_trusts_tup_ticket_registry_id', None
        )
        self.saved_group_sentinel = getattr(
            self.live_contributor, '_trusts_tup_group_registry_id', None
        )

    def tearDown(self):
        self.live.registries.clear()
        self.live.registries.update(self.saved_registries)
        self.live._trusts_tup_trust_registry_id = self.saved_trust_sentinel
        if self.saved_trust_ids is None:
            if hasattr(self.live, '_trusts_tup_trust_registry_ids'):
                delattr(self.live, '_trusts_tup_trust_registry_ids')
        else:
            self.live._trusts_tup_trust_registry_ids = self.saved_trust_ids
        self.live_contributor._trusts_tup_category_registry_id = (
            self.saved_category_sentinel
        )
        self.live_contributor._trusts_tup_ticket_registry_id = (
            self.saved_ticket_sentinel
        )
        self.live_contributor._trusts_tup_group_registry_id = (
            self.saved_group_sentinel
        )
        super().tearDown()


class PathScopedRegistryStoreTest(_RegistryRestoreMixin, SimpleTestCase):
    def test_one_path_registry_alias_is_exact_store(self):
        handle = configured_backend()
        self.assertEqual(handle.path, CONCRETE)
        self.assertIs(handle.catalog, self.live.get_catalog())
        self.assertIs(handle.registry._catalog, self.live.registry._catalog)
        self.assertIs(self.live.registries[CONCRETE]._catalog, self.live.get_catalog())
        self.assertFalse(hasattr(TrustModelBackend, 'query_compiler'))
        self.assertIsInstance(handle.compiler, PlanQueryCompiler)
        self.assertIs(handle.compiler, handle.catalog.compiler)

    def test_duplicate_identical_paths_stay_listed(self):
        with override_settings(AUTHENTICATION_BACKENDS=(CONCRETE, CONCRETE)):
            self.assertEqual(
                self.live._configured_trusts_paths(), (CONCRETE, CONCRETE),
            )
            self.assertIs(
                configured_backend(CONCRETE).catalog, self.live.get_catalog(),
            )

    def test_same_class_alias_shares_the_zero_catalog(self):
        with override_settings(AUTHENTICATION_BACKENDS=(CONCRETE, ALIASED)):
            self.assertEqual(
                self.live._configured_trusts_paths(), (CONCRETE, ALIASED),
            )
            self.assertIs(
                configured_backend(CONCRETE).catalog,
                configured_backend(ALIASED).catalog,
            )
            self.assertTrue(self.live.registry.plan_for(Trust).records)

    def test_unlisted_mixin_still_constructs_its_app_catalog(self):
        handle = configured_backend(MIXIN)
        self.assertEqual(handle.path, MIXIN)
        self.assertIs(handle.catalog, MixinOnlyBackend().catalog)
        self.assertIsNot(handle.catalog, self.live.get_catalog())

    def test_modelbackend_only_leaves_the_built_catalog_in_place(self):
        with override_settings(AUTHENTICATION_BACKENDS=(
            'django.contrib.auth.backends.ModelBackend',
        )):
            self.assertEqual(self.live._configured_trusts_paths(), ())
            self.assertTrue(self.live.registry.plan_for(Trust).records)
            self.assertIs(configured_backend().catalog, self.live.get_catalog())
        with override_settings(AUTHENTICATION_BACKENDS=(CONCRETE, MIXIN)):
            self.assertEqual(
                self.live._configured_trusts_paths(), (CONCRETE, MIXIN),
            )
            self.assertIs(configured_backend().catalog, self.live.get_catalog())
            self.assertIsNot(
                configured_backend(MIXIN).catalog, self.live.get_catalog(),
            )

    def test_ready_does_not_replace_store_or_registry(self):
        store = self.live.registries
        first = self.live.get_catalog()
        self.live.ready()
        self.assertIs(self.live.registries, store)
        self.assertIs(self.live.get_catalog(), first)
        self.assertIs(self.live.registries[CONCRETE]._catalog, first)

    def test_frozen_recorder_does_not_rewrite_a_swapped_catalog(self):
        isolated = IsolatedTarget()
        empty = isolated.compile()
        isolate_live_registry(self.live, empty, CONCRETE)
        self.live.ready()
        self.assertEqual(self.live.get_catalog().records, ())

    def test_new_appconfig_gets_its_own_store(self):
        isolated = isolated_owner()
        with self.assertRaises(TrustsConfigurationError):
            isolated.registry
        apply_zero_trust_donation(isolated)
        isolated.ready()
        self.assertEqual(len(_trust_rows(isolated.registry)), 1)
        self.assertIsNot(isolated.get_catalog(), self.live.get_catalog())

    def test_compiler_lives_on_the_catalog_not_the_backend_class(self):
        from tests.apps import tests_catalog

        first = TrustModelBackend()
        second = TrustModelBackend()
        self.assertIs(first.catalog.compiler, second.catalog.compiler)
        self.assertIsInstance(first.catalog.compiler, PlanQueryCompiler)
        self.assertFalse(hasattr(TrustModelBackend, 'query_compiler'))
        self.assertFalse(hasattr(TrustModelBackendMixin, 'query_compiler'))
        mixin = MixinOnlyBackend()
        self.assertIs(mixin.catalog, tests_catalog())
        self.assertIsNot(mixin.catalog, first.catalog)


@isolate_apps(
    'tests',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    attr_name='isolated_apps',
)
class IsolatedAppsPathStoreTest(SimpleTestCase):
    def test_isolate_apps_without_trusts_does_not_donate(self):
        live = live_config()
        before = live.registry.records
        self.assertFalse(self.isolated_apps.is_installed('trusts'))
        contributor = TestsConfig('tests', tests_module)
        contributor.apps = self.isolated_apps
        contributor.ready()
        self.assertIsNone(
            getattr(contributor, '_trusts_tup_category_registry_id', None)
        )
        self.assertIsNone(
            getattr(contributor, '_trusts_tup_ticket_registry_id', None)
        )
        self.assertIsNone(
            getattr(contributor, '_trusts_tup_group_registry_id', None)
        )
        self.assertEqual(live.registry.records, before)


class ContributionPathTest(_RegistryRestoreMixin, SimpleTestCase):
    def test_explicit_path_contribution_writes_one_registry(self):
        from tests.apps import tests_catalog

        with override_settings(AUTHENTICATION_BACKENDS=(CONCRETE, MIXIN)):
            zero = configured_backend(CONCRETE)
            mixin = configured_backend(MIXIN)
            self.assertEqual(len(_category_rows(zero.registry)), 0)
            self.assertEqual(len(_category_rows(mixin.registry)), 1)
            self.assertEqual(
                self.live._configured_trusts_paths(), (CONCRETE, MIXIN),
            )
            self.assertIs(mixin.catalog, tests_catalog())
            self.assertTrue(zero.registry.plan_for(Trust).records)
            self.assertFalse(mixin.registry.plan_for(Trust).records)

    def test_alias_does_not_block_a_second_app_ready(self):
        with override_settings(AUTHENTICATION_BACKENDS=(CONCRETE, ALIASED)):
            before = self.live.get_catalog().records
            contributor = _new_contributor(apps)
            contributor.ready()
            self.assertEqual(self.live.get_catalog().records, before)
            self.assertIsNone(
                getattr(contributor, '_trusts_tup_category_registry_id', None)
            )
            self.assertTrue(contributor.get_catalog().plan_for(Category).records)

    def test_mixin_catalog_holds_content_terminals_not_trust(self):
        from tests.models import Category, Ticket

        with override_settings(AUTHENTICATION_BACKENDS=(CONCRETE, MIXIN)):
            mixin = configured_backend(MIXIN)
            zero = configured_backend(CONCRETE)
            self.assertTrue(mixin.registry.plan_for(Category).records)
            self.assertTrue(mixin.registry.plan_for(Ticket).records)
            self.assertTrue(mixin.registry.plan_for(Group).records)
            self.assertFalse(zero.registry.plan_for(Category).records)
            self.assertTrue(zero.registry.plan_for(Trust).records)

    def test_mixin_does_not_receive_package_trust(self):
        with override_settings(AUTHENTICATION_BACKENDS=(CONCRETE, MIXIN)):
            apply_zero_trust_donation(self.live)
            zero = configured_backend(CONCRETE)
            mixin = configured_backend(MIXIN)
            self.assertTrue(zero.registry.plan_for(Trust).records)
            self.assertFalse(mixin.registry.plan_for(Trust).records)

    def test_host_backend_shares_the_tests_catalog(self):
        with override_settings(AUTHENTICATION_BACKENDS=(CONCRETE, HOST)):
            apply_zero_trust_donation(self.live)
            host = configured_backend(HOST)
            zero = configured_backend(CONCRETE)
            self.assertEqual(len(_trust_rows(zero.registry)), 1)
            self.assertEqual(len(_trust_rows(host.registry)), 0)
            self.assertIs(host.catalog, configured_backend(MIXIN).catalog)

    def test_contributor_reentry_does_not_duplicate(self):
        apply_zero_trust_donation(self.live)
        handle = configured_backend(CONCRETE)
        before = handle.registry.records
        apply_zero_trust_donation(self.live)
        self.assertEqual(handle.registry.records, before)
        self.assertEqual(len(_trust_rows(handle.registry)), 1)

    def test_swapped_catalog_is_not_rewritten_when_frozen(self):
        isolated = IsolatedTarget()
        empty = isolated.compile()
        self.live.registries[CONCRETE] = empty
        apply_zero_trust_donation(self.live)
        self.assertEqual(self.live.get_catalog().records, ())


class CompilerProtocolTest(_RegistryRestoreMixin, SimpleTestCase):
    def test_backend_query_compiler_is_not_a_system_check(self):
        from tests.backends import MissingCompilerBackend, RaisingCompilerBackend

        with override_settings(AUTHENTICATION_BACKENDS=(
            MISSING, MALFORMED, RAISING, CONCRETE,
        )):
            ids = {message.id for message in run_checks()}
        self.assertNotIn('trusts.E004', ids)
        self.assertIsInstance(
            MissingCompilerBackend().catalog.compiler, PlanQueryCompiler,
        )
        self.assertIsInstance(
            RaisingCompilerBackend().catalog.compiler, PlanQueryCompiler,
        )
        self.assertFalse(getattr(
            RaisingCompilerBackend().catalog.compiler, 'historical_fallback', False,
        ))

    def test_listed_mixin_backends_share_their_app_catalog(self):
        with override_settings(AUTHENTICATION_BACKENDS=(CONCRETE, MISSING)):
            handles = self.live.configured_handles()
        self.assertEqual(
            [handle.path for handle in handles], [CONCRETE, MISSING],
        )
        self.assertIs(handles[0].catalog, live_config().get_catalog())
        self.assertIsNot(handles[1].catalog, handles[0].catalog)


class CompilerCheckQueryCountTest(TestCase):
    def test_system_checks_issue_zero_sql(self):
        with override_settings(AUTHENTICATION_BACKENDS=(MISSING, CONCRETE)):
            with self.assertNumQueries(0):
                run_checks()


class OnePathPermittedUnchangedTest(TestCase):
    def setUp(self):
        super().setUp()
        call_command('create_trust_root')
        get_or_create_root_user(self)
        self.alice = User.objects.create_user('alice', 'alice@example.com', 'x')
        self.carol = User.objects.create_user('carol', 'carol@example.com', 'x')
        for user in (self.alice, self.carol):
            user.is_active = True
            user.save()
        root = Trust.objects.get_root()
        self.trust_a = Trust(settlor=self.alice, trust=root, title='Trust A')
        self.trust_a.save()
        self.cat_a = Category.objects.create(trust=self.trust_a, name='keep')
        self.change = _perm(Category, 'change_category')
        self.change_code = 'trusts_zero_tests.change_category'
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).save()
        self.carol_group = Group.objects.create(name='carol-s3a')
        self.carol.groups.add(self.carol_group)
        self.change.group_set.add(self.carol_group)
        enable_local_group_grant(self.trust_a, self.carol_group, self.change)
        self.alice = User.objects.get(pk=self.alice.pk)
        self.carol = User.objects.get(pk=self.carol.pk)

    def test_category_ticket_trust_object_results_unchanged(self):
        self.assertEqual(
            _pks(Category.objects.permitted(self.change_code, self.alice)),
            {self.cat_a.pk},
        )
        self.assertEqual(
            _pks(Category.objects.permitted(self.change_code, self.carol)),
            {self.cat_a.pk},
        )
        organization = Organization.objects.create(name='Org', manager=self.alice)
        ticket = Ticket.objects.create(
            trust=self.trust_a, title='t', owner=self.alice,
            organization=organization, status='open',
        )
        TrustUserPermission(
            trust=self.trust_a,
            entity=self.alice,
            permission=_perm(Ticket, 'change_ticket'),
        ).save()
        self.alice = User.objects.get(pk=self.alice.pk)
        self.assertIn(
            ticket.pk,
            _pks(Ticket.objects.permitted('trusts_zero_tests.change_ticket', self.alice)),
        )
        child = Trust(settlor=self.alice, trust=self.trust_a, title='Child A')
        child.save()
        TrustUserPermission(
            trust=self.trust_a,
            entity=self.alice,
            permission=_perm(Trust, 'change_trust'),
        ).save()
        self.alice = User.objects.get(pk=self.alice.pk)
        self.assertIn(
            child.pk,
            _pks(Trust.objects.permitted('trusts.change_trust', self.alice)),
        )


class TwoPathAuthorizationTest(_RegistryRestoreMixin, TestCase):
    def setUp(self):
        super().setUp()
        call_command('create_trust_root')
        get_or_create_root_user(self)
        self.alice = User.objects.create_user('alice75', 'alice75@example.com', 'x')
        self.carol = User.objects.create_user('carol75', 'carol75@example.com', 'x')
        for user in (self.alice, self.carol):
            user.is_active = True
            user.save()
        root = Trust.objects.get_root()
        self.trust_a = Trust(settlor=self.alice, trust=root, title='S3a A')
        self.trust_a.save()
        self.trust_b = Trust(settlor=self.alice, trust=root, title='S3a B')
        self.trust_b.save()
        self.cat_a = Category.objects.create(trust=self.trust_a, name='c-a')
        self.cat_b = Category.objects.create(trust=self.trust_b, name='c-b')
        self.change = _perm(Category, 'change_category')
        self.change_code = 'trusts_zero_tests.change_category'
        self.ticket_perm = _perm(Ticket, 'change_ticket')
        self.ticket_code = 'trusts_zero_tests.change_ticket'

    def _reload(self):
        self.alice = User.objects.get(pk=self.alice.pk)
        self.carol = User.objects.get(pk=self.carol.pk)

    def test_grant_only_through_a(self):
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).save()
        self._reload()
        handle_a = configured_backend(MIXIN)
        self.assertTrue(handle_a.registry.plan_for(Category).records)
        qs = Category.objects.all()
        pred_a = _evaluate(handle_a, qs, self.alice, self.change)
        self.assertIsNotNone(pred_a)
        self.assertEqual(_pks(qs.filter(pred_a)), {self.cat_a.pk})
        permitted = Category.objects.permitted(self.change_code, self.alice)
        self.assertIsInstance(permitted, QuerySet)
        self.assertIsNone(permitted._result_cache)
        with self.assertNumQueries(1):
            self.assertEqual(_pks(permitted), {self.cat_a.pk})
        self.assertFalse(
            TrustModelBackend().has_perm(self.alice, self.change_code, self.cat_a)
        )

    def test_grant_only_through_b(self):
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).save()
        self._reload()
        handle_a = configured_backend(MIXIN)
        self.assertTrue(handle_a.registry.plan_for(Category).records)
        self.assertEqual(
            _pks(Category.objects.permitted(self.change_code, self.alice)),
            {self.cat_a.pk},
        )

    def test_grant_through_neither(self):
        self.assertFalse(
            Category.objects.permitted(self.change_code, self.alice).exists()
        )

    def test_aggregate_ors_both_complete_proofs_in_one_statement(self):
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).save()
        alice_group = Group.objects.create(name='alice-s3a-or')
        self.alice.groups.add(alice_group)
        self.change.group_set.add(alice_group)
        enable_local_group_grant(self.trust_b, alice_group, self.change)
        self._reload()
        handle_a = configured_backend(MIXIN)
        qs = Category.objects.all()
        pred_a = _evaluate(handle_a, qs, self.alice, self.change)
        # Concrete historical compiler: TUP on cat_a plus group on cat_b.
        self.assertEqual(_pks(qs.filter(pred_a)), {self.cat_a.pk, self.cat_b.pk})
        permitted = Category.objects.permitted(self.change_code, self.alice)
        self.assertIsInstance(permitted, QuerySet)
        self.assertIsNone(permitted._result_cache)
        with self.assertNumQueries(1):
            self.assertEqual(_pks(permitted), {self.cat_a.pk, self.cat_b.pk})
        page = Category.objects.permitted(
            self.change_code, self.alice,
        ).order_by('pk')[:1]
        self.assertIsNone(page._result_cache)
        with self.assertNumQueries(1):
            self.assertEqual(list(page), [self.cat_a])

    def test_failed_ceiling_cannot_use_other_path_fragment(self):
        self.carol_group = Group.objects.create(name='carol-s3a-ceiling')
        self.carol.groups.add(self.carol_group)
        self.change.group_set.add(self.carol_group)
        enable_local_group_grant(self.trust_a, self.carol_group, self.change)
        self.change.group_set.remove(self.carol_group)
        self._reload()
        handle_a = configured_backend(MIXIN)
        qs = Category.objects.all()
        pred_a = _evaluate(handle_a, qs, self.carol, self.change)
        self.assertEqual(_pks(qs.filter(pred_a)), set())
        self.assertFalse(
            Category.objects.permitted(self.change_code, self.carol).exists()
        )

    def test_different_terminals_route_only_through_applicable_handles(self):
        organization = Organization.objects.create(name='S3aOrg', manager=self.alice)
        ticket = Ticket.objects.create(
            trust=self.trust_a, title='s3a-t', owner=self.alice,
            organization=organization, status='open',
        )
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).save()
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.ticket_perm,
        ).save()
        self._reload()
        handle_a = configured_backend(MIXIN)
        self.assertTrue(handle_a.registry.plan_for(Category).records)
        self.assertTrue(handle_a.registry.plan_for(Ticket).records)
        self.assertEqual(
            _pks(Category.objects.permitted(self.change_code, self.alice)),
            {self.cat_a.pk},
        )
        self.assertEqual(
            _pks(Ticket.objects.permitted(self.ticket_code, self.alice)),
            {ticket.pk},
        )


class CompilerIsolationTest(_RegistryRestoreMixin, TestCase):
    def setUp(self):
        super().setUp()
        call_command('create_trust_root')
        get_or_create_root_user(self)
        self.carol = User.objects.create_user('carol-iso', 'carol-iso@example.com', 'x')
        self.carol.is_active = True
        self.carol.save()
        root = Trust.objects.get_root()
        self.trust_a = Trust(settlor=self.carol, trust=root, title='iso')
        self.trust_a.save()
        self.cat_a = Category.objects.create(trust=self.trust_a, name='iso-c')
        self.change = _perm(Category, 'change_category')
        self.change_code = 'trusts_zero_tests.change_category'
        self.carol_group = Group.objects.create(name='carol-iso-group')
        self.carol.groups.add(self.carol_group)
        self.change.group_set.add(self.carol_group)
        enable_local_group_grant(self.trust_a, self.carol_group, self.change)
        self.carol = User.objects.get(pk=self.carol.pk)

    def test_concrete_group_grant_is_not_inherited_by_mixin(self):
        self.assertFalse(
            TrustUserPermission.objects.filter(entity=self.carol).exists()
        )
        handle_a = configured_backend(MIXIN)
        qs = Category.objects.all()
        pred_a = _evaluate(handle_a, qs, self.carol, self.change)
        self.assertIsNotNone(pred_a)
        self.assertEqual(_pks(qs.filter(pred_a)), {self.cat_a.pk})
        permitted = Category.objects.permitted(self.change_code, self.carol)
        with self.assertNumQueries(1):
            self.assertEqual(_pks(permitted), {self.cat_a.pk})
        again = configured_backend(MIXIN)
        self.assertIs(again.catalog, handle_a.catalog)
        self.assertFalse(
            TrustModelBackend().has_perm(self.carol, self.change_code, self.cat_a)
        )

    def test_mixin_only_alone_uses_its_app_catalog(self):
        with override_settings(AUTHENTICATION_BACKENDS=(MIXIN,)):
            clear_backend_cache()
            self.assertEqual(self.live._configured_trusts_paths(), (MIXIN,))
            self.assertFalse(
                TrustModelBackend().has_perm(
                    self.carol, self.change_code, self.cat_a,
                )
            )
            self.assertTrue(
                MixinOnlyBackend().has_perm(
                    self.carol, self.change_code, self.cat_a,
                )
            )

    def test_raising_compiler_is_not_caught_by_aggregate(self):
        handle = configured_backend()
        exploding = RaisingCompilerBackend.query_compiler
        with patch.object(handle.compiler, 'complete_exists', exploding.complete_exists):
            with self.assertRaises(RuntimeError):
                list(Category.objects.permitted(self.change_code, self.carol))

    def test_missing_compiler_attribute_keeps_the_catalog_grant(self):
        with override_settings(AUTHENTICATION_BACKENDS=(MISSING,)):
            clear_backend_cache()
            ids = {check.id for check in run_checks()}
            self.assertNotIn('trusts.E004', ids)
            self.assertIsInstance(
                MissingCompilerBackend().catalog.compiler, PlanQueryCompiler,
            )
            self.assertTrue(
                Category.objects.permitted(self.change_code, self.carol).exists()
            )

    def test_broken_second_path_does_not_narrow_to_first(self):
        with override_settings(AUTHENTICATION_BACKENDS=(CONCRETE, MISSING)):
            # Unowned missing compiler is not consulted at runtime.
            permitted = Category.objects.permitted(self.change_code, self.carol)
            self.assertEqual(_pks(permitted), {self.cat_a.pk})


class ContentConditionsPreservedTest(TestCase):
    def test_conditions_live_on_the_handle_registry(self):
        self.assertFalse(hasattr(Content, '_conditions'))
        self.assertIsNotNone(
            live_registry().get_permission_condition_record(Trust, 'own')
        )
