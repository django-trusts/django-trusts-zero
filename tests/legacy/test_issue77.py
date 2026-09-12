"""Copied from django-trusts@948d6666342377b9472debb57d4a1e26e81402d1 ``trusts/test_issue77.py`` for issue #37 Zero-first coverage.

Final-state adaptations: Zero test app label, core registry APIs, no Content._conditions.

Generic multi-path / compiler-isolation / distributive-law / coordinator
classes were deleted (core-owned; restore under ``tests/core/`` with
neutral hosts). Zero keeps runnable live one-path authorization and
Zero-noun assertions — no ``@unittest.skip`` stand-ins.
"""

"""S3b: backend authorization and enumeration on compiler handles (issue #77).

Structural and behavioral tests only — no source-token or
``inspect.getsource`` assertions.
"""

from tests.apps import live_registry, live_config
from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db.models.query import QuerySet
from django.test import TestCase, override_settings

from tests.models import Category, Organization, Ticket, TestGroupJunction
from trusts.zero.backends import TrustModelBackend
from trusts.conditions import condition_refs
from trusts.core import common_permissions
from trusts.zero.models import (
    PermissionConditionNotQueryable,
    Trust,
    TrustUserPermission,
)
from trusts.query import is_active_principal
from tests.legacy.helpers import (
    enable_local_group_grant,
    forget_condition,
    get_or_create_root_user,
)

CONCRETE = 'trusts.zero.backends.TrustModelBackend'
MODEL = 'django.contrib.auth.backends.ModelBackend'

def _pks(qs):
    return set(qs.values_list('pk', flat=True))

def _perm(model, codename):
    return Permission.objects.get(
        content_type=ContentType.objects.get_for_model(model),
        codename=codename,
    )

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
        self.trust_a = Trust(settlor=self.alice, trust=root, title='S3b A %s' % suffix)
        self.trust_a.save()
        self.trust_b = Trust(settlor=self.alice, trust=root, title='S3b B %s' % suffix)
        self.trust_b.save()

    def _reload(self):
        self.alice = User.objects.get(pk=self.alice.pk)
        self.bob = User.objects.get(pk=self.bob.pk)
        self.carol = User.objects.get(pk=self.carol.pk)

class OnePathAuthorizationTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('one')
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
        self.carol_group = Group.objects.create(name='carol-s3b')
        self.carol.groups.add(self.carol_group)
        self.change.group_set.add(self.carol_group)
        enable_local_group_grant(self.trust_a, self.carol_group, self.change)
        self._reload()
        u, p, o = condition_refs()
        live_registry().register_permission_condition(Category, 'named', o.name == 'keep')

    def test_category_trustee_and_group_object_and_queryset(self):
        qs = Category.objects.filter(pk__in=[self.cat_a1.pk, self.cat_a2.pk])
        self.assertTrue(self.alice.has_perm(self.change_code, self.cat_a1))
        self.assertTrue(self.alice.has_perm(self.change_code, self.cat_a2))
        self.assertFalse(self.alice.has_perm(self.change_code, self.cat_b))
        self.assertFalse(self.alice.has_perm(self.add_code, self.cat_a1))
        self.assertFalse(self.bob.has_perm(self.change_code, self.cat_a1))
        self.assertTrue(self.alice.has_perm(self.change_code, qs))
        self.assertFalse(self.alice.has_perm(self.change_code, Category.objects.all()))
        self.assertTrue(self.carol.has_perm(self.change_code, self.cat_a1))
        self.assertTrue(self.carol.has_perm(self.change_code, qs))
        self.assertFalse(self.carol.has_perm(self.change_code, self.cat_b))
        self.assertEqual(
            _pks(Category.objects.permitted(self.change_code, self.alice)),
            {self.cat_a1.pk, self.cat_a2.pk},
        )
        self.assertEqual(
            _pks(Category.objects.permitted(self.change_code, self.carol)),
            {self.cat_a1.pk, self.cat_a2.pk},
        )

    def test_ticket_and_trust_object_queryset_parity(self):
        organization = Organization.objects.create(name='Org', manager=self.alice)
        ticket = Ticket.objects.create(
            trust=self.trust_a, title='t', owner=self.alice,
            organization=organization, status='open',
        )
        ticket_perm = _perm(Ticket, 'change_ticket')
        ticket_code = 'trusts_zero_tests.change_ticket'
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=ticket_perm,
        ).save()
        change_trust = _perm(Trust, 'change_trust')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=change_trust,
        ).save()
        child = Trust(settlor=self.alice, trust=self.trust_a, title='Child')
        child.save()
        self._reload()
        self.assertTrue(self.alice.has_perm(ticket_code, ticket))
        self.assertTrue(
            self.alice.has_perm(ticket_code, Ticket.objects.filter(pk=ticket.pk))
        )
        self.assertTrue(self.alice.has_perm('trusts.change_trust', child))
        self.assertTrue(
            self.alice.has_perm(
                'trusts.change_trust', Trust.objects.filter(pk=child.pk),
            )
        )
        self.assertFalse(self.bob.has_perm(ticket_code, ticket))
        self.assertIn(ticket.pk, _pks(Ticket.objects.permitted(ticket_code, self.alice)))
        self.assertIn(child.pk, _pks(Trust.objects.permitted('trusts.change_trust', self.alice)))

    def test_named_condition_constrains_and_does_not_create(self):
        conditioned = '%s:named' % self.change_code
        self.assertTrue(self.alice.has_perm(conditioned, self.cat_a1))
        self.assertFalse(self.alice.has_perm(conditioned, self.cat_a2))
        self.assertTrue(self.carol.has_perm(conditioned, self.cat_a1))
        qs_keep = Category.objects.filter(pk=self.cat_a1.pk)
        qs_drop = Category.objects.filter(pk=self.cat_a2.pk)
        self.assertTrue(self.alice.has_perm(conditioned, qs_keep))
        self.assertFalse(self.alice.has_perm(conditioned, qs_drop))
        self.assertFalse(self.bob.has_perm(conditioned, self.cat_a1))
        self.assertEqual(
            _pks(Category.objects.permitted(conditioned, self.alice)),
            {self.cat_a1.pk},
        )

    def test_inactive_and_anonymous_denied(self):
        self.alice.is_active = False
        self.alice.save()
        self.alice = User.objects.get(pk=self.alice.pk)
        self.assertFalse(is_active_principal(self.alice))
        self.assertFalse(self.alice.has_perm(self.change_code, self.cat_a1))
        self.assertFalse(
            self.alice.has_perm(
                self.change_code,
                Category.objects.filter(pk=self.cat_a1.pk),
            )
        )
        self.assertEqual(
            TrustModelBackend().get_all_permissions(self.alice, self.cat_a1),
            set(),
        )
        anon = AnonymousUser()
        self.assertFalse(
            TrustModelBackend().has_perm(anon, self.change_code, self.cat_a1)
        )
        self.assertEqual(
            TrustModelBackend().get_all_permissions(anon, self.cat_a1),
            set(),
        )

    def test_permission_identity_and_group_enumeration(self):
        backend = TrustModelBackend()
        all_perms = backend.get_all_permissions(self.alice, self.cat_a1)
        self.assertIn(self.change_code, all_perms)
        self.assertNotIn(self.add_code, all_perms)
        group_perms = backend.get_group_permissions(self.alice, self.cat_a1)
        self.assertNotIn(self.change_code, group_perms)
        carol_all = backend.get_all_permissions(self.carol, self.cat_a1)
        carol_group = backend.get_group_permissions(self.carol, self.cat_a1)
        self.assertIn(self.change_code, carol_all)
        self.assertIn(self.change_code, carol_group)
        qs = Category.objects.filter(pk__in=[self.cat_a1.pk, self.cat_a2.pk])
        self.assertIn(self.change_code, backend.get_all_permissions(self.alice, qs))
        self.assertIn(self.change_code, backend.get_all_permissions(self.carol, qs))
        self.assertNotIn(self.change_code, backend.get_group_permissions(self.alice, qs))
        self.assertIn(self.change_code, backend.get_group_permissions(self.carol, qs))

    def test_cache_attribute_is_not_an_authorization_source(self):
        backend = TrustModelBackend()
        self.assertFalse(hasattr(self.alice, '_trust_perm_cache'))
        backend.get_all_permissions(self.alice, self.cat_a1)
        self.assertTrue(hasattr(self.alice, '_trust_perm_cache'))
        self.assertIsInstance(self.alice._trust_perm_cache, dict)
        delattr(self.alice, '_trust_perm_cache')
        self.assertFalse(hasattr(self.alice, '_trust_perm_cache'))
        self.assertTrue(self.alice.has_perm(self.change_code, self.cat_a1))
        TrustUserPermission.objects.filter(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).delete()
        self.alice = User.objects.get(pk=self.alice.pk)
        self.assertFalse(self.alice.has_perm(self.change_code, self.cat_a1))

    def test_query_bounds_one_path(self):
        backend = TrustModelBackend()
        qs = Category.objects.filter(pk__in=[self.cat_a1.pk, self.cat_a2.pk])
        with self.assertNumQueries(1):
            self.assertTrue(backend.has_perm(self.alice, self.change_code, qs))
        with self.assertNumQueries(1):
            self.assertTrue(backend.has_perm(self.alice, self.change_code, self.cat_a1))
        with self.assertNumQueries(1):
            backend.get_all_permissions(self.alice, qs)
        with self.assertNumQueries(1):
            backend.get_group_permissions(self.carol, qs)
        self.assertTrue(
            self.alice.has_perms((self.change_code, self.change_code), qs)
        )
        with self.assertNumQueries(2):
            backend.has_perm(self.alice, self.change_code, qs)
            backend.has_perm(self.alice, self.add_code, qs)
        permitted = Category.objects.permitted(self.change_code, self.alice)
        self.assertIsInstance(permitted, QuerySet)
        self.assertIsNone(permitted._result_cache)
        with self.assertNumQueries(1):
            self.assertEqual(_pks(permitted), {self.cat_a1.pk, self.cat_a2.pk})
        page = Category.objects.permitted(
            self.change_code, self.alice,
        ).order_by('pk')[:1]
        with self.assertNumQueries(1):
            self.assertEqual(list(page), [self.cat_a1])

class ObjNoneBoundaryTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('none')
        self.cat_a = Category.objects.create(trust=self.trust_a, name='none')
        self.change = _perm(Category, 'change_category')
        self.change_code = 'trusts_zero_tests.change_category'
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).save()
        self.global_perm = _perm(User, 'change_user')
        self.alice.user_permissions.add(self.global_perm)
        self._reload()

    def test_trusts_only_obj_none_is_false_empty(self):
        backend = TrustModelBackend()
        self.assertFalse(backend.has_perm(self.alice, 'auth.change_user'))
        self.assertFalse(backend.has_perm(self.alice, self.change_code))
        self.assertEqual(backend.get_all_permissions(self.alice), set())
        self.assertEqual(backend.get_group_permissions(self.alice), set())
        with override_settings(AUTHENTICATION_BACKENDS=(CONCRETE,)):
            self.assertFalse(self.alice.has_perm('auth.change_user'))
            self.assertFalse(self.alice.has_perms(('auth.change_user',)))
            self.assertEqual(self.alice.get_all_permissions(), set())
        self.assertTrue(self.alice.has_perm(self.change_code, self.cat_a))
        self.assertNotIn('auth.change_user', backend.get_all_permissions(self.alice, self.cat_a))

    def test_modelbackend_plus_trusts_restores_globals_not_object_grants(self):
        with override_settings(AUTHENTICATION_BACKENDS=(MODEL, CONCRETE)):
            self.assertTrue(self.alice.has_perm('auth.change_user'))
            self.assertTrue(self.alice.has_perms(('auth.change_user',)))
            self.assertIn('auth.change_user', self.alice.get_all_permissions())
            self.assertFalse(
                TrustModelBackend().has_perm(self.alice, 'auth.change_user')
            )
            self.assertTrue(self.alice.has_perm(self.change_code, self.cat_a))
            self.assertFalse(self.alice.has_perm('auth.change_user', self.cat_a))
            self.assertNotIn(
                'auth.change_user',
                self.alice.get_all_permissions(self.cat_a),
            )

class UndeclaredJunctionRemainsHistoricalTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('junc')
        self.group = Group.objects.create(name='junc-group')
        self.junction = TestGroupJunction.objects.create(
            trust=self.trust_a, content=self.group, name='junc',
        )
        group_ct = ContentType.objects.get_for_model(Group)
        self.change_group, _created = Permission.objects.get_or_create(
            content_type=group_ct, codename='change_group',
            defaults={'name': 'Can change group'},
        )
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change_group,
        ).save()
        self._reload()

    def test_junction_group_uses_registered_plan(self):
        handle = live_config().configured_backend()
        self.assertTrue(handle.registry.plan_for(Group).records)
        self.assertFalse(handle.registry.plan_for(TestGroupJunction).records)
        code = 'auth.change_group'
        self.assertFalse(hasattr(TrustModelBackend, '_get_trusts'))
        self.assertTrue(self.alice.has_perm(code, self.group))
        self.assertFalse(self.bob.has_perm(code, self.group))
        qs = Group.objects.filter(pk=self.group.pk)
        self.assertTrue(self.alice.has_perm(code, qs))

class CoreCommonPermissionsProjectionTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('proj')
        self.cat_a = Category.objects.create(trust=self.trust_a, name='proj')
        self.change = _perm(Category, 'change_category')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).save()
        self._reload()

    def test_plan_and_handle_common_permissions_are_one_sql(self):
        handle = live_config().configured_backend()
        plan = handle.registry.plan_for(self.cat_a, user=self.alice)
        with self.assertNumQueries(1):
            codes = set(
                plan.common_permissions(self.alice, self.cat_a).values_list(
                    'codename', flat=True,
                )
            )
        self.assertIn('change_category', codes)
        qs = Category.objects.filter(pk=self.cat_a.pk)
        with self.assertNumQueries(1):
            rows = list(common_permissions((handle,), qs, self.alice))
        self.assertTrue(any(row.codename == 'change_category' for row in rows))
        empty = Category.objects.none()
        with self.assertNumQueries(1):
            self.assertFalse(list(common_permissions((handle,), empty, self.alice)))

class _CallLog(object):
    def __init__(self, impl):
        self.impl = impl
        self.calls = []

    def __call__(self, user, perm, obj):
        self.calls.append((user, perm, obj))
        return self.impl(user, perm, obj)

class QuerySetCallableConditionTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('cb')
        self.cat_a = Category.objects.create(trust=self.trust_a, name='keep')
        self.cat_b = Category.objects.create(trust=self.trust_a, name='drop')
        self.change = _perm(Category, 'change_category')
        self.change_code = 'trusts_zero_tests.change_category'
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).save()
        self._reload()
        self.log = _CallLog(lambda user, perm, obj: obj.name == 'keep')
        live_registry().register_permission_condition(Category, 'spy', self.log)
        self.conditioned = '%s:spy' % self.change_code

    def tearDown(self):
        forget_condition(Category, 'spy')
        super().tearDown()

    def _assert_zero_queryset_callbacks(self):
        qs = Category.objects.filter(pk__in=[self.cat_a.pk, self.cat_b.pk])
        backend = TrustModelBackend()
        with self.assertNumQueries(0):
            with self.assertRaises(PermissionConditionNotQueryable):
                backend.has_perm(self.alice, self.conditioned, qs)
        self.assertEqual(self.log.calls, [])
        with self.assertRaises(PermissionConditionNotQueryable):
            self.alice.has_perm(self.conditioned, qs)
        self.assertEqual(self.log.calls, [])
        with self.assertNumQueries(0):
            with self.assertRaises(PermissionConditionNotQueryable):
                self.alice.has_perms((self.conditioned,), qs)
        self.assertEqual(self.log.calls, [])

    @override_settings(TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS=True)
    def test_queryset_callable_raises_before_sql_or_callback(self):
        self._assert_zero_queryset_callbacks()
        self.assertTrue(self.alice.has_perm(self.conditioned, self.cat_a))
        self.assertEqual(len(self.log.calls), 1)
        self.assertFalse(self.alice.has_perm(self.conditioned, self.cat_b))
        self.assertEqual(len(self.log.calls), 2)

    def test_queryset_callable_raises_when_callbacks_disabled(self):
        self._assert_zero_queryset_callbacks()
        self.assertEqual(self.log.calls, [])
