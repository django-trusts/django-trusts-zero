"""Zero #248: explicit auth.Group registration, role path stays ordinary."""

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase

from trusts.zero.models import Role, Trust, TrustGroup, TrustGroupPermission
from trusts.zero.registration import register_zero_group
from tests.apps import isolated_backend
from tests.legacy.helpers import enable_local_group_grant, get_or_create_root_user
from tests.models import Category


class ExplicitGroupRegistrationTests(TestCase):
    def test_auth_group_record_is_explicit_and_role_is_not(self):
        backend = isolated_backend()
        register_zero_group(backend, (Trust,))
        grouped = backend.registry.records_for_root(TrustGroup)[0]
        role = backend.registry.records_for_root(TrustGroupPermission)[0]
        self.assertTrue(grouped.via_group)
        self.assertEqual(grouped.group_path, ('group',))
        self.assertEqual(grouped.group_model._meta.label, 'auth.Group')
        self.assertEqual(grouped.user_path, ('group', 'user'))
        self.assertEqual(grouped.permission_path, ('group', 'permissions'))
        self.assertEqual(grouped.permission_model._meta.label, 'auth.Permission')
        self.assertNotIn('permissions', grouped.group_path)
        self.assertFalse(role.via_group)
        self.assertEqual(role.user_path, ('trustgroup', 'group', 'user'))
        self.assertEqual(role.permission_path, ('permission',))
        self.assertEqual(role.group_path, ())


class ExplicitGroupAuthorizationTests(TestCase):
    def setUp(self):
        get_or_create_root_user(self)
        call_command('create_trust_root')
        self.user = User.objects.create_user('iss248', 'iss248@example.com', 'x')
        self.user.is_active = True
        self.user.save()
        self.other = User.objects.create_user('iss248b', 'iss248b@example.com', 'x')
        self.root = Trust.objects.get_root()
        self.org = Trust(settlor=self.user, trust=self.root, title='Iss248 Org')
        self.org.save()
        self.category = Category.objects.create(trust=self.org, name='iss248-cat')
        self.sibling = Category.objects.create(trust=self.org, name='iss248-sib')
        content_type = ContentType.objects.get_for_model(Category)
        self.read = Permission.objects.get(
            content_type=content_type, codename='read_category',
        )
        self.change = Permission.objects.get(
            content_type=content_type, codename='change_category',
        )
        self.group = Group.objects.create(name='iss248-group')
        self.group.user_set.add(self.user)
        self.read_code = 'trusts_zero_tests.read_category'
        self.change_code = 'trusts_zero_tests.change_category'

    def _reload(self):
        self.user = User.objects.get(pk=self.user.pk)
        self.other = User.objects.get(pk=self.other.pk)

    def test_direct_group_grant_feeds_group_and_ordinary_checks(self):
        self.group.permissions.add(self.read)
        enable_local_group_grant(self.org, self.group, self.read)
        self._reload()
        one = Category.objects.filter(pk=self.category.pk)
        both = Category.objects.filter(pk__in=[self.category.pk, self.sibling.pk])
        self.assertTrue(self.user.has_perm(self.read_code, self.category))
        self.assertTrue(self.user.has_perm(self.read_code, one))
        self.assertIn(self.read_code, self.user.get_all_permissions(self.category))
        self.assertEqual(
            self.user.get_group_permissions(self.category), {self.read_code},
        )
        self.assertEqual(
            self.user.get_group_permissions(one), {self.read_code},
        )
        self.assertIn(self.read_code, self.user.get_group_permissions(both))
        self.assertIn(
            self.category.pk,
            Category.objects.permitted('read', self.user).values_list(
                'pk', flat=True,
            ),
        )
        self.assertEqual(self.other.get_group_permissions(self.category), set())
        self.assertFalse(self.other.has_perm(self.read_code, self.category))

    def test_ungranted_group_permission_is_not_enumerated(self):
        self.group.permissions.add(self.read, self.change)
        enable_local_group_grant(self.org, self.group, self.read)
        self._reload()
        self.assertEqual(
            self.user.get_group_permissions(self.category), {self.read_code},
        )
        self.assertEqual(
            self.user.get_all_permissions(self.category), {self.read_code},
        )
        self.assertFalse(self.user.has_perm(self.change_code, self.category))
        self.assertNotIn(
            self.category.pk,
            Category.objects.permitted('change', self.user).values_list(
                'pk', flat=True,
            ),
        )
        self.assertFalse(
            Trust.objects.filter_by_user_content_perm(
                self.user, Category, 'change', exclude_root=True,
            ).filter(pk=self.org.pk).exists()
        )
        self.assertTrue(
            Trust.objects.filter_by_user_content_perm(
                self.user, Category, 'read', exclude_root=True,
            ).filter(pk=self.org.pk).exists()
        )

    def test_role_ceiling_authorizes_without_group_enumeration(self):
        role, _created = Role.objects.get_or_create(name='iss248-role')
        role.permissions.add(self.read)
        role.groups.add(self.group)
        self.assertFalse(self.group.permissions.filter(pk=self.read.pk).exists())
        enable_local_group_grant(self.org, self.group, self.read)
        self._reload()
        one = Category.objects.filter(pk=self.category.pk)
        self.assertTrue(self.user.has_perm(self.read_code, self.category))
        self.assertTrue(self.user.has_perm(self.read_code, one))
        self.assertIn(self.read_code, self.user.get_all_permissions(self.category))
        self.assertIn(self.read_code, self.user.get_all_permissions(one))
        self.assertEqual(self.user.get_group_permissions(self.category), set())
        self.assertEqual(self.user.get_group_permissions(one), set())
        self.assertIn(
            self.category.pk,
            Category.objects.permitted('read', self.user).values_list(
                'pk', flat=True,
            ),
        )

    def test_association_without_local_grant_denies(self):
        self.group.permissions.add(self.read)
        self.org.groups.add(self.group)
        self._reload()
        self.assertFalse(self.user.has_perm(self.read_code, self.category))
        self.assertEqual(self.user.get_group_permissions(self.category), set())
        self.assertEqual(self.user.get_all_permissions(self.category), set())
