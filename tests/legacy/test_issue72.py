"""Ticket relation plan and ``permitted`` (issue #72).

Sentinel and swapped-registry cases were removed with Core's catalog.
Ticket's Meta ``:meta_own`` is already on the live catalog.
"""

from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db.models.query import QuerySet
from django.test import SimpleTestCase, TestCase

from tests.apps import live_catalog
from tests.legacy.helpers import enable_local_group_grant, get_or_create_root_user
from tests.models import Organization, Ticket
from trusts.zero.models import Trust, TrustGroup, TrustGroupPermission, TrustUserPermission
def _pks(qs):
    return set(qs.values_list('pk', flat=True))


def _perm(model, codename):
    return Permission.objects.get(
        content_type=ContentType.objects.get_for_model(model),
        codename=codename,
    )


def _tup(catalog, model):
    matches = [
        record for record in catalog.plan_for(model).records
        if record.root is TrustUserPermission
    ]
    return matches[0]


class TicketRegistrationShapeTest(SimpleTestCase):
    def test_live_declaration_uses_meta_reverse(self):
        catalog = live_catalog()
        rev = Ticket._meta.get_field('trust').remote_field.get_accessor_name()
        self.assertNotEqual(rev, 'tests_ticket_content')
        record = _tup(catalog, Ticket)
        self.assertIs(record.root, TrustUserPermission)
        self.assertIs(record.content_model, Ticket._meta.concrete_model)
        self.assertEqual(record.user_field, 'entity')
        self.assertEqual(record.permission_field, 'permission')
        self.assertEqual(record.content_field, 'trust__%s' % rev)
        self.assertNotEqual(record.content_field, 'trust')
        roots = {row.root for row in catalog.records}
        self.assertEqual(
            roots, {TrustUserPermission, TrustGroup, TrustGroupPermission},
        )


