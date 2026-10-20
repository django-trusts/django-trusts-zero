"""Zero #32: migrate donation to the final configured-backend methods.

Paired against the exact django-trusts candidate
``b240eed7fd12f34891c6dd0957d944c9f2591473``.
"""

import inspect
from pathlib import Path

from django.contrib.auth.models import User
from django.db import models
from django.test import SimpleTestCase, TestCase
from django.test.utils import isolate_apps

from trusts.zero import registration as zero_registration
from trusts.zero.apps import ZeroConfig, zero_config
from trusts.zero.models import (
    Junction, Trust, TrustGroup, TrustGroupPermission, TrustUserPermission,
)
from trusts.zero.registration import (
    donate_content_permission_conditions,
    donate_installed_permission_conditions,
    donate_junction_content_permission_conditions,
    register_zero_group,
    register_zero_relations,
)
from tests.apps import (
    build_catalog,
    isolated_recorder,
    live_catalog,
    live_recorder,
    records_for_root,
)
from tests.models import Ticket


ROOT = Path(__file__).resolve().parents[1]
CORE_PIN = 'b240eed7fd12f34891c6dd0957d944c9f2591473'
STALE_269 = '71699ba35f960780fd9eb1a7fe027623584e8034'
STALE_253 = 'e085898277682a4ee3de5d49985053cba9979cbe'
STALE_R5B = '91e1fb690e14a88626ff3c1c05b137da96c6b254'
STALE_PIN = '8bfe6151b5a65af2d0667ab3a71680eecc90a691'

APPLICATION_PATHS = (
    ROOT / 'trusts' / 'zero' / 'registration.py',
    ROOT / 'trusts' / 'zero' / 'apps.py',
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
        registration = (ROOT / 'trusts' / 'zero' / 'registration.py').read_text()
        apps = (ROOT / 'trusts' / 'zero' / 'apps.py').read_text()
        rst = (ROOT / 'docs' / 'source' / 'index.rst').read_text()
        migrates = (ROOT / 'migrates.md').read_text()

        self.assertIn('recorder.register(', registration)
        self.assertIn('trust=TrustUserPermission', registration)
        self.assertIn(
            'recorder.add_named_filter(model, cond_code, condition)',
            registration,
        )
        self.assertNotIn('predicate=', registration)
        self.assertIn('add_named_filter', apps)
        self.assertIn('register_zero_relations(recorder)', apps)
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

        for path in APPLICATION_PATHS:
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
        self.assertNotIn('def _require_handle', registration)
        self.assertNotIn('handle.registry', registration)
        self.assertNotIn('_zero_z1_relation_ids', registration)
        self.assertNotIn('_zero_condition_donation_id', registration)
        self.assertNotIn('_condition_store', registration)
        self.assertNotIn('.registry', registration)

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
        source = inspect.getsource(ZeroConfig._donate_zero_relations)
        self.assertIn('add_named_filter', inspect.getsource(zero_registration))
        self.assertNotIn('register_permission_condition', source)
        self.assertNotIn('handle =', source)
        self.assertIn('register_zero_relations(recorder)', source)


class ZMethodsPlanTests(SimpleTestCase):
    def test_tup_and_tgp_plans_or_complete_records(self):
        recorder = isolated_recorder()
        register_zero_relations(recorder)
        catalog = build_catalog(recorder=recorder)
        tup = records_for_root(catalog, TrustUserPermission)
        tgp = records_for_root(catalog, TrustGroupPermission)
        grouped = records_for_root(catalog, TrustGroup)
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
        recorder = isolated_recorder()
        register_zero_group(recorder, (Trust,))
        catalog = build_catalog(recorder=recorder)
        role = records_for_root(catalog, TrustGroupPermission)
        grouped = records_for_root(catalog, TrustGroup)
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
        donate_installed_permission_conditions(live_recorder())
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
            first = list(recorder.rows)
            register_zero_relations(recorder)
            self.assertEqual(list(recorder.rows), first)
            donate_content_permission_conditions(recorder, Trust)
            donate_content_permission_conditions(recorder, Trust)
            catalog = build_catalog(recorder=recorder)
        self.assertEqual(len(records_for_root(catalog, TrustUserPermission)), 1)
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
        source = inspect.getsource(zero_registration)
        self.assertNotIn('_zero_z1_relation_ids', source)
        self.assertNotIn('_zero_condition_donation_id', source)

    def test_catalog_build_invokes_builder_once(self):
        calls = []

        def boom(u, p, o):
            calls.append((u, p, o))
            return u == o.settlor

        def contribute(recorder):
            recorder.add_named_filter(Trust, 'late32', boom)
            self.assertEqual(len(calls), 0)

        catalog = build_catalog(contribute)
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
                content_permission_conditions = (
                    ('via_memo', via_memo),
                )

        def contribute(recorder):
            donate_junction_content_permission_conditions(recorder, MemoJunction)

        catalog = build_catalog(contribute)
        self.assertIsNotNone(
            catalog.get_permission_condition_record(MemoJunction, 'via_memo')
        )
        self.assertIsNone(
            live_catalog().get_permission_condition_record(
                MemoJunction, 'via_memo',
            )
        )


class ZMethodsRecorderContractTests(SimpleTestCase):
    def test_donation_requires_a_recorder(self):
        def contribute(recorder):
            recorder.add_named_filter(
                Ticket, 'own', lambda u, p, o: u == o.owner,
            )

        catalog = build_catalog(contribute)
        self.assertIsNotNone(
            catalog.get_permission_condition_record(Ticket, 'own')
        )
        with self.assertRaises(TypeError):
            donate_content_permission_conditions(catalog, Ticket)
