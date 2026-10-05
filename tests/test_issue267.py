"""Zero paired with Core #267: content-type mismatch is a denial.

A direct ``TrustUserPermission`` and an explicit ``auth.Group`` grant
both store ``auth.Permission`` rows. A group that contains a category
permission and a group permission used to authorize each row on both
objects. The shared grant now requires ``Permission.content_type`` to
be the protected object's content type. The codename is not consulted.
Same-model grants stay, including ``add_topic_to_category``.
"""

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase

from trusts.zero.models import Trust, TrustUserPermission
from tests.apps import live_backend
from tests.legacy.helpers import enable_local_group_grant, get_or_create_root_user
from tests.models import Category, Organization, TestGroupJunction
from tests.runtests import NORMAL_SUITE


class ContentTypeMismatchZeroTest(TestCase):
    def setUp(self):
        get_or_create_root_user(self)
        call_command('create_trust_root')
        self.member = User.objects.create_user('z267', 'z267@example.com', 'x')
        self.member.is_active = True
        self.member.save()
        self.direct = User.objects.create_user('z267d', 'z267d@example.com', 'x')
        self.direct.is_active = True
        self.direct.save()
        self.superuser = User.objects.create_superuser(
            'z267s', 'z267s@example.com', 'x',
        )
        self.root = Trust.objects.get_root()
        self.org = Trust(settlor=self.member, trust=self.root, title='Z267 Org')
        self.org.save()
        self.category = Category.objects.create(trust=self.org, name='z267-cat')
        self.protected = Group.objects.create(name='z267-protected')
        TestGroupJunction.objects.create(
            trust=self.org, content=self.protected, name='z267-j',
        )
        category_type = ContentType.objects.get_for_model(Category)
        group_type = ContentType.objects.get_for_model(Group)
        self.read = Permission.objects.get(
            content_type=category_type, codename='read_category',
        )
        self.topic = Permission.objects.get(
            content_type=category_type, codename='add_topic_to_category',
        )
        self.change_group = Permission.objects.get(
            content_type=group_type, codename='change_group',
        )
        self.read_code = 'trusts_zero_tests.read_category'
        self.topic_code = 'trusts_zero_tests.add_topic_to_category'
        self.group_code = 'auth.change_group'
        self.members = Group.objects.create(name='z267-members')
        self.members.user_set.add(self.member)
        self.members.permissions.add(self.read, self.topic, self.change_group)
        enable_local_group_grant(
            self.org, self.members, self.read, self.topic, self.change_group,
        )
        TrustUserPermission.objects.create(
            trust=self.org, entity=self.direct, permission=self.read,
        )
        TrustUserPermission.objects.create(
            trust=self.org, entity=self.direct, permission=self.change_group,
        )
        self._reload()

    def _reload(self):
        self.member = User.objects.get(pk=self.member.pk)
        self.direct = User.objects.get(pk=self.direct.pk)
        self.superuser = User.objects.get(pk=self.superuser.pk)

    def test_module_is_on_the_zero_suite(self):
        self.assertIn('tests.test_issue267', NORMAL_SUITE)

    def test_group_grant_keeps_same_model_and_denies_the_cross(self):
        self.assertTrue(self.member.has_perm(self.read_code, self.category))
        self.assertTrue(self.member.has_perm(self.topic_code, self.category))
        self.assertTrue(self.member.has_perm(self.read, self.category))
        self.assertTrue(self.member.has_perm(self.group_code, self.protected))
        self.assertTrue(self.member.has_perm(self.change_group, self.protected))

        with self.assertNumQueries(1):
            self.assertFalse(self.member.has_perm(self.group_code, self.category))
        with self.assertNumQueries(1):
            self.assertIs(
                self.member.has_perm(self.change_group, self.category), False,
            )
        with self.assertNumQueries(1):
            self.assertFalse(self.member.has_perm(self.read_code, self.protected))
        with self.assertNumQueries(1):
            self.assertIs(
                self.member.has_perm(self.topic, self.protected), False,
            )

        self.assertEqual(
            self.member.get_all_permissions(self.category),
            {self.read_code, self.topic_code},
        )
        self.assertEqual(
            self.member.get_group_permissions(self.category),
            {self.read_code, self.topic_code},
        )
        self.assertEqual(
            self.member.get_all_permissions(self.protected),
            {self.group_code},
        )
        self.assertEqual(
            self.member.get_group_permissions(self.protected),
            {self.group_code},
        )
        self.assertNotIn(
            self.group_code, self.member.get_all_permissions(self.category),
        )
        self.assertNotIn(
            self.read_code, self.member.get_all_permissions(self.protected),
        )

    def test_direct_row_denies_the_other_models_object(self):
        self.assertTrue(self.direct.has_perm(self.read_code, self.category))
        self.assertTrue(self.direct.has_perm(self.group_code, self.protected))
        self.assertFalse(self.direct.has_perm(self.group_code, self.category))
        self.assertFalse(self.direct.has_perm(self.read_code, self.protected))
        self.assertIs(
            self.direct.has_perm(self.change_group, self.category), False,
        )
        self.assertEqual(
            self.direct.get_all_permissions(self.category), {self.read_code},
        )
        self.assertEqual(self.direct.get_group_permissions(self.category), set())
        self.assertEqual(
            self.direct.get_all_permissions(self.protected), {self.group_code},
        )
        self.assertNotIn(self.topic_code, self.direct.get_all_permissions(self.category))

    def test_listings_and_create_under_trust_follow_the_denial(self):
        self.assertIn(
            self.category.pk,
            Category.objects.permitted('read', self.member).values_list(
                'pk', flat=True,
            ),
        )
        self.assertIn(
            self.category.pk,
            Category.objects.authorized(self.member, self.topic).values_list(
                'pk', flat=True,
            ),
        )
        self.assertEqual(
            list(Category.objects.authorized(self.member, self.change_group)),
            [],
        )
        self.assertEqual(
            list(Category.objects.permitted(self.group_code, self.member)),
            [],
        )
        permitted_sql = str(
            Category.objects.permitted(self.read_code, self.member).query,
        ).lower()
        self.assertIn('django_content_type', permitted_sql)
        denied_sql = str(
            Category.objects.authorized(self.direct, self.change_group).query,
        ).lower()
        self.assertIn('django_content_type', denied_sql)

        self.assertTrue(
            Trust.objects.filter_by_user_content_perm(
                self.member, Category, 'read', exclude_root=True,
            ).filter(pk=self.org.pk).exists()
        )
        self.assertFalse(
            Trust.objects.filter_by_user_content_perm(
                self.member, Category, self.change_group, exclude_root=True,
            ).filter(pk=self.org.pk).exists()
        )
        self.assertFalse(
            Trust.objects.filter_by_user_content_perm(
                self.direct, Group, self.read, exclude_root=True,
            ).filter(pk=self.org.pk).exists()
        )
        self.assertTrue(
            Trust.objects.filter_by_user_content_perm(
                self.direct, Group, self.change_group, exclude_root=True,
            ).filter(pk=self.org.pk).exists()
        )

    def test_unregistered_model_is_zero_sql(self):
        unrelated = Organization.objects.create(name='z267-org', manager=self.member)
        registry = live_backend().registry
        self.assertFalse(registry.plan_for(Organization).records)
        with self.assertNumQueries(0):
            self.assertFalse(self.member.has_perm(self.read_code, unrelated))
        with self.assertNumQueries(0):
            self.assertEqual(self.member.get_all_permissions(unrelated), set())

    def test_active_superuser_has_perm_stays_outside_the_predicate(self):
        self.assertTrue(self.superuser.has_perm(self.group_code, self.category))
        self.assertNotIn(
            self.group_code, self.superuser.get_all_permissions(self.category),
        )
        self.assertEqual(
            list(Category.objects.authorized(self.superuser, self.change_group)),
            [],
        )
        self.assertFalse(
            Trust.objects.filter_by_user_content_perm(
                self.superuser, Category, self.change_group, exclude_root=True,
            ).filter(pk=self.org.pk).exists()
        )
