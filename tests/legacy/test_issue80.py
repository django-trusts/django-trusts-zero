"""Trust-row ``filter_by_user_content_perm`` and the NewTeamForm dropdown.

Creating content under a Trust is not answered by
``filter_by_user_content_perm``; it returns Trust rows the user holds a
grant on. The form lists the Trusts a user may create a team on.
"""

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db.models.query import QuerySet
from django.test import TestCase

from trusts.zero.models import Trust, TrustUserPermission
from trusts.zero.views import NewTeamForm
from tests.legacy.helpers import get_or_create_root_user


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
