"""Live ``:own`` grants on Ticket and Trust."""

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase

from tests.apps import ZERO_BACKEND, named_filter_ids
from tests.legacy.helpers import (
    create_test_users,
    get_or_create_root_user,
    reload_test_users,
)
from tests.models import Ticket
from trusts.zero.models import Trust, TrustUserPermission


class LiveOwnConditionTest(TestCase):
    def setUp(self):
        super().setUp()
        call_command('create_trust_root')
        get_or_create_root_user(self)
        create_test_users(self)
        self.org_trust = Trust(
            settlor=self.user, trust=Trust.objects.get_root(), title='Tickets Org',
        )
        self.org_trust.save()
        self.other_trust = Trust(
            settlor=self.user1, trust=Trust.objects.get_root(), title='Other Org',
        )
        self.other_trust.save()
        self.owned_open = Ticket.objects.create(
            trust=self.org_trust, title='owned-open', owner=self.user, status='open',
        )
        self.managed_open = Ticket.objects.create(
            trust=self.org_trust, title='managed-open', owner=self.user1, status='open',
        )
        self.perm_change = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Ticket),
            codename='change_ticket',
        )
        TrustUserPermission(
            trust=self.org_trust, entity=self.user, permission=self.perm_change,
        ).save()
        reload_test_users(self)
        self.change_own = 'trusts_zero_tests.change_ticket:own'

    def test_ticket_own_matches_has_perm_and_permitted(self):
        self.assertIn(
            'trusts_zero_tests__Ticket__own',
            named_filter_ids(Ticket),
        )
        self.assertTrue(self.user.has_perm(self.change_own, self.owned_open))
        self.assertFalse(self.user.has_perm(self.change_own, self.managed_open))
        self.assertEqual(
            set(Ticket.objects.permitted(self.change_own, self.user).values_list(
                'pk', flat=True,
            )),
            {self.owned_open.pk},
        )
        self.assertFalse(
            Ticket.objects.permitted(self.change_own, self.user1).exists()
        )

    def test_trust_own_requires_the_settlor(self):
        self.assertIn('trusts__Trust__own', named_filter_ids(Trust, ZERO_BACKEND))
        change_trust = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Trust),
            codename='change_trust',
        )
        TrustUserPermission(
            trust=self.org_trust, entity=self.user, permission=change_trust,
        ).save()
        TrustUserPermission(
            trust=self.org_trust, entity=self.user1, permission=change_trust,
        ).save()
        reload_test_users(self)
        child = Trust(
            settlor=self.user, title='Child owned', trust=self.org_trust,
        )
        child.save()
        perm = 'trusts.change_trust:own'
        self.assertTrue(self.user.has_perm('trusts.change_trust', child))
        self.assertTrue(self.user.has_perm(perm, child))
        self.assertTrue(self.user1.has_perm('trusts.change_trust', child))
        self.assertFalse(self.user1.has_perm(perm, child))
        self.assertIn(
            child.pk,
            Trust.objects.permitted(perm, self.user).values_list('pk', flat=True),
        )
        self.assertNotIn(
            child.pk,
            Trust.objects.permitted(perm, self.user1).values_list('pk', flat=True),
        )
        self.assertEqual(
            set(Trust.objects.permitted(perm, self.user).values_list('pk', flat=True)),
            set(t.pk for t in Trust.objects.all() if self.user.has_perm(perm, t)),
        )
