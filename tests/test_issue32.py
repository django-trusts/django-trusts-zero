"""Zero #32: migrate donation to the final configured-backend methods.

Paired against the exact django-trusts candidate
``91e1fb690e14a88626ff3c1c05b137da96c6b254``.
"""

import inspect
from pathlib import Path

from django.contrib.auth.models import User
from django.db import models
from django.test import SimpleTestCase, TestCase
from django.test.utils import isolate_apps

from trusts.core import TrustsConfigurationError, TrustsRegistry
from trusts.zero.apps import CANONICAL_BACKEND_PATH, ZeroConfig, zero_config
from trusts.zero.models import Junction, Trust, TrustGroupPermission, TrustUserPermission
from trusts.zero.registration import (
    donate_content_permission_conditions,
    donate_installed_permission_conditions,
    donate_junction_content_permission_conditions,
    register_zero_group,
    register_zero_relations,
)
from tests.apps import isolated_backend, live_backend
from tests.models import Ticket


ROOT = Path(__file__).resolve().parents[1]
CORE_PIN = '91e1fb690e14a88626ff3c1c05b137da96c6b254'
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

        self.assertIn('backend.register(', registration)
        self.assertIn('trust=TrustUserPermission', registration)
        self.assertIn('backend.add_named_filter(', registration)
        self.assertIn('predicate=', registration)
        self.assertIn('backend.add_named_filter', apps)
        self.assertIn('register_zero_relations(backend)', apps)
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
        self.assertIn('predicate=', migrates)
        self.assertIn("Python 'in' is unsupported", migrates)

        for path in APPLICATION_PATHS:
            text = path.read_text()
            for needle in TEMPORARY_METHOD_NEEDLES:
                self.assertNotIn(
                    needle, text,
                    '%s still teaches %s' % (path.relative_to(ROOT), needle),
                )
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
        self.assertNotIn(STALE_PIN, ci)
        self.assertNotIn('#211', ci)
        self.assertNotIn('C-methods', ci)

    def test_live_backend_exposes_final_methods_not_as_required_api(self):
        backend = live_backend()
        self.assertTrue(callable(backend.register))
        self.assertFalse(hasattr(backend, 'register_relationship'))
        self.assertTrue(callable(backend.add_named_filter))
        source = inspect.getsource(ZeroConfig._donate_zero_relations)
        self.assertIn('add_named_filter', inspect.getsource(
            __import__('trusts.zero.registration', fromlist=['donate_installed_permission_conditions'])
        ))
        self.assertNotIn('register_permission_condition', source)
        self.assertNotIn('handle =', source)


class ZMethodsPlanTests(SimpleTestCase):
    def test_tup_and_tgp_plans_or_complete_records(self):
        backend = isolated_backend()
        register_zero_relations(backend)
        tup = backend.registry.records_for_root(TrustUserPermission)
        tgp = backend.registry.records_for_root(TrustGroupPermission)
        self.assertEqual(len(tup), 1)
        self.assertEqual(len(tgp), 2)
        self.assertIs(tup[0].content_model, Trust)
        self.assertEqual(tup[0].user_field, 'entity')
        self.assertEqual(tgp[0].user_path, tgp[1].user_path)
        self.assertEqual(tgp[0].permission_path, tgp[1].permission_path)
        self.assertNotEqual(tgp[0].condition, tgp[1].condition)
        self.assertFalse(callable(tup[0].condition))
        self.assertFalse(callable(tgp[0].condition))
        self.assertFalse(callable(tgp[1].condition))
        self.assertEqual(
            {row.content_model for row in tup + tgp},
            {Trust},
        )

    def test_register_zero_group_keeps_two_alternatives(self):
        backend = isolated_backend()
        register_zero_group(backend, (Trust,))
        rows = backend.registry.records_for_root(TrustGroupPermission)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0].condition, rows[1].condition)


class ZMethodsDonationOnceTests(TestCase):
    def test_trust_own_and_ticket_own_are_donated_once(self):
        backend = live_backend()
        registry = backend.registry
        own = [
            (model, code)
            for model, code, record in registry.iter_permission_conditions()
            if model is Trust and code == 'own'
        ]
        ticket = [
            (model, code)
            for model, code, record in registry.iter_permission_conditions()
            if model is Ticket and code == 'own'
        ]
        self.assertEqual(len(own), 1)
        self.assertEqual(len(ticket), 1)
        donate_installed_permission_conditions(backend)
        self.assertEqual(
            len([
                row for row in registry.iter_permission_conditions()
                if row[0] is Trust and row[1] == 'own'
            ]),
            1,
        )

    def test_repeated_helper_donation_is_idempotent_and_zero_sql(self):
        backend = isolated_backend()
        with self.assertNumQueries(0):
            register_zero_relations(backend)
            first = list(backend.registry.records)
            register_zero_relations(backend)
            donate_content_permission_conditions(backend, Trust)
            donate_content_permission_conditions(backend, Trust)
        self.assertEqual(list(backend.registry.records), first)
        own = backend.registry.get_permission_condition_record(Trust, 'own')
        self.assertIsNotNone(own)
        self.assertIsNotNone(own.expr)
        self.assertFalse(hasattr(own, 'func'))

    def test_repeated_ready_is_idempotent_without_reading_registry_flags(self):
        owner = zero_config()
        backend = owner.configured_backend(CANONICAL_BACKEND_PATH)
        before = list(backend.registry.records)
        own_before = backend.registry.get_permission_condition_record(Trust, 'own')
        with self.assertNumQueries(0):
            owner.ready()
        after = owner.configured_backend(CANONICAL_BACKEND_PATH)
        self.assertEqual(list(after.registry.records), before)
        self.assertIs(
            after.registry.get_permission_condition_record(Trust, 'own'),
            own_before,
        )
        source = inspect.getsource(
            __import__('trusts.zero.registration', fromlist=['x'])
        )
        self.assertNotIn('_zero_z1_relation_ids', source)
        self.assertNotIn('_zero_condition_donation_id', source)

    def test_frozen_add_named_filter_is_before_builder(self):
        calls = []

        def boom(u, p, o):
            calls.append((u, p, o))
            return u == o.settlor

        with self.assertRaises(TrustsConfigurationError):
            live_backend().add_named_filter(Trust, 'late32', predicate=boom)
        self.assertEqual(calls, [])

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

        isolated = isolated_backend()
        donate_junction_content_permission_conditions(isolated, MemoJunction)
        self.assertIsNotNone(
            isolated.registry.get_permission_condition_record(
                MemoJunction, 'via_memo',
            )
        )
        self.assertIsNone(
            live_backend().registry.get_permission_condition_record(
                MemoJunction, 'via_memo',
            )
        )


class ZMethodsCoreInternalFixtureNote(SimpleTestCase):
    def test_trusts_registry_condition_api_remains_core_internal(self):
        isolated = TrustsRegistry()
        isolated.register_permission_condition(
            Ticket, 'own', lambda u, p, o: u == o.owner,
        )
        self.assertIsNotNone(isolated.get_permission_condition_record(Ticket, 'own'))
        with self.assertRaises(TypeError):
            donate_content_permission_conditions(isolated, Ticket)
