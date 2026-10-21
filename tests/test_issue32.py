"""Zero #32: migrate donation to the final configured-backend methods.

Paired against the exact django-trusts candidate
``f898123987569817bc93e31e34505211e1c61b82``.
"""

from pathlib import Path

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import models
from django.test import SimpleTestCase, TestCase
from django.test.utils import isolate_apps

from trusts.zero.apps import zero_config
from trusts.zero.models import (
    Junction, Trust, TrustGroup, TrustGroupPermission, TrustUserPermission,
)
from trusts.zero.options import ZERO_META_OPTION_NAMES
from trusts.zero.registration import (
    register_zero_relations,
    trust_settlor_owns,
)
from tests.apps import (
    catalog_from,
    catalog_from_recorder,
    isolated_compiler,
    isolated_recorder,
    live_catalog,
    live_recorder,
    root_records,
)
from tests.models import Ticket


ROOT = Path(__file__).resolve().parents[1]
CORE_PIN = 'f898123987569817bc93e31e34505211e1c61b82'
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
        self.assertIn('register_zero_content(backend, Receipt)', rst)
        self.assertIn('backend.add_named_filter', rst)
        self.assertIn('backend.add_named_filter', migrates)
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

    def test_live_recorder_exposes_final_methods_not_as_required_api(self):
        recorder = live_recorder()
        self.assertTrue(callable(recorder.register))
        self.assertFalse(hasattr(recorder, 'register_relationship'))
        self.assertTrue(callable(recorder.add_named_filter))
        catalog = live_catalog()
        self.assertEqual(len(root_records(catalog, TrustUserPermission, Trust)), 1)
        self.assertEqual(len(root_records(catalog, TrustGroupPermission, Trust)), 1)
        self.assertEqual(len(root_records(catalog, TrustGroup, Trust)), 1)
        self.assertIsNotNone(catalog.get_permission_condition_record(Trust, 'own'))
        self.assertIsNotNone(catalog.get_permission_condition_record(Ticket, 'own'))


class ZMethodsPlanTests(SimpleTestCase):
    def test_tup_and_tgp_plans_or_complete_records(self):
        catalog = live_catalog()
        tup = root_records(catalog, TrustUserPermission, Trust)
        tgp = root_records(catalog, TrustGroupPermission, Trust)
        grouped = root_records(catalog, TrustGroup, Trust)
        self.assertEqual(len(tup), 1)
        self.assertEqual(len(tgp), 1)
        self.assertEqual(len(grouped), 1)
        self.assertIs(tup[0].content_model, Trust)
        self.assertEqual(tup[0].user_field, 'entity')
        self.assertFalse(tgp[0].via_group)
        self.assertEqual(tgp[0].permission_path, ('permission',))
        self.assertTrue(grouped[0].via_group)
        self.assertEqual(grouped[0].group_path, ('group',))
        self.assertEqual(grouped[0].permission_path, ('group', 'permissions'))
        self.assertNotEqual(tgp[0].condition, grouped[0].condition)
        self.assertFalse(callable(tup[0].condition))
        self.assertFalse(callable(tgp[0].condition))
        self.assertFalse(callable(grouped[0].condition))
        self.assertEqual(
            {row.content_model for row in tup + tgp + grouped},
            {Trust},
        )

    def test_register_zero_group_keeps_auth_group_and_role(self):
        catalog = live_catalog()
        role = root_records(catalog, TrustGroupPermission, Trust)
        grouped = root_records(catalog, TrustGroup, Trust)
        self.assertEqual(len(role), 1)
        self.assertEqual(len(grouped), 1)
        self.assertNotEqual(role[0].condition, grouped[0].condition)


