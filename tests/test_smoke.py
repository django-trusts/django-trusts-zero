"""Smoke: reconstituted models still authorize through C1 public seams."""

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase

from trusts.zero.models import Trust, TrustUserPermission


class ZeroSmokeTests(TestCase):
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
        self.isolated_child = Trust(settlor=self.other, title='OtherChild', trust=self.isolated)
        self.isolated_child.save()
        ct = ContentType.objects.get_for_model(Trust)
        self.change = Permission.objects.get(content_type=ct, codename='change_trust')
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=self.change,
        ).save()

    def test_direct_grant_on_trust_content_and_isolation(self):
        user = User.objects.get(pk=self.user.pk)
        other = User.objects.get(pk=self.other.pk)
        child = Trust.objects.get(pk=self.child.pk)
        isolated_child = Trust.objects.get(pk=self.isolated_child.pk)

        self.assertTrue(user.has_perm('trusts.change_trust', child))
        self.assertFalse(user.has_perm('trusts.change_trust', isolated_child))
        self.assertFalse(other.has_perm('trusts.change_trust', child))
        permitted = list(Trust.objects.permitted('change', user))
        self.assertIn(child, permitted)
        self.assertNotIn(isolated_child, permitted)

    def test_root_row_and_content_type_natural_key(self):
        root = Trust.objects.get(pk=1)
        self.assertEqual(root.trust_id, root.pk)
        ct = ContentType.objects.get_by_natural_key('trusts', 'trust')
        self.assertEqual(ct.model, 'trust')
        self.assertEqual(ct.app_label, 'trusts')
