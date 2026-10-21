"""Backend authorization on the live catalog (issue #77).

Multi-path handles, historical fallback, and compiler isolation across
backends were removed with Core's catalog.
"""

from django.apps import apps
from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import connection, models
from django.db.models.query import QuerySet
from django.test import TestCase, TransactionTestCase, override_settings

from tests.apps import (
    category_spy, forget_models, isolated_catalog, live_catalog,
)
from tests.legacy.helpers import enable_local_group_grant, get_or_create_root_user
from tests.models import Category, Organization, Ticket
from trusts.backends import compile_permitted_users
from trusts.zero.backends import TrustModelBackend
from trusts.zero.models import Trust, TrustUserPermission


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
        self.assertIn(
            ticket.pk,
            _pks(Ticket.objects.permitted(ticket_code, self.alice)),
        )
        self.assertIn(
            child.pk,
            _pks(Trust.objects.permitted('trusts.change_trust', self.alice)),
        )

    def test_inactive_and_anonymous_denied(self):
        self.alice.is_active = False
        self.alice.save()
        self.alice = User.objects.get(pk=self.alice.pk)
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

    def test_deleting_the_grant_denies(self):
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

    def test_planted_cache_is_not_an_authorization_source(self):
        backend = TrustModelBackend()
        self.alice._trust_perm_cache = {}
        self.alice._perm_cache = set()
        self.assertTrue(self.alice.has_perm(self.change_code, self.cat_a1))
        self.assertIn(
            self.alice.pk,
            _pks(compile_permitted_users(self.cat_a1, self.change_code)),
        )
        self.alice._trust_perm_cache = {(self.change_code, self.cat_a1.pk): False}
        self.alice._perm_cache = set()
        self.assertTrue(self.alice.has_perm(self.change_code, self.cat_a1))
        self.assertEqual(
            _pks(Category.objects.permitted(self.change_code, self.alice)),
            {self.cat_a1.pk, self.cat_a2.pk},
        )

        TrustUserPermission.objects.filter(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).delete()
        self.alice = User.objects.get(pk=self.alice.pk)
        self.alice._trust_perm_cache = {(self.change_code, self.cat_a1.pk): True}
        self.alice._perm_cache = {self.change_code}
        self.assertFalse(self.alice.has_perm(self.change_code, self.cat_a1))
        self.assertFalse(
            Category.objects.permitted(self.change_code, self.alice).exists()
        )
        self.assertNotIn(
            self.alice.pk,
            _pks(compile_permitted_users(self.cat_a1, self.change_code)),
        )


class TrusteeAndGroupCoverageTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('dist')
        self.cat_a = Category.objects.create(trust=self.trust_a, name='c-a')
        self.cat_b = Category.objects.create(trust=self.trust_b, name='c-b')
        self.change = _perm(Category, 'change_category')
        self.change_code = 'trusts_zero_tests.change_category'
        self.alice_group = Group.objects.create(name='alice-dist')
        self.alice.groups.add(self.alice_group)
        self.change.group_set.add(self.alice_group)
        enable_local_group_grant(self.trust_a, self.alice_group, self.change)
        TrustUserPermission(
            trust=self.trust_b, entity=self.alice, permission=self.change,
        ).save()
        self._reload()

    def test_split_coverage_object_queryset_and_permitted(self):
        concrete = TrustModelBackend()
        self.assertTrue(concrete.has_perm(self.alice, self.change_code, self.cat_a))
        self.assertTrue(concrete.has_perm(self.alice, self.change_code, self.cat_b))
        self.assertTrue(self.alice.has_perm(self.change_code, self.cat_a))
        self.assertTrue(self.alice.has_perm(self.change_code, self.cat_b))
        qs = Category.objects.filter(pk__in=[self.cat_a.pk, self.cat_b.pk])
        self.assertTrue(self.alice.has_perm(self.change_code, qs))
        self.assertTrue(self.alice.has_perms((self.change_code,), qs))
        self.assertIn(self.change_code, self.alice.get_all_permissions(qs))
        permitted = Category.objects.permitted(self.change_code, self.alice)
        with self.assertNumQueries(1):
            self.assertEqual(_pks(permitted), {self.cat_a.pk, self.cat_b.pk})

    def test_failed_ceiling_cannot_borrow_a_fragment(self):
        self.change.group_set.remove(self.alice_group)
        TrustUserPermission.objects.filter(
            trust=self.trust_b, entity=self.alice,
        ).delete()
        self._reload()
        qs = Category.objects.filter(pk__in=[self.cat_a.pk, self.cat_b.pk])
        self.assertFalse(self.alice.has_perm(self.change_code, self.cat_a))
        self.assertFalse(self.alice.has_perm(self.change_code, self.cat_b))
        self.assertFalse(self.alice.has_perm(self.change_code, qs))
        self.assertFalse(
            Category.objects.permitted(self.change_code, self.alice).exists()
        )


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
            self.alice = User.objects.get(pk=self.alice.pk)
            self.assertFalse(self.alice.has_perm('auth.change_user'))
            self.assertFalse(self.alice.has_perms(('auth.change_user',)))
            self.assertEqual(self.alice.get_all_permissions(), set())
            self.assertTrue(self.alice.has_perm(self.change_code, self.cat_a))
        self.assertNotIn(
            'auth.change_user',
            backend.get_all_permissions(self.alice, self.cat_a),
        )

    def test_modelbackend_plus_trusts_restores_globals_not_object_grants(self):
        with override_settings(AUTHENTICATION_BACKENDS=(MODEL, CONCRETE)):
            self.alice = User.objects.get(pk=self.alice.pk)
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


class PlanCommonPermissionsTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('proj')
        self.cat_a = Category.objects.create(trust=self.trust_a, name='proj')
        self.change = _perm(Category, 'change_category')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).save()
        self._reload()

    def test_plan_common_permissions_are_one_sql(self):
        plan = live_catalog().plan_for(self.cat_a, user=self.alice)
        with self.assertNumQueries(1):
            codes = set(
                plan.common_permissions(self.alice, self.cat_a).values_list(
                    'codename', flat=True,
                )
            )
        self.assertIn('change_category', codes)


class RegisteredOrdinaryModelTest(TransactionTestCase):
    """An ordinary model authorized by an isolated catalog."""

    def test_registered_ordinary_instance_queryset_and_filter(self):
        class Memo(models.Model):
            title = models.CharField(max_length=40)

            class Meta:
                app_label = 'trusts_zero_tests'

        class MemoGrant(models.Model):
            memo = models.ForeignKey(Memo, on_delete=models.CASCADE)
            user = models.ForeignKey(User, on_delete=models.CASCADE)
            permission = models.ForeignKey(Permission, on_delete=models.CASCADE)

            class Meta:
                app_label = 'trusts_zero_tests'

        with connection.schema_editor() as editor:
            editor.create_model(Memo)
            editor.create_model(MemoGrant)
        try:
            get_or_create_root_user(self)
            call_command('create_trust_root')
            alice = User.objects.create_user('alice-memo', 'alice-memo@example.com', 'x')
            bob = User.objects.create_user('bob-memo', 'bob-memo@example.com', 'x')
            alice.is_active = True
            bob.is_active = True
            alice.save()
            bob.save()
            memo = Memo.objects.create(title='note')
            other = Memo.objects.create(title='other')
            ct = ContentType.objects.get_for_model(Memo)
            change, _created = Permission.objects.get_or_create(
                content_type=ct,
                codename='change_memo',
                defaults={'name': 'Can change memo'},
            )
            code = 'trusts_zero_tests.change_memo'
            MemoGrant.objects.create(memo=memo, user=alice, permission=change)

            def register(factory):
                factory.register(
                    trust=MemoGrant,
                    user='user',
                    permission='permission',
                    content='memo',
                )

            catalog = isolated_catalog(register)
            self.assertTrue(catalog.plan_for(Memo).records)
            self.assertTrue(catalog.has_perm(alice, code, memo))
            self.assertFalse(catalog.has_perm(alice, code, other))
            self.assertFalse(catalog.has_perm(bob, code, memo))
            self.assertIn(code, catalog.get_all_permissions(alice, memo))
            self.assertEqual(catalog.get_group_permissions(alice, memo), set())
            qs = Memo.objects.filter(pk=memo.pk)
            self.assertTrue(catalog.has_perm(alice, code, qs))
            self.assertIn(code, catalog.get_all_permissions(alice, qs))
            self.assertEqual(catalog.get_group_permissions(alice, qs), set())
            self.assertFalse(
                catalog.has_perm(
                    alice, code,
                    Memo.objects.filter(pk__in=[memo.pk, other.pk]),
                )
            )
            self.assertEqual(
                _pks(catalog.filter_authorized(Memo.objects.all(), alice, change)),
                {memo.pk},
            )
            self.assertFalse(
                catalog.filter_authorized(Memo.objects.all(), bob, change).exists()
            )
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(MemoGrant)
                editor.delete_model(Memo)
            forget_models(Memo, MemoGrant)
            apps.clear_cache()


class _BuilderLog(object):
    def __init__(self, impl):
        self.impl = impl
        self.calls = []

    def __call__(self, u, p, o):
        self.calls.append((u, p, o))
        return self.impl(u, p, o)


class BuilderOnceParityTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('spy')
        self.keep = Category.objects.create(trust=self.trust_a, name='keep')
        self.drop = Category.objects.create(trust=self.trust_a, name='drop')
        self.change = _perm(Category, 'change_category')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).save()
        self._reload()
        self.code = 'trusts_zero_tests.change_category:spy'

    def test_builder_once_object_and_queryset_parity(self):
        self.assertEqual(len(category_spy.calls), 1)
        self.assertTrue(self.alice.has_perm(self.code, self.keep))
        self.assertFalse(self.alice.has_perm(self.code, self.drop))
        only = Category.objects.filter(pk=self.keep.pk)
        both = Category.objects.filter(pk__in=[self.keep.pk, self.drop.pk])
        self.assertTrue(self.alice.has_perm(self.code, only))
        self.assertFalse(self.alice.has_perm(self.code, both))
        permitted = set(
            Category.objects.permitted(self.code, self.alice).values_list(
                'pk', flat=True,
            )
        )
        self.assertEqual(permitted, {self.keep.pk})
        catalog = live_catalog()
        self.assertIn(
            self.alice.pk,
            _pks(catalog.permitted_users(self.keep, self.code)),
        )
        self.assertNotIn(
            self.alice.pk,
            _pks(catalog.permitted_users(self.drop, self.code)),
        )
        self.assertEqual(len(category_spy.calls), 1)