class ZMethodsDonationOnceTests(TestCase):
    def test_trust_own_and_ticket_own_are_donated_once(self):
        catalog = live_catalog()
        own = [
            (model, code)
            for model, code, record in catalog.iter_permission_conditions()
            if model is Trust and code == 'own'
        ]
        ticket = [
            (model, code)
            for model, code, record in catalog.iter_permission_conditions()
            if model is Ticket and code == 'own'
        ]
        self.assertEqual(len(own), 1)
        self.assertEqual(len(ticket), 1)
        self.assertEqual(
            len([
                row for row in catalog.iter_permission_conditions()
                if row[0] is Trust and row[1] == 'own'
            ]),
            1,
        )

    def test_repeated_helper_donation_is_idempotent_and_zero_sql(self):
        recorder = isolated_recorder()
        with self.assertNumQueries(0):
            register_zero_relations(recorder)
            register_zero_relations(recorder)
            recorder.add_named_filter(Trust, 'own', trust_settlor_owns)
            catalog = catalog_from_recorder(recorder)
        self.assertEqual(
            len(root_records(catalog, TrustUserPermission, Trust)), 1,
        )
        self.assertEqual(len(root_records(live_catalog(), TrustUserPermission, Trust)), 1)
        own = catalog.get_permission_condition_record(Trust, 'own')
        self.assertIsNotNone(own)
        self.assertIsNotNone(own.expr)
        self.assertFalse(hasattr(own, 'func'))

    def test_repeated_ready_is_idempotent_without_reading_recorder_flags(self):
        owner = zero_config()
        before = live_catalog()
        records_before = list(before.records)
        own_before = before.get_permission_condition_record(Trust, 'own')
        with self.assertNumQueries(0):
            owner.ready()
        after = live_catalog()
        self.assertIs(after, before)
        self.assertEqual(list(after.records), records_before)
        self.assertIs(
            after.get_permission_condition_record(Trust, 'own'),
            own_before,
        )

    def test_catalog_build_invokes_builder_once(self):
        calls = []

        def boom(u, p, o):
            calls.append((u, p, o))
            return u == o.settlor

        factory = isolated_compiler()
        self.assertEqual(len(calls), 0)
        factory.add_named_filter(Trust, 'late32', boom)
        catalog = catalog_from(factory)
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(
            catalog.get_permission_condition_record(Trust, 'late32')
        )
        catalog.compile_registered_condition_q(
            Trust, 'trusts.change_trust:late32', None,
        )
        self.assertEqual(len(calls), 1)

    @isolate_apps('tests', 'django.contrib.auth', 'django.contrib.contenttypes')
    def test_missing_junction_filter_is_not_on_live_backend(self):
        def via_memo(u, p, o):
            return u == o.content.owner

        class Memo(models.Model):
            owner = models.ForeignKey(User, on_delete=models.CASCADE)

            class Meta:
                app_label = 'trusts_zero_tests'

        class MemoJunction(Junction):
            content = models.ForeignKey(Memo, unique=True, on_delete=models.CASCADE)

            class Meta:
                app_label = 'trusts_zero_tests'

        factory = isolated_compiler()
        factory.add_named_filter(MemoJunction, 'via_memo', via_memo)
        catalog = catalog_from(factory)
        self.assertIsNotNone(
            catalog.get_permission_condition_record(MemoJunction, 'via_memo')
        )
        self.assertIsNone(
            live_catalog().get_permission_condition_record(
                MemoJunction, 'via_memo',
            )
        )


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
        catalog = live_catalog()
        self.assertEqual(len(root_records(catalog, TrustUserPermission, Trust)), 1)
        self.assertIsNotNone(catalog.get_permission_condition_record(Trust, 'own'))
        self.assertIsNotNone(catalog.get_permission_condition_record(Ticket, 'own'))

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
    def test_donation_requires_a_recorder(self):
        factory = isolated_compiler()
        factory.add_named_filter(
            Ticket, 'own', lambda u, p, o: u == o.owner,
        )
        catalog = catalog_from(factory)
        self.assertIsNotNone(
            catalog.get_permission_condition_record(Ticket, 'own')
        )
        with self.assertRaises(TypeError):
            register_zero_relations(catalog)
