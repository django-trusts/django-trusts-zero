"""Copied from django-trusts@948d6666342377b9472debb57d4a1e26e81402d1 ``trusts/test_issue70.py`` for issue #37 Zero-first coverage.

Final-state adaptations: Zero test app label, core registry APIs, no Content._conditions.
"""

"""S1: package-owned Trust-as-content contribution (issue #70).

Registers ``TrustUserPermission → parent Trust ← child Trust`` on the
AppConfig-owned ``TrustsRegistry`` so ``Trust.objects.permitted(...)``
uses the common relation plan. Backend ``has_perm`` and
``filter_by_user_content_perm`` stay on the old path. Isolated core
tests keep constructing their own ``IsolatedTarget()``.
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
    apply_zero_trust_donation,
    isolate_live_registry,
    isolated_owner,
    live_config,
    live_registry,
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
    get_or_create_root_user,
)
from trusts.plan.relations import RelationPlan
from trusts.errors import TrustsConfigurationError
from trusts.zero.registration import register_zero_relations
from tests.apps import IsolatedTarget


def _pks(qs):
    return set(qs.values_list('pk', flat=True))


def _perm(model, codename):
    return Permission.objects.get(
        content_type=ContentType.objects.get_for_model(model),
        codename=codename,
    )


class _UnusableContents(object):
    """Stand-in that fails if the static content registry is read."""

    def __getitem__(self, key):
        raise AssertionError('Content._contents must not be consulted')

    def __contains__(self, key):
        raise AssertionError('Content._contents must not be consulted')

    def get(self, *args, **kwargs):
        raise AssertionError('Content._contents must not be consulted')

    def keys(self):
        raise AssertionError('Content._contents must not be consulted')

    def values(self):
        raise AssertionError('Content._contents must not be consulted')

    def items(self):
        raise AssertionError('Content._contents must not be consulted')


class TrustContributionIdempotenceTest(SimpleTestCase):
    def setUp(self):
        self.live = live_config()
        self.live_registry = self.live.registry

    def tearDown(self):
        self.live.registry = self.live_registry

    def test_reenter_same_contributor_ready_is_noop(self):
        self.assertTrue(self.live.recorder.frozen)
        before = self.live_registry.records
        self.live.ready()
        self.assertIs(self.live.get_catalog(), self.live_registry._catalog)
        self.assertEqual(self.live.registry.records, before)
        self.assertTrue(self.live.registry.plan_for(Trust).records)

    def test_ready_does_not_replace_registry(self):
        config = isolated_owner()
        apply_zero_trust_donation(config)
        config.ready()
        first = config.get_catalog()
        config.ready()
        self.assertIs(config.get_catalog(), first)
        self.assertEqual(len(first.records), 3)

        before = self.live.get_catalog()
        self.live.ready()
        self.assertIs(self.live.get_catalog(), before)

    def test_different_root_trust_registration_does_not_suppress_tup(self):
        class OtherTrustGrant(models.Model):
            trust = models.ForeignKey(Trust, on_delete=models.CASCADE)
            user = models.ForeignKey(User, on_delete=models.CASCADE)
            permission = models.ForeignKey(Permission, on_delete=models.CASCADE)

            class Meta:
                app_label = 'trusts'

        isolated = IsolatedTarget()
        isolated.register(
            trust=OtherTrustGrant,
            content='trust',
            user='user',
            permission='permission',
        )
        register_zero_relations(isolated)
        catalog = isolated.compile()
        self.assertEqual(len(catalog.records), 4)
        roots = {record.root for record in catalog.records}
        self.assertEqual(
            roots,
            {OtherTrustGrant, TrustUserPermission, TrustGroup, TrustGroupPermission},
        )
        plan = catalog.plan_for(Trust)
        self.assertEqual(len(plan.records), 4)

    def test_conflicting_contribution_reaches_register_and_fails_closed(self):
        isolated = IsolatedTarget()
        rev = Trust._meta.get_field('trust').remote_field.get_accessor_name()
        isolated.register(
            trust=TrustUserPermission,
            content='trust__%s' % rev,
            user='permission',
            permission='entity',
        )
        with self.assertRaises(TrustsConfigurationError):
            register_zero_relations(isolated)
        self.assertIsNone(getattr(isolated, '_trusts_tup_trust_registry_id', None))
        self.assertEqual(len(isolated.records), 1)
        with self.assertRaises(TrustsConfigurationError):
            register_zero_relations(isolated)
        self.assertEqual(len(isolated.records), 1)

    def test_new_appconfig_registry_receives_declaration_again(self):
        live_before = self.live_registry.records
        isolated = isolated_owner()
        with self.assertRaises(TrustsConfigurationError):
            isolated.registry
        apply_zero_trust_donation(isolated)
        isolated.ready()
        self.assertIsNone(getattr(isolated, '_trusts_tup_trust_registry_id', None))
        self.assertIsNot(isolated.get_catalog(), self.live.get_catalog())
        self.assertEqual(len(isolated.registry.records), 3)
        tup = [
            record for record in isolated.registry.records
            if record.root is TrustUserPermission
        ]
        self.assertEqual(len(tup), 1)
        self.assertIs(tup[0].content_model, Trust._meta.concrete_model)
        self.assertEqual(
            {record.root for record in isolated.registry.records},
            {TrustUserPermission, TrustGroup, TrustGroupPermission},
        )
        self.assertEqual(self.live_registry.records, live_before)

    def test_declaration_uses_meta_reverse_not_contents(self):
        isolated = IsolatedTarget()
        remote = Trust._meta.get_field('trust').remote_field
        with patch.object(
            remote, 'get_accessor_name', wraps=remote.get_accessor_name,
        ) as accessor:
            self.assertFalse(hasattr(Content, '_contents'))
            register_zero_relations(isolated)
        accessor.assert_called()
        rev = remote.get_accessor_name()
        self.assertEqual(len(isolated.records), 3)
        record = [
            row for row in isolated.records
            if row.root is TrustUserPermission
        ][0]
        self.assertIs(record.content_model, Trust._meta.concrete_model)
        self.assertEqual(record.content_field, 'trust__%s' % rev)
        self.assertEqual(record.user_field, 'entity')
        self.assertEqual(record.permission_field, 'permission')
        self.assertNotEqual(record.content_field, 'trust')

    def test_frozen_recorder_does_not_rewrite_a_swapped_catalog(self):
        isolated = IsolatedTarget()
        empty = isolated.compile()
        isolate_live_registry(self.live, empty)
        self.live.ready()
        self.assertEqual(self.live.get_catalog().records, ())
        self.assertFalse(self.live.registry.plan_for(Trust).records)


@isolate_apps(
    'tests',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    attr_name='isolated_apps',
)
class IsolatedAppsDoesNotDonateTrustContributionTest(SimpleTestCase):
    def test_isolate_apps_ready_does_not_touch_live_registry(self):
        live = live_registry()
        host = tests_registry()
        before_live = live.records
        before_host = host.records
        tup_trust = [
            record for record in live.records
            if record.root is TrustUserPermission
            and record.content_model is Trust._meta.concrete_model
        ]
        self.assertEqual(len(tup_trust), 1)
        self.assertFalse(live.plan_for(Ticket).records)
        self.assertTrue(host.plan_for(Ticket).records)
        self.assertFalse(self.isolated_apps.is_installed('trusts'))

        isolated = isolated_owner()
        isolated.apps = self.isolated_apps
        apply_zero_trust_donation(isolated)
        isolated.ready()
        self.assertIsNone(getattr(isolated, '_trusts_tup_trust_registry_id', None))
        self.assertIsNot(isolated.get_catalog(), live._catalog)
        self.assertEqual(live.records, before_live)

        contributor = TestsConfig('tests', tests_module)
        contributor.apps = self.isolated_apps
        contributor.ready()
        self.assertIsNone(getattr(contributor, '_trusts_tup_category_registry_id', None))
        self.assertIsNone(getattr(contributor, '_trusts_tup_ticket_registry_id', None))
        self.assertIsNone(getattr(contributor, '_trusts_tup_group_registry_id', None))
        self.assertEqual(live.records, before_live)
        self.assertEqual(host.records, before_host)
        self.assertTrue(contributor.get_catalog().plan_for(Ticket).records)


class TrustPermittedRegistryTest(TestCase):
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
        return {
            obj.pk for obj in Trust.objects.all()
            if user.has_perm(perm, obj)
        }

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
        registry = live_config().registry
        self.assertTrue(registry.plan_for(Trust).records)
        TrustUserPermission.objects.all().delete()
        self._reload()
        self.assertTrue(registry.plan_for(Trust).records)
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

    def test_reader_uses_content_exists_not_filter_authorized(self):
        registry = live_config().registry
        plan = registry.plan_for(
            Trust.objects.all(), user=self.carol, permission=self.change,
        )
        with patch.object(registry, 'filter_authorized') as filtered:
            with patch.object(
                RelationPlan, 'content_exists', wraps=plan.content_exists,
            ) as exists:
                list(Trust.objects.permitted(self.change_code, self.carol))
        filtered.assert_not_called()
        self.assertEqual(exists.call_count, 1)

    def test_create_under_trust_uses_scope_rows(self):
        with patch('trusts.zero.query.filter_by_permitted_content', wraps=filter_by_permitted_content) as grant_q:
            pks = _pks(Trust.objects.filter_by_user_content_perm(
                self.alice, Trust, 'change_trust',
            ))
            self.assertGreaterEqual(grant_q.call_count, 1)
        self.assertIn(self.trust_a.pk, pks)
        self.assertNotIn(self.child_a1.pk, pks)
        self.assertNotIn(self.child_a2.pk, pks)
        self.assertNotIn(self.trust_b.pk, pks)
        self.assertNotIn(self.child_b.pk, pks)

    def test_junction_stays_on_old_path(self):
        host = tests_registry()
        zero = live_registry()
        self.assertTrue(host.plan_for(Category).records)
        self.assertTrue(zero.plan_for(Trust).records)
        self.assertTrue(host.plan_for(Ticket).records)
        self.assertTrue(host.plan_for(Group).records)
        self.assertFalse(zero.plan_for(Category).records)

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
