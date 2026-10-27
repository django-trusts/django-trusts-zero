"""Named filters donated in ready() are visible and authorize."""

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.checks import run_checks
from django.core.management import call_command
from django.test import TestCase, override_settings

from tests.apps import (
    TEST_BACKEND,
    ZERO_BACKEND,
    category_spy,
    named_filter_ids,
)
from tests.models import Category, Ticket
from trusts.zero.models import Content, Junction, Trust, TrustUserPermission
from trusts.zero.registration import trust_settlor_owns


REMOVED_STATIC = (
    'register_permission_condition',
    'register_content',
    'get_permission_condition_record',
    'get_permission_condition_func',
    'iter_permission_conditions',
    'register_junction',
)


class ZeroConditionSurfaceTests(TestCase):
    def test_content_and_junction_have_no_registration_staticmethods(self):
        for name in REMOVED_STATIC:
            self.assertFalse(hasattr(Content, name), name)
            self.assertFalse(hasattr(Junction, name), name)

    def test_live_named_filters_are_trust_own_and_ticket_own(self):
        self.assertIn('trusts__Trust__own', named_filter_ids(Trust, ZERO_BACKEND))
        self.assertEqual(
            named_filter_ids(Ticket, TEST_BACKEND).count(
                'trusts_zero_tests__Ticket__own',
            ),
            1,
        )
        self.assertIn(
            'trusts_zero_tests__Ticket__meta_own',
            named_filter_ids(Ticket, TEST_BACKEND),
        )
        self.assertTrue(callable(trust_settlor_owns))


class ExprParityTests(TestCase):
    def setUp(self):
        call_command('create_trust_root')
        self.user = User.objects.create_user('alice-16', 'alice-16@example.com', 'x')
        self.other = User.objects.create_user('bob-16', 'bob-16@example.com', 'x')
        self.root = Trust.objects.get(pk=1)
        self.org = Trust(settlor=self.user, title='Org16', trust=self.root)
        self.org.save()
        self.child = Trust(settlor=self.user, title='Child16', trust=self.org)
        self.child.save()
        self.isolated = Trust(settlor=self.other, title='Iso16', trust=self.root)
        self.isolated.save()
        ct = ContentType.objects.get_for_model(Trust)
        self.change = Permission.objects.get(content_type=ct, codename='change_trust')
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=self.change,
        ).save()
        self.ticket = Ticket(title='mine', owner=self.user, trust=self.org)
        self.ticket.save()
        self.other_ticket = Ticket(title='theirs', owner=self.other, trust=self.org)
        self.other_ticket.save()
        read = Ticket.objects.get_permission('read')
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=read,
        ).save()

    def test_has_perm_and_permitted_parity_for_registered_expr(self):
        user = User.objects.get(pk=self.user.pk)
        permitted_trusts = set(Trust.objects.permitted('change:own', user))
        evaluated_trusts = {
            row for row in Trust.objects.all()
            if user.has_perm('trusts.change_trust:own', row)
        }
        self.assertEqual(permitted_trusts, evaluated_trusts)
        self.assertIn(self.child, permitted_trusts)
        self.assertNotIn(self.isolated, permitted_trusts)

        permitted_tickets = set(Ticket.objects.permitted('read:own', user))
        evaluated_tickets = {
            row for row in Ticket.objects.all()
            if user.has_perm('trusts_zero_tests.read_ticket:own', row)
        }
        self.assertEqual(permitted_tickets, evaluated_tickets)
        self.assertEqual(permitted_tickets, {self.ticket})

    def test_unknown_condition_fails_closed(self):
        user = User.objects.get(pk=self.user.pk)
        self.assertEqual(
            list(Ticket.objects.permitted('read:nope16', user)),
            [],
        )
        with self.assertNumQueries(0):
            self.assertFalse(
                user.has_perm('trusts_zero_tests.read_ticket:nope16', self.ticket),
            )
        self.assertTrue(
            user.has_perm('trusts_zero_tests.read_ticket:own', self.ticket)
        )
        self.assertIn(self.ticket, set(Ticket.objects.permitted('read:own', user)))


class BuilderOnceTests(TestCase):
    def setUp(self):
        call_command('create_trust_root')
        self.user = User.objects.create_user('cb-16', 'cb-16@example.com', 'x')
        self.root = Trust.objects.get(pk=1)
        self.org = Trust(settlor=self.user, title='CB16', trust=self.root)
        self.org.save()
        self.keep = Category(name='keep', trust=self.org)
        self.keep.save()
        self.drop = Category(name='drop', trust=self.org)
        self.drop.save()
        read = Category.objects.get_permission('read')
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=read,
        ).save()

    def test_builder_once_object_and_queryset_parity(self):
        self.assertEqual(len(category_spy.calls), 1)
        user = User.objects.get(pk=self.user.pk)
        code = 'trusts_zero_tests.read_category:spy'
        self.assertTrue(user.has_perm(code, self.keep))
        self.assertFalse(user.has_perm(code, self.drop))
        permitted = set(Category.objects.permitted('read:spy', user))
        self.assertEqual(permitted, {self.keep})
        self.assertEqual(len(category_spy.calls), 1)

    @override_settings(TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS=True)
    def test_leftover_setting_is_error_and_does_not_enable_callbacks(self):
        messages = [
            message for message in run_checks()
            if message.id == 'trusts.E007'
        ]
        self.assertEqual(len(messages), 1)
        self.assertIn('does not enable', messages[0].msg)
        user = User.objects.get(pk=self.user.pk)
        before = len(category_spy.calls)
        self.assertTrue(user.has_perm(
            'trusts_zero_tests.read_category:spy', self.keep,
        ))
        self.assertEqual(len(category_spy.calls), before)