class TicketPermittedTest(TestCase):
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

        self.org = Organization.objects.create(name='Org', manager=self.alice)
        self.ticket_a1 = Ticket.objects.create(
            trust=self.trust_a, title='keep', owner=self.alice,
            organization=self.org, status='open',
        )
        self.ticket_a2 = Ticket.objects.create(
            trust=self.trust_a, title='drop', owner=self.carol,
            organization=self.org, status='open',
        )
        self.ticket_b = Ticket.objects.create(
            trust=self.trust_b, title='other', owner=self.bob,
            organization=self.org, status='open',
        )

        self.change = _perm(Ticket, 'change_ticket')
        self.add = _perm(Ticket, 'add_ticket')
        self.change_code = 'trusts_zero_tests.change_ticket'
        self.add_code = 'trusts_zero_tests.add_ticket'
        self.change_own = 'trusts_zero_tests.change_ticket:meta_own'

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
        return {obj.pk for obj in Ticket.objects.all() if user.has_perm(perm, obj)}

    def test_alice_tup_grants_sibling_tickets_on_trust_a_not_b(self):
        qs = Ticket.objects.permitted(self.change_code, self.alice)
        self.assertEqual(_pks(qs), {self.ticket_a1.pk, self.ticket_a2.pk})
        self.assertTrue(self.alice.has_perm(self.change_code, self.ticket_a1))
        self.assertTrue(self.alice.has_perm(self.change_code, self.ticket_a2))
        self.assertFalse(self.alice.has_perm(self.change_code, self.ticket_b))

    def test_bob_without_tup_is_denied(self):
        self.assertFalse(self.bob.has_perm(self.change_code, self.ticket_a1))
        self.assertFalse(Ticket.objects.permitted(self.change_code, self.bob).exists())

    def test_wrong_permission_is_denied(self):
        self.assertFalse(self.alice.has_perm(self.add_code, self.ticket_a1))
        self.assertFalse(Ticket.objects.permitted(self.add_code, self.alice).exists())

    def test_carol_group_only_grant_is_not_erased_by_trustee_branch(self):
        self.assertFalse(
            TrustUserPermission.objects.filter(entity=self.carol).exists()
        )
        self.assertTrue(self.carol.has_perm(self.change_code, self.ticket_a1))
        self.assertTrue(self.carol.has_perm(self.change_code, self.ticket_a2))
        self.assertFalse(self.carol.has_perm(self.change_code, self.ticket_b))
        self.assertEqual(
            _pks(Ticket.objects.permitted(self.change_code, self.carol)),
            {self.ticket_a1.pk, self.ticket_a2.pk},
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
                _pks(Ticket.objects.permitted(perm, user)),
                self._direct_pks(perm, user),
                (user.username, perm),
            )

    def test_permitted_is_lazy_paginated_and_one_query(self):
        qs = Ticket.objects.permitted(self.change_code, self.alice)
        self.assertIsInstance(qs, QuerySet)
        self.assertIsNone(qs._result_cache)
        with self.assertNumQueries(1):
            self.assertEqual(_pks(qs), {self.ticket_a1.pk, self.ticket_a2.pk})
        page = Ticket.objects.permitted(
            self.change_code, self.alice,
        ).order_by('pk')[:1]
        self.assertIsNone(page._result_cache)
        with self.assertNumQueries(1):
            self.assertEqual(list(page), [self.ticket_a1])

    def test_no_tup_rows_deny_without_changing_registration(self):
        catalog = live_catalog()
        self.assertTrue(catalog.plan_for(Ticket).records)
        TrustUserPermission.objects.all().delete()
        self._reload()
        self.assertTrue(catalog.plan_for(Ticket).records)
        self.assertFalse(self.alice.has_perm(self.change_code, self.ticket_a1))
        self.assertFalse(
            Ticket.objects.permitted(self.change_code, self.alice).exists()
        )
        self.assertEqual(
            _pks(Ticket.objects.permitted(self.change_code, self.carol)),
            {self.ticket_a1.pk, self.ticket_a2.pk},
        )

    def test_meta_own_is_condition_overlay_and_does_not_create_a_grant(self):
        record = live_catalog().get_permission_condition_record(Ticket, 'meta_own')
        self.assertIsNotNone(record)
        self.assertIs(record.model, Ticket)
        self.assertTrue(self.alice.has_perm(self.change_own, self.ticket_a1))
        self.assertFalse(self.alice.has_perm(self.change_own, self.ticket_a2))
        self.assertFalse(self.carol.has_perm(self.change_own, self.ticket_a1))
        self.assertTrue(self.carol.has_perm(self.change_own, self.ticket_a2))
        self.assertEqual(
            _pks(Ticket.objects.permitted(self.change_own, self.alice)),
            {self.ticket_a1.pk},
        )
        self.assertEqual(
            _pks(Ticket.objects.permitted(self.change_own, self.carol)),
            {self.ticket_a2.pk},
        )
        self.assertFalse(
            Ticket.objects.permitted(self.change_own, self.bob).exists()
        )

        ticket_dave = Ticket.objects.create(
            trust=self.trust_a, title='dave', owner=self.dave,
            organization=self.org, status='open',
        )
        self.assertFalse(self.dave.has_perm(self.change_code, ticket_dave))
        self.assertFalse(self.dave.has_perm(self.change_own, ticket_dave))
        self.assertFalse(
            Ticket.objects.permitted(self.change_own, self.dave).exists()
        )

        TrustUserPermission.objects.filter(entity=self.alice).delete()
        self._reload()
        self.assertFalse(self.alice.has_perm(self.change_own, self.ticket_a1))
        self.assertFalse(
            Ticket.objects.permitted(self.change_own, self.alice).exists()
        )
        self.assertEqual(
            _pks(Ticket.objects.permitted(self.change_own, self.carol)),
            {self.ticket_a2.pk},
        )

    def test_sibling_and_mixed_trust_isolation(self):
        TrustUserPermission(
            trust=self.trust_b, entity=self.alice, permission=self.add,
        ).save()
        self._reload()
        self.assertEqual(
            _pks(Ticket.objects.permitted(self.change_code, self.alice)),
            {self.ticket_a1.pk, self.ticket_a2.pk},
        )
        self.assertEqual(
            _pks(Ticket.objects.permitted(self.add_code, self.alice)),
            {self.ticket_b.pk},
        )
        self.assertNotIn(
            self.ticket_b.pk,
            _pks(Ticket.objects.permitted(self.change_code, self.alice)),
        )
        self.assertNotIn(
            self.ticket_a1.pk,
            _pks(Ticket.objects.permitted(self.add_code, self.alice)),
        )

    def test_create_under_trust_filters_parent_rows(self):
        pks = _pks(Trust.objects.filter_by_user_content_perm(
            self.alice, Ticket, 'change_ticket',
        ))
        self.assertIn(self.trust_a.pk, pks)
        self.assertNotIn(self.trust_b.pk, pks)

    def test_inactive_and_anonymous_remain_empty(self):
        self.alice.is_active = False
        self.alice.save()
        self._reload()
        self.assertFalse(
            Ticket.objects.permitted(self.change_code, self.alice).exists()
        )
        self.assertFalse(self.alice.has_perm(self.change_code, self.ticket_a1))
        self.assertFalse(
            Ticket.objects.permitted(self.change_code, AnonymousUser()).exists()
        )
