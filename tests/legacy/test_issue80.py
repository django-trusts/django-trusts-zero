"""``filter_by_user_content_perm`` on the live catalog (issue #80).

``any_plan_records`` and multi-path gates were removed with Core's catalog.
Create-under-trust is ``filter_by_permitted_content`` through Zero's wrapper.
"""

from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db.models.query import QuerySet
from django.test import TestCase

from tests.legacy.helpers import enable_local_group_grant, get_or_create_root_user
from tests.models import AutoAdminCategory, Category, Organization, Ticket
from trusts.errors import PermissionConditionError
from trusts.zero.models import Trust, TrustUserPermission
from trusts.zero.views import NewTeamForm


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
        self.trust_a = Trust(settlor=self.alice, trust=root, title='S4 A %s' % suffix)
        self.trust_a.save()
        self.trust_b = Trust(settlor=self.alice, trust=root, title='S4 B %s' % suffix)
        self.trust_b.save()

    def _reload(self):
        self.alice = User.objects.get(pk=self.alice.pk)
        self.bob = User.objects.get(pk=self.bob.pk)
        self.carol = User.objects.get(pk=self.carol.pk)


class FilterByUserContentPermTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('gate')
        self.cat_a = Category.objects.create(trust=self.trust_a, name='s4-a')
        self.add = _perm(Category, 'add_category')
        self.change = _perm(Category, 'change_category')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.add,
        ).save()
        self.carol_group = Group.objects.create(name='carol-s4')
        self.carol.groups.add(self.carol_group)
        self.add.group_set.add(self.carol_group)
        enable_local_group_grant(self.trust_a, self.carol_group, self.add)
        self._reload()

    def _filter(self, user, content=Category, perm='add_category', **kwargs):
        return Trust.objects.filter_by_user_content_perm(
            user, content, perm, **kwargs
        )

    def test_registered_model_is_lazy_distinct_and_one_query(self):
        extra = [
            Trust(
                settlor=self.alice, trust=Trust.objects.get_root(),
                title='S4 extra %s' % i,
            )
            for i in range(8)
        ]
        Trust.objects.bulk_create(extra)
        qs = self._filter(self.alice)
        self.assertIsInstance(qs, QuerySet)
        self.assertIsNone(qs._result_cache)
        with self.assertNumQueries(1):
            pks = _pks(qs)
        self.assertEqual(pks, {self.trust_a.pk})
        self.assertNotIn(self.trust_b.pk, pks)
        self.assertNotIn(Trust.objects.get_root().pk, pks)

    def test_instance_and_proxy_use_the_same_registered_terminal(self):
        self.assertEqual(
            _pks(self._filter(self.alice, self.cat_a)),
            {self.trust_a.pk},
        )
        self.assertEqual(
            _pks(self._filter(self.alice, AutoAdminCategory, 'add_category')),
            {self.trust_a.pk},
        )

    def test_correct_permission_grants_wrong_permission_and_trust_deny(self):
        self.assertEqual(
            _pks(self._filter(self.alice, Category, 'add')), {self.trust_a.pk},
        )
        self.assertFalse(self._filter(self.alice, Category, 'change_category').exists())
        self.assertFalse(self._filter(self.bob, Category, 'add_category').exists())
        self.assertNotIn(self.trust_b.pk, _pks(self._filter(self.alice)))

    def test_group_grant_and_excluded_root(self):
        self.assertIn(self.trust_a.pk, _pks(self._filter(self.carol)))
        root = Trust.objects.get_root()
        TrustUserPermission(
            trust=root, entity=self.alice, permission=self.add,
        ).save()
        self._reload()
        self.assertNotIn(root.pk, _pks(self._filter(self.alice, exclude_root=True)))
        self.assertIn(root.pk, _pks(self._filter(self.alice, exclude_root=False)))

    def test_inactive_and_anonymous_deny(self):
        self.alice.is_active = False
        self.alice.save()
        self._reload()
        self.assertFalse(self._filter(self.alice).exists())
        self.assertFalse(self._filter(AnonymousUser()).exists())

    def test_condition_raises(self):
        with self.assertRaises(PermissionConditionError):
            self._filter(self.alice, Category, 'add_category:own')
        with self.assertRaises(PermissionConditionError):
            self._filter(self.alice, Organization, 'add:never')

    def test_unknown_model_is_none(self):
        qs = self._filter(self.alice, Organization, 'add')
        self.assertIsInstance(qs, QuerySet)
        self.assertIsNone(qs._result_cache)
        with self.assertNumQueries(0):
            self.assertFalse(qs.exists())
        self.assertFalse(self._filter(self.alice, User, 'add_user').exists())

    def test_declared_group_without_a_grant_is_empty(self):
        self.assertFalse(self._filter(self.alice, Group, 'change_group').exists())

    def test_ticket_and_trust_remain_supported(self):
        organization = Organization.objects.create(name='S4Org', manager=self.alice)
        Ticket.objects.create(
            trust=self.trust_a, title='s4-t', owner=self.alice,
            organization=organization, status='open',
        )
        ticket_add = _perm(Ticket, 'add_ticket')
        change_trust = _perm(Trust, 'change_trust')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=ticket_add,
        ).save()
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=change_trust,
        ).save()
        self._reload()
        self.assertEqual(
            _pks(self._filter(self.alice, Ticket, 'add_ticket')),
            {self.trust_a.pk},
        )
        self.assertEqual(
            _pks(self._filter(self.alice, Trust, 'change_trust')),
            {self.trust_a.pk},
        )


class NewTeamFormTrustChangeTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('form')
        self.change_trust = _perm(Trust, 'change_trust')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change_trust,
        ).save()
        self._reload()

    def test_new_team_form_lists_change_trust_targets_excluding_root(self):
        form = NewTeamForm(user=self.alice)
        qs = form.fields['trust'].queryset
        self.assertIsInstance(qs, QuerySet)
        self.assertIsNone(qs._result_cache)
        pks = _pks(qs)
        self.assertEqual(pks, {self.trust_a.pk})
        self.assertNotIn(Trust.objects.get_root().pk, pks)
        self.assertNotIn(self.trust_b.pk, pks)
        denied = NewTeamForm(user=self.bob)
        self.assertFalse(denied.fields['trust'].queryset.exists())
