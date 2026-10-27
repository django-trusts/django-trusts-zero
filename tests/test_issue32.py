"""Zero #32: migrate donation to the final configured-backend methods.

Paired against the exact django-trusts candidate
``07dfb76a88cc6e80fa0c554218e543bd33fd4d1e``.
"""

from pathlib import Path

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from trusts.zero.apps import zero_config
from trusts.zero.models import (
    Trust, TrustGroup, TrustGroupPermission, TrustUserPermission,
)
from trusts.zero.options import ZERO_META_OPTION_NAMES
from trusts.zero.registration import register_zero_relations

from tests.apps import ZERO_BACKEND, named_filter_ids, trust_rows
from tests.models import Ticket
from trusts.errors import TrustsConfigurationError


ROOT = Path(__file__).resolve().parents[1]
CORE_PIN = '07dfb76a88cc6e80fa0c554218e543bd33fd4d1e'
STALE_269 = '71699ba35f960780fd9eb1a7fe027623584e8034'
STALE_253 = 'e085898277682a4ee3de5d49985053cba9979cbe'
STALE_R5B = '91e1fb690e14a88626ff3c1c05b137da96c6b254'
STALE_PIN = '8bfe6151b5a65af2d0667ab3a71680eecc90a691'

DOC_PATHS = (
    ROOT / 'docs' / 'source' / 'index.rst',
    ROOT / 'README.md',
)

TEMPORARY_METHOD_NEEDLES = (
    'handle.register(',
    'register_relationship(',
    'permission_in(',
    'register_permission_condition(',
    '.registry.register(',
)


class ZMethodsSurfaceTests(SimpleTestCase):
    def test_application_paths_use_final_backend_methods(self):
        rst = (ROOT / 'docs' / 'source' / 'index.rst').read_text()
        migrates = (ROOT / 'migrates.md').read_text()

        self.assertNotIn('content_permission_conditions', ZERO_META_OPTION_NAMES)
        self.assertIn('register_zero_content(registry, Receipt)', rst)
        self.assertIn('registry.add_named_filter', rst)
        self.assertIn('registry.add_named_filter', migrates)
        self.assertIn('backend.register(\n    trust=TrustUserPermission', migrates)
        self.assertIn('backend.register_relationship(', migrates)
        self.assertIn('permission_in("trustgroup__group__permissions")', migrates)
        self.assertIn(
            't.trustgroup.group.permissions.contains(t.permission)',
            migrates,
        )
        self.assertIn('group="group"', migrates)
        self.assertIn(
            't.permissions.contains(t.group.permissions)',
            migrates,
        )
        self.assertIn('predicate=', migrates)
        self.assertIn("Python 'in' is unsupported", migrates)

        for path in DOC_PATHS:
            text = path.read_text()
            for needle in TEMPORARY_METHOD_NEEDLES:
                self.assertNotIn(
                    needle, text,
                    '%s still teaches %s' % (path.relative_to(ROOT), needle),
                )
            self.assertNotIn(STALE_269, text)
            self.assertNotIn(STALE_253, text)
            self.assertNotIn(STALE_R5B, text)
            self.assertNotIn(STALE_PIN, text)

    def test_ci_pins_exact_django_trusts_candidate(self):
        ci = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text()
        self.assertIn('COMPANION_KERNEL_SHA: %s' % CORE_PIN, ci)
        self.assertNotIn(STALE_269, ci)
        self.assertNotIn(STALE_253, ci)
        self.assertNotIn(STALE_R5B, ci)
        self.assertNotIn(STALE_PIN, ci)
        self.assertNotIn('#211', ci)
        self.assertNotIn('C-methods', ci)

    def test_live_policy_exposes_trust_rows_and_named_filters(self):
        self.assertEqual(len(trust_rows(Trust, TrustUserPermission, ZERO_BACKEND)), 1)
        self.assertEqual(len(trust_rows(Trust, TrustGroupPermission, ZERO_BACKEND)), 1)
        self.assertEqual(len(trust_rows(Trust, TrustGroup, ZERO_BACKEND)), 1)
        self.assertIn('trusts__Trust__own', named_filter_ids(Trust, ZERO_BACKEND))
        self.assertIn('trusts_zero_tests__Ticket__own', named_filter_ids(Ticket))


