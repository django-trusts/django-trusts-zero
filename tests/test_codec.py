"""Zero codec, registration, manager, and condition compatibility on IIa."""

from django.core.exceptions import ValidationError
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase

from trusts.models import AuthorizedQuerySet
from trusts.zero.models import (
    Content,
    Trust,
    TrustGroup,
    TrustGroupPermission,
    TrustUserPermission,
)
from trusts.zero.query import (
    ContentQuerySet,
    django_permission_filter,
)
from tests.apps import (
    TEST_BACKEND,
    ZERO_BACKEND,
    category_spy,
    named_filter_ids,
    trust_rows,
)
from tests.models import Category, Ticket
from trusts.errors import PermissionConditionError, TrustsConfigurationError


class RegistrationAndCodecTests(TestCase):
    def setUp(self):
        call_command('create_trust_root')
        self.user = User.objects.create_user('daniel', 'daniel@example.com', 'pass')
        self.other = User.objects.create_user('other', 'other@example.com', 'pass')
        self.root = Trust.objects.get(pk=1)
        self.org = Trust(settlor=self.user, title='Org', trust=self.root)
        self.org.save()
        self.child = Trust(settlor=self.user, title='Child', trust=self.org)
        self.child.save()
        self.isolated = Trust(settlor=self.other, title='OtherOrg', trust=self.root)
        self.isolated.save()
        ct = ContentType.objects.get_for_model(Trust)
        self.change = Permission.objects.get(content_type=ct, codename='change_trust')
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=self.change,
        ).save()

    def test_content_queryset_is_authorized_queryset_subclass(self):
        self.assertTrue(issubclass(ContentQuerySet, AuthorizedQuerySet))
        self.assertTrue(callable(ContentQuerySet.permitted))

    def test_tup_register_on_the_live_policy(self):
        records = trust_rows(Trust, TrustUserPermission, backend=ZERO_BACKEND)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['content']['model'], 'trusts.Trust')
        self.assertEqual(records[0]['user']['path'], 'entity')

    def test_tgp_register_uses_group_and_role_ceilings(self):
        role = trust_rows(Trust, TrustGroupPermission, backend=ZERO_BACKEND)
        grouped = trust_rows(Trust, TrustGroup, backend=ZERO_BACKEND)
        self.assertEqual(len(role), 1)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(role[0]['content']['model'], 'trusts.Trust')
        self.assertEqual(grouped[0]['content']['model'], 'trusts.Trust')
        self.assertNotIn('group', role[0])
        self.assertEqual(grouped[0]['group']['path'], 'group')
        self.assertEqual(grouped[0]['permission']['path'], 'group__permissions')
        self.assertEqual(role[0]['permission']['path'], 'permission')
        self.assertNotEqual(role[0].get('condition'), grouped[0].get('condition'))

    def test_live_policy_has_trust_category_ticket_and_own(self):
        self.assertTrue(trust_rows(Trust, TrustUserPermission, backend=ZERO_BACKEND))
        self.assertTrue(trust_rows(Category, TrustUserPermission, backend=TEST_BACKEND))
        self.assertTrue(trust_rows(Ticket, TrustUserPermission, backend=TEST_BACKEND))
        self.assertIn('trusts__Trust__own', named_filter_ids(Trust, ZERO_BACKEND))

    def test_permitted_and_has_perm_trustee_isolation(self):
        user = User.objects.get(pk=self.user.pk)
        other = User.objects.get(pk=self.other.pk)
        child = Trust.objects.get(pk=self.child.pk)
        isolated = Trust.objects.get(pk=self.isolated.pk)

        self.assertTrue(user.has_perm('trusts.change_trust', child))
        self.assertFalse(user.has_perm('trusts.change_trust', isolated))
        self.assertFalse(other.has_perm('trusts.change_trust', child))
        permitted = list(Trust.objects.permitted('change', user))
        self.assertIn(child, permitted)
        self.assertNotIn(isolated, permitted)

    def test_inactive_and_anonymous_are_empty(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(list(Trust.objects.permitted('change', self.user)), [])
        class Anon(object):
            is_anonymous = True
            is_authenticated = False
            is_active = False
        self.assertEqual(list(Trust.objects.permitted('change', Anon())), [])

    def test_get_permission_and_manager_surfaces(self):
        perm = Trust.objects.get_permission('change')
        self.assertEqual(perm.codename, 'change_trust')
        self.assertEqual(Trust.objects.get_root().pk, 1)
        trusts = Trust.objects.filter_by_user_perm(self.user)
        self.assertIn(self.org, trusts)
        self.assertNotIn(self.isolated, trusts)

    def test_filter_by_user_content_perm_trustee_and_fail_closed(self):
        qs = Trust.objects.filter_by_user_content_perm(
            self.user, Trust, 'change',
        )
        self.assertIn(self.org, qs)
        self.assertNotIn(self.root, qs)
        self.assertNotIn(self.isolated, qs)
        empty = Trust.objects.filter_by_user_content_perm(
            self.user, Category, 'add',
        )
        # Category is declared; user has no add_category grant.
        self.assertIsNone(empty._result_cache)
        self.assertEqual(list(empty), [])

    def test_filter_by_user_content_perm_resolves_on_content_model(self):
        add_category = Category.objects.get_permission('add')
        add_trust = Trust.objects.get_permission('add')
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=add_category,
        ).save()
        TrustUserPermission(
            trust=self.isolated, entity=self.user, permission=add_trust,
        ).save()
        qs = Trust.objects.filter_by_user_content_perm(
            self.user, Category, 'add',
        )
        self.assertIsNone(qs._result_cache)
        self.assertIn(self.org, qs)
        self.assertNotIn(self.isolated, qs)
        self.assertNotIn(self.root, qs)
        self.assertNotIn(self.child, qs)

    def test_filter_by_user_content_perm_rejects_condition(self):
        with self.assertRaises(PermissionConditionError):
            Trust.objects.filter_by_user_content_perm(
                self.user, Trust, 'change:own',
            )

    def test_trust_own_condition_compiles_on_permitted(self):
        # Trust-as-content is the parent hop: a TUP on org authorizes child
        # Trust rows, not the org identity row.
        permitted = list(Trust.objects.permitted('change:own', self.user))
        self.assertIn(self.child, permitted)
        self.assertNotIn(self.isolated, permitted)

    def test_ticket_own_condition_and_unregistered_code(self):
        ticket = Ticket(title='t', owner=self.user, trust=self.org)
        ticket.save()
        other_ticket = Ticket(title='o', owner=self.other, trust=self.org)
        other_ticket.save()
        read = Ticket.objects.get_permission('read')
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=read,
        ).save()
        permitted = list(Ticket.objects.permitted('read:own', self.user))
        self.assertIn(ticket, permitted)
        self.assertNotIn(other_ticket, permitted)
        with self.assertRaises(TrustsConfigurationError):
            list(Ticket.objects.permitted('read:nope', self.user))

    def test_named_filter_builder_is_not_reinvoked(self):
        before = len(category_spy.calls)
        self.assertGreaterEqual(before, 1)
        cat = Category(name='keep', trust=self.org)
        cat.save()
        other = Category(name='other', trust=self.org)
        other.save()
        read = Category.objects.get_permission('read')
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=read,
        ).save()
        user = User.objects.get(pk=self.user.pk)
        code = 'trusts_zero_tests.read_category:spy'
        self.assertTrue(user.has_perm(code, cat))
        self.assertFalse(user.has_perm(code, other))
        permitted = set(Category.objects.permitted('read:spy', user))
        self.assertIn(cat, permitted)
        self.assertNotIn(other, permitted)
        self.assertEqual(len(category_spy.calls), before)

    def test_group_local_grant_still_authorizes_via_zero_compiler(self):
        group = Group.objects.create(name='writers')
        group.user_set.add(self.user)
        group.permissions.add(self.change)
        other_child = Trust(settlor=self.other, title='GChild', trust=self.isolated)
        other_child.save()
        tg, _created = TrustGroup.objects.get_or_create(
            trust=self.isolated, group=group,
        )
        TrustGroupPermission.objects.create(trustgroup=tg, permission=self.change)
        user = User.objects.get(pk=self.user.pk)
        self.assertTrue(user.has_perm('trusts.change_trust', other_child))
        permitted = list(Trust.objects.permitted('change', user))
        self.assertIn(other_child, permitted)

    def test_trustgrouppermission_save_rejects_outside_ceiling(self):
        group = Group.objects.create(name='no-ceiling')
        tg, _created = TrustGroup.objects.get_or_create(
            trust=self.org, group=group,
        )
        with self.assertRaises(ValidationError):
            TrustGroupPermission.objects.create(
                trustgroup=tg, permission=self.change,
            )

    def test_r7_write_conveniences_are_absent(self):
        for name in (
            'grant', 'revoke',
        ):
            self.assertFalse(hasattr(Content, name), name)
        for name in (
            'associate_group',
            'grant_group_permission',
            'revoke_group_permission',
            'set_group_permissions',
        ):
            self.assertFalse(hasattr(Trust, name), name)
        for name in (
            'grant_permission',
            'revoke_permission',
            'set_permissions',
        ):
            self.assertFalse(hasattr(TrustGroup, name), name)
        self.assertTrue(callable(TrustGroupPermission.clean))
        self.assertTrue(callable(TrustGroupPermission.save))
        self.assertTrue(callable(TrustGroupPermission.objects.bulk_create))

    def test_django_permission_filter_is_the_codec(self):
        qs = Trust.objects.all()
        filtered = django_permission_filter(qs, 'change', self.user)
        self.assertIn(self.child, list(filtered))
