"""Zero pairing: Django user permissions stay separate from Trusts grants.

Core #314 removes the active-superuser shortcut from Zero's backend.
Ordinary ``user_permissions`` stay. ``with_perm`` is Django's direct and
group rows only. Trusts grants and a registered user override are
Core's ``get_permitted_users``.
"""

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase

from tests.legacy.helpers import get_or_create_root_user
from tests.models import Category
from tests.runtests import NORMAL_SUITE
from trusts.models import PermittedUsersMixin
from trusts.zero.backends import TrustModelBackend
from trusts.zero.models import Trust, TrustUserPermission


def _reload(user):
    return User.objects.get(pk=user.pk)


class DjangoUserPermissionBoundaryTest(TestCase):
    def setUp(self):
        get_or_create_root_user(self)
        call_command('create_trust_root')
        self.backend = TrustModelBackend()
        self.ordinary = User.objects.create_user('z314', 'z314@example.com', 'x')
        self.grouped = User.objects.create_user('z314g', 'z314g@example.com', 'x')
        self.trustee = User.objects.create_user('z314t', 'z314t@example.com', 'x')
        self.superuser = User.objects.create_superuser(
            'z314s', 'z314s@example.com', 'x',
        )
        self.view_user = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(User),
            codename='view_user',
        )
        self.ordinary.user_permissions.add(self.view_user)
        self.group = Group.objects.create(name='z314-viewers')
        self.group.permissions.add(self.view_user)
        self.grouped.groups.add(self.group)
        self.root = Trust.objects.get_root()
        self.org = Trust(settlor=self.ordinary, trust=self.root, title='Z314')
        self.org.save()
        self.category = Category.objects.create(trust=self.org, name='z314-cat')
        self.read = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Category),
            codename='read_category',
        )
        TrustUserPermission.objects.create(
            trust=self.org, entity=self.trustee, permission=self.read,
        )
        self.read_code = 'trusts_zero_tests.read_category'

    def test_module_is_on_the_zero_suite(self):
        self.assertIn('tests.test_issue314', NORMAL_SUITE)

    def test_ordinary_user_keeps_direct_permissions(self):
        user = _reload(self.ordinary)
        self.assertEqual(
            self.backend.get_user_permissions(user),
            {'auth.view_user'},
        )
        self.assertEqual(
            ModelBackend().get_user_permissions(_reload(self.ordinary)),
            {'auth.view_user'},
        )

    def test_active_superuser_does_not_receive_every_permission(self):
        via_model = ModelBackend().get_user_permissions(_reload(self.superuser))
        self.assertIn('auth.view_user', via_model)
        self.assertEqual(
            self.backend.get_user_permissions(_reload(self.superuser)),
            set(),
        )

        shared = _reload(self.superuser)
        self.assertEqual(self.backend.get_user_permissions(shared), set())
        self.assertIn('auth.view_user', ModelBackend().get_user_permissions(shared))

        shared = _reload(self.superuser)
        self.assertIn('auth.view_user', ModelBackend().get_user_permissions(shared))
        self.assertEqual(self.backend.get_user_permissions(shared), set())

        self.superuser.user_permissions.add(self.view_user)
        self.assertEqual(
            self.backend.get_user_permissions(_reload(self.superuser)),
            {'auth.view_user'},
        )

    def test_inactive_anonymous_and_object_checks_stay_empty(self):
        self.ordinary.is_active = False
        self.ordinary.save(update_fields=['is_active'])
        self.assertEqual(
            self.backend.get_user_permissions(_reload(self.ordinary)),
            set(),
        )
        self.assertEqual(
            self.backend.get_user_permissions(AnonymousUser()),
            set(),
        )
        self.assertEqual(
            self.backend.get_user_permissions(_reload(self.grouped), self.category),
            set(),
        )

    def test_with_perm_is_django_direct_and_group_permissions_only(self):
        holders = set(self.backend.with_perm(
            'auth.view_user', include_superusers=True,
        ))
        self.assertIn(self.ordinary, holders)
        self.assertIn(self.grouped, holders)
        self.assertNotIn(self.superuser, holders)
        self.assertNotIn(self.trustee, holders)

        self.superuser.user_permissions.add(self.view_user)
        holders = set(self.backend.with_perm(
            'auth.view_user', include_superusers=False,
        ))
        self.assertIn(_reload(self.superuser), holders)

    def test_trusts_grant_and_override_come_from_get_permitted_users(self):
        django_holders = set(self.backend.with_perm(
            self.read_code, include_superusers=True,
        ))
        self.assertNotIn(self.trustee, django_holders)
        self.assertNotIn(self.superuser, django_holders)

        permitted = set(PermittedUsersMixin.get_permitted_users(
            self.category, self.read,
        ))
        self.assertIn(self.trustee, permitted)
        self.assertNotIn(self.superuser, permitted)
        django_holders = set(self.backend.with_perm(
            self.read_code, include_superusers=True,
        ))
        self.assertNotIn(self.superuser, django_holders)
        self.assertNotIn(self.trustee, django_holders)
