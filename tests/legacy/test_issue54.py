"""#54 public authorization seams on the live catalog.

``set_condition_lookup``, ``filter_authorized_scopes`` handles, and
custom multi-registry scope graphs were removed with Core's catalog.
"""

from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.models import Q
from django.db.models.query import QuerySet
from django.test import SimpleTestCase, TestCase

from tests.apps import live_config
from trusts.zero.apps import ZeroConfig
from tests.legacy.helpers import enable_local_group_grant, get_or_create_root_user
from tests.models import Category, Organization
from trusts.apps import TrustsImplementationConfig
from trusts.decorators import filter_by_permitted_content
from trusts.errors import TrustsConfigurationError
from trusts.plan.relations import PlanQueryCompiler
from trusts.query import AuthorizedManager, AuthorizedQuerySet
from trusts.zero.backends import TrustModelBackend
from trusts.zero.models import Trust, TrustUserPermission
from trusts.zero.query import ContentQuerySet


def _pks(qs):
    return set(qs.values_list('pk', flat=True))


def _perm(model, codename):
    return Permission.objects.get(
        content_type=ContentType.objects.get_for_model(model),
        codename=codename,
    )


def _authorized(model, user, permission, extra_q=None):
    return AuthorizedQuerySet(model).authorized(user, permission, extra_q=extra_q)


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
        self.trust_a = Trust(settlor=self.alice, trust=root, title='C1 A %s' % suffix)
        self.trust_a.save()
        self.trust_b = Trust(settlor=self.alice, trust=root, title='C1 B %s' % suffix)
        self.trust_b.save()

    def _reload(self):
        self.alice = User.objects.get(pk=self.alice.pk)
        self.bob = User.objects.get(pk=self.bob.pk)
        self.carol = User.objects.get(pk=self.carol.pk)


class KernelConfigTest(TestCase):
    def test_live_owner_is_zero(self):
        with self.assertNumQueries(0):
            config = live_config()
        zero = apps.get_app_config('trusts')
        self.assertIs(type(config), ZeroConfig)
        self.assertIsInstance(config, TrustsImplementationConfig)
        self.assertEqual(config.name, 'trusts.zero')
        self.assertEqual(config.label, 'trusts')
        self.assertIs(config, live_config())
        self.assertIs(config, zero)
        self.assertIsInstance(TrustModelBackend.query_compiler, PlanQueryCompiler)


class LegacyMatrixBPairTest(TestCase):
    def test_pair_zero_owns_trusts_label_and_migration_keys(self):
        config = live_config()
        self.assertEqual(config.name, 'trusts.zero')
        self.assertEqual(config.label, 'trusts')
        self.assertIs(config, apps.get_app_config('trusts'))
        self.assertIs(apps.get_model('trusts', 'Trust'), Trust)
        self.assertTrue(apps.is_installed('trusts.zero'))
        self.assertFalse(apps.is_installed('trusts'))
        loader = MigrationLoader(connection)
        keys = {key for key in loader.disk_migrations if key[0] == 'trusts'}
        self.assertEqual(
            keys,
            {('trusts', '0001_initial'), ('trusts', '0002_trustgroup')},
        )
        initial = loader.disk_migrations[('trusts', '0001_initial')]
        self.assertTrue(initial.__module__.startswith('trusts.zero.migrations'))
        group = loader.disk_migrations[('trusts', '0002_trustgroup')]
        self.assertTrue(group.__module__.startswith('trusts.zero.migrations'))
        self.assertTrue(
            Trust.objects.filter(pk=Trust.objects.get_root().pk).exists()
        )


class AuthorizedQuerySetSurfaceTest(SimpleTestCase):
    def test_no_permitted_or_get_permission_on_generic_surface(self):
        self.assertFalse(hasattr(AuthorizedQuerySet, 'permitted'))
        self.assertFalse(hasattr(AuthorizedQuerySet, 'get_permission'))
        self.assertFalse(hasattr(AuthorizedManager, 'permitted'))
        self.assertFalse(hasattr(AuthorizedManager, 'get_permission'))
        self.assertTrue(issubclass(ContentQuerySet, QuerySet))
        self.assertTrue(issubclass(ContentQuerySet, AuthorizedQuerySet))
        self.assertTrue(hasattr(ContentQuerySet, 'permitted'))
        self.assertTrue(hasattr(AuthorizedManager, 'authorized'))
        self.assertFalse(hasattr(AuthorizedManager, 'permitted'))
        self.assertFalse(hasattr(AuthorizedManager, 'get_permission'))


class AuthorizedQuerySetLiveTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('authz')
        self.cat_a = Category.objects.create(trust=self.trust_a, name='c1-a')
        self.cat_b = Category.objects.create(trust=self.trust_b, name='c1-b')
        self.read = _perm(Category, 'read_category')
        self.change = _perm(Category, 'change_category')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.read,
        ).save()
        self.carol_group = Group.objects.create(name='carol-c1')
        self.carol.groups.add(self.carol_group)
        self.read.group_set.add(self.carol_group)
        enable_local_group_grant(self.trust_a, self.carol_group, self.read)
        self._reload()

    def test_wrong_permission_type_is_zero_sql_configuration_error(self):
        qs = AuthorizedQuerySet(Category)
        with patch.object(Category.objects, 'get_permission') as get_perm:
            with self.assertNumQueries(0):
                with self.assertRaises(TrustsConfigurationError):
                    qs.authorized(self.alice, 'read_category')
                with self.assertRaises(TrustsConfigurationError):
                    qs.authorized(self.alice, 'trusts_zero_tests.read_category')
                with self.assertRaises(TrustsConfigurationError):
                    qs.authorized(self.alice, 'read_category:own')
                with self.assertRaises(TrustsConfigurationError):
                    qs.authorized(self.alice, None)
        get_perm.assert_not_called()

    def test_instance_filter_matches_trustee_and_group_and_stays_lazy(self):
        qs = _authorized(Category, self.alice, self.read)
        self.assertIsInstance(qs, QuerySet)
        self.assertIsNone(qs._result_cache)
        with self.assertNumQueries(1):
            pks = _pks(qs)
        self.assertEqual(pks, {self.cat_a.pk})
        self.assertNotIn(self.cat_b.pk, pks)
        self.assertEqual(
            _pks(_authorized(Category, self.carol, self.read)),
            {self.cat_a.pk},
        )
        self.assertFalse(_authorized(Category, self.bob, self.read).exists())
        self.assertFalse(_authorized(Category, self.alice, self.change).exists())

    def test_inactive_user_is_denied_unless_skip_is_active(self):
        self.alice.is_active = False
        self.alice.save()
        self._reload()
        with patch.object(Category.objects, 'get_permission') as get_perm:
            pks = _pks(_authorized(Category, self.alice, self.read))
            inactive_pks = _pks(AuthorizedQuerySet(Category).authorized(
                self.alice, self.read, skip_is_active=True,
            ))
        get_perm.assert_not_called()
        self.assertEqual(pks, set())
        self.assertEqual(inactive_pks, {self.cat_a.pk})

    def test_extra_q_is_and_overlay_and_never_creates_a_grant(self):
        extra = Q(pk=self.cat_a.pk)
        self.assertEqual(
            _pks(_authorized(Category, self.alice, self.read, extra_q=extra)),
            {self.cat_a.pk},
        )
        self.assertFalse(
            _authorized(
                Category, self.alice, self.read, extra_q=Q(pk=self.cat_b.pk),
            ).exists()
        )
        self.assertFalse(
            _authorized(Category, self.bob, self.read, extra_q=extra).exists()
        )

    def test_unknown_terminal_is_none_without_grant_sql(self):
        qs = _authorized(Organization, self.alice, self.read)
        self.assertIsInstance(qs, QuerySet)
        self.assertIsNone(qs._result_cache)
        with self.assertNumQueries(0):
            self.assertFalse(qs.exists())

    def test_anonymous_is_denied_and_invalid_user_raises_without_codec(self):
        with self.assertNumQueries(0):
            for include_inactive in (False, True):
                rows = AuthorizedQuerySet(Category).authorized(
                    AnonymousUser(), self.read,
                    skip_is_active=include_inactive,
                )
                self.assertEqual(list(rows), [])
            for invalid_user in (None, object()):
                with self.assertRaises(TrustsConfigurationError):
                    _authorized(Category, invalid_user, self.read)


class FilterByPermittedContentLiveTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('scope-live')
        self.cat_a = Category.objects.create(trust=self.trust_a, name='c1-scope')
        self.add = _perm(Category, 'add_category')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.add,
        ).save()
        self.carol_group = Group.objects.create(name='carol-c1-scope')
        self.carol.groups.add(self.carol_group)
        self.add.group_set.add(self.carol_group)
        enable_local_group_grant(self.trust_a, self.carol_group, self.add)
        self._reload()

    def test_trust_is_prefix_of_category_for_trustee_and_registered_group(self):
        qs = filter_by_permitted_content(
            Trust.objects.all(), self.alice, self.add, content=Category,
        )
        self.assertIsInstance(qs, QuerySet)
        self.assertIsNone(qs._result_cache)
        with self.assertNumQueries(1):
            pks = _pks(qs)
        self.assertEqual(pks, {self.trust_a.pk})
        self.assertNotIn(self.trust_b.pk, pks)
        self.assertTrue(
            filter_by_permitted_content(
                Trust.objects.all(), self.carol, self.add, content=Category,
            ).exists()
        )
        self.assertIn(
            self.trust_a.pk,
            _pks(Trust.objects.filter_by_user_content_perm(
                self.carol, Category, 'add_category',
            )),
        )

    def test_content_terminal_and_unknown_scope_are_none(self):
        with self.assertNumQueries(0):
            self.assertFalse(
                filter_by_permitted_content(
                    Category.objects.all(), self.alice, self.add, content=Category,
                ).exists()
            )
            self.assertFalse(
                filter_by_permitted_content(
                    Organization.objects.all(), self.alice, self.add,
                    content=Category,
                ).exists()
            )
            self.assertFalse(
                filter_by_permitted_content(
                    Trust.objects.all(), self.alice, self.add, content=Organization,
                ).exists()
            )

    def test_permission_must_be_an_instance(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TrustsConfigurationError):
                filter_by_permitted_content(
                    Trust.objects.all(), self.alice, 'add_category',
                    content=Category,
                )
            with self.assertRaises(TrustsConfigurationError):
                filter_by_permitted_content(
                    Trust.objects.all(), self.alice, None, content=Category,
                )

    def test_wrong_user_and_wrong_permission_deny(self):
        self.assertFalse(
            filter_by_permitted_content(
                Trust.objects.all(), self.bob, self.add, content=Category,
            ).exists()
        )
        change = _perm(Category, 'change_category')
        self.assertFalse(
            filter_by_permitted_content(
                Trust.objects.all(), self.alice, change, content=Category,
            ).exists()
        )

    def test_legacy_create_under_trust_path_is_unchanged(self):
        pks = _pks(Trust.objects.filter_by_user_content_perm(
            self.alice, Category, 'add_category',
        ))
        self.assertEqual(pks, {self.trust_a.pk})