class ZMethodsPlanTests(SimpleTestCase):
    def test_tup_and_tgp_plans_or_complete_records(self):
        tup = trust_rows(Trust, TrustUserPermission, ZERO_BACKEND)
        tgp = trust_rows(Trust, TrustGroupPermission, ZERO_BACKEND)
        grouped = trust_rows(Trust, TrustGroup, ZERO_BACKEND)
        self.assertEqual(len(tup), 1)
        self.assertEqual(len(tgp), 1)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(tup[0]['content']['model'], 'trusts.Trust')
        self.assertEqual(tup[0]['user']['path'], 'entity')
        self.assertNotIn('group', tgp[0])
        self.assertEqual(tgp[0]['permission']['path'], 'permission')
        self.assertEqual(grouped[0]['group']['path'], 'group')
        self.assertEqual(grouped[0]['permission']['path'], 'group__permissions')
        self.assertNotEqual(tgp[0].get('condition'), grouped[0].get('condition'))
        self.assertNotIsInstance(tup[0].get('condition'), type(lambda: None))
        self.assertEqual(tup[0]['content']['model'], 'trusts.Trust')
        self.assertEqual(tgp[0]['content']['model'], 'trusts.Trust')
        self.assertEqual(grouped[0]['content']['model'], 'trusts.Trust')

    def test_register_zero_group_keeps_auth_group_and_role(self):
        role = trust_rows(Trust, TrustGroupPermission, ZERO_BACKEND)
        grouped = trust_rows(Trust, TrustGroup, ZERO_BACKEND)
        self.assertEqual(len(role), 1)
        self.assertEqual(len(grouped), 1)
        self.assertNotEqual(role[0].get('condition'), grouped[0].get('condition'))


class ZMethodsDonationOnceTests(TestCase):
    def test_trust_own_and_ticket_own_are_donated_once(self):
        self.assertEqual(
            named_filter_ids(Trust, ZERO_BACKEND).count('trusts__Trust__own'), 1,
        )
        self.assertEqual(
            named_filter_ids(Ticket).count('trusts_zero_tests__Ticket__own'), 1,
        )

    def test_repeated_ready_keeps_the_policy_and_late_registration_raises(self):
        from trusts.zero.backends import TrustModelBackend

        before = trust_rows(Trust, TrustUserPermission, ZERO_BACKEND)
        with self.assertNumQueries(0):
            zero_config().ready()
        self.assertEqual(trust_rows(Trust, TrustUserPermission, ZERO_BACKEND), before)
        with self.assertNumQueries(0):
            with self.assertRaises(TrustsConfigurationError):
                TrustModelBackend().get_registry().add_named_filter(
                    Trust, 'late', lambda u, p, o: u == o.settlor,
                )
        self.assertEqual(trust_rows(Trust, TrustUserPermission, ZERO_BACKEND), before)
        self.assertIn('trusts__Trust__own', named_filter_ids(Trust, ZERO_BACKEND))


class ZMethodsAuthorizationTests(TestCase):
    def setUp(self):
        call_command('create_trust_root')
        self.settlor = User.objects.create_user('settlor32', 's32@example.com', 'x')
        self.other = User.objects.create_user('other32', 'o32@example.com', 'x')
        self.root = Trust.objects.get(pk=1)
        self.org = Trust(settlor=self.settlor, title='Org32', trust=self.root)
        self.org.save()
        self.child = Trust(settlor=self.settlor, title='Child32', trust=self.org)
        self.child.save()
        self.foreign = Trust(settlor=self.other, title='Foreign32', trust=self.root)
        self.foreign.save()
        change = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Trust),
            codename='change_trust',
        )
        TrustUserPermission(
            trust=self.org, entity=self.settlor, permission=change,
        ).save()
        TrustUserPermission(
            trust=self.org, entity=self.other, permission=change,
        ).save()
        self.ticket = Ticket(title='mine32', owner=self.settlor, trust=self.org)
        self.ticket.save()
        self.other_ticket = Ticket(
            title='theirs32', owner=self.other, trust=self.org,
        )
        self.other_ticket.save()
        read = Ticket.objects.get_permission('read')
        TrustUserPermission(
            trust=self.org, entity=self.settlor, permission=read,
        ).save()

    def test_has_perm_and_permitted_follow_the_catalog(self):
        settlor = User.objects.get(pk=self.settlor.pk)
        other = User.objects.get(pk=self.other.pk)
        self.assertEqual(len(trust_rows(Trust, TrustUserPermission, ZERO_BACKEND)), 1)
        self.assertIn('trusts__Trust__own', named_filter_ids(Trust, ZERO_BACKEND))
        self.assertIn('trusts_zero_tests__Ticket__own', named_filter_ids(Ticket))

        self.assertTrue(settlor.has_perm('trusts.change_trust', self.child))
        self.assertTrue(settlor.has_perm('trusts.change_trust:own', self.child))
        self.assertTrue(other.has_perm('trusts.change_trust', self.child))
        self.assertFalse(other.has_perm('trusts.change_trust:own', self.child))
        owned = set(Trust.objects.permitted('change:own', settlor))
        self.assertIn(self.child, owned)
        self.assertNotIn(self.foreign, owned)
        self.assertNotIn(self.child, set(Trust.objects.permitted('change:own', other)))

        self.assertTrue(
            settlor.has_perm('trusts_zero_tests.read_ticket:own', self.ticket),
        )
        self.assertFalse(
            settlor.has_perm('trusts_zero_tests.read_ticket:own', self.other_ticket),
        )
        self.assertEqual(
            set(Ticket.objects.permitted('read:own', settlor)),
            {self.ticket},
        )


class ZMethodsRecorderContractTests(SimpleTestCase):
    def test_donation_requires_a_registry(self):
        with self.assertRaises(AttributeError):
            register_zero_relations(object())
