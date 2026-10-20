"""Catalog freeze and missing-declaration checks (issue #89).

Build-on-demand registries and register-after-build were removed with
Core's catalog. A recorder freezes at build. ``trusts.E003`` reads the
live catalog and does not register.
"""

from contextlib import contextmanager
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core.checks import Error, run_checks
from django.core.management import call_command
from django.db import models
from django.test import SimpleTestCase, TestCase, override_settings

from tests.apps import (
    catalog_from,
    forget_models,
    isolated_factory,
    live_catalog,
    live_config,
    live_recorder,
    register_relations,
)
from tests.models import (
    AutoAdminCategory,
    AutoAdminJunction,
    ManualAdminCategory,
)
from trusts.errors import TrustsConfigurationError
from trusts.inspect.checks import (
    CHECK_ID_MISSING_DECLARATION,
    CHECK_ID_OBSOLETE_CALLBACK_SETTING,
    check_missing_declarations,
    check_permission_conditions,
    check_query_compilers,
)
from trusts.zero.models import Content, Junction, Trust, TrustUserPermission


def _e003(messages=None):
    if messages is None:
        messages = check_missing_declarations(None)
    return [
        message for message in messages
        if message.id == CHECK_ID_MISSING_DECLARATION
    ]


def _objs(messages):
    return {message.obj for message in messages}


@contextmanager
def _dynamic_models(*model_classes):
    try:
        yield model_classes
    finally:
        forget_models(*model_classes)


class RecorderFreezeTest(SimpleTestCase):
    def test_ready_freezes_the_live_recorder(self):
        recorder = live_recorder()
        self.assertTrue(recorder.frozen)
        self.assertTrue(live_catalog().plan_for(Trust).records)
        with self.assertRaises(TrustsConfigurationError):
            recorder.register(
                trust=TrustUserPermission,
                user='entity',
                permission='permission',
                content='trust',
            )
        with self.assertRaises(TrustsConfigurationError):
            recorder.add_named_filter(
                Trust, 'late', lambda u, p, o: u == o.settlor,
            )

    def test_factory_build_freezes_the_factory(self):
        factory = isolated_factory()
        register_relations(factory, Trust)
        catalog = catalog_from(factory)
        self.assertTrue(factory.frozen)
        self.assertTrue(catalog.plan_for(Trust).records)
        with self.assertRaises(TrustsConfigurationError):
            factory.register_public(
                trust=TrustUserPermission,
                user='entity',
                permission='permission',
                content='trust',
            )

    def test_duplicate_trust_registration_fails_at_register(self):
        factory = isolated_factory()
        register_relations(factory, Trust)
        with self.assertRaises(TrustsConfigurationError):
            register_relations(factory, Trust)

    def test_malformed_path_fails_at_register(self):
        factory = isolated_factory()
        with self.assertRaises(TrustsConfigurationError):
            factory.register_public(
                trust=TrustUserPermission,
                user='entity',
                permission='permission',
                content='not_a_field',
            )

    def test_ready_again_keeps_the_live_catalog(self):
        catalog = live_catalog()
        before = catalog.records
        live_config().ready()
        self.assertIs(live_catalog(), catalog)
        self.assertEqual(live_catalog().records, before)


class MissingDeclarationCheckTest(TestCase):
    def test_declared_terminals_have_no_e003(self):
        messages = _e003()
        self.assertEqual(messages, [])

    def test_undeclared_content_and_junction_are_reported(self):
        class OrphanSheet(Content):
            title = models.CharField(max_length=12)

            class Meta:
                app_label = 'trusts_zero_tests'
                managed = False

        class OrphanTarget(models.Model):
            title = models.CharField(max_length=12)

            class Meta:
                app_label = 'trusts_zero_tests'
                managed = False

        class OrphanJunction(Junction):
            content = models.ForeignKey(
                OrphanTarget, unique=True, on_delete=models.CASCADE,
            )

            class Meta:
                app_label = 'trusts_zero_tests'
                managed = False

        with _dynamic_models(OrphanSheet, OrphanTarget, OrphanJunction):
            messages = _e003()
            objs = _objs(messages)
            self.assertIn(OrphanSheet, objs)
            self.assertIn(OrphanJunction, objs)
            self.assertNotIn(OrphanTarget, objs)
            self.assertTrue(all(isinstance(message, Error) for message in messages))
            self.assertTrue(all(message.hint for message in messages))
            sheet = [message for message in messages if message.obj is OrphanSheet]
            junction = [
                message for message in messages if message.obj is OrphanJunction
            ]
            self.assertEqual(len(sheet), 1)
            self.assertEqual(len(junction), 1)
            self.assertIn('OrphanSheet', sheet[0].msg)
            self.assertIn('OrphanJunction', junction[0].msg)
            self.assertIn('exact backend path', sheet[0].hint)

    def test_abstract_proxy_and_manual_dependents_are_not_reported(self):
        class AbstractHolder(Content):
            class Meta:
                abstract = True
                app_label = 'trusts_zero_tests'

        class ManualImage(models.Model):
            title = models.CharField(max_length=12)

            class Meta:
                app_label = 'trusts_zero_tests'
                managed = False

        with _dynamic_models(ManualImage):
            objs = _objs(_e003())
            self.assertNotIn(AbstractHolder, objs)
            self.assertNotIn(AutoAdminCategory, objs)
            self.assertNotIn(ManualAdminCategory, objs)
            self.assertNotIn(AutoAdminJunction, objs)
            self.assertNotIn(ManualImage, objs)

    def test_malformed_junction_is_diagnostic_not_a_crash(self):
        class BrokenJunction(Junction):
            extra = models.ForeignKey(
                User, null=True, on_delete=models.SET_NULL,
            )
            other = models.ForeignKey(
                Group, null=True, on_delete=models.SET_NULL,
            )

            class Meta:
                app_label = 'trusts_zero_tests'
                managed = False

        with _dynamic_models(BrokenJunction):
            messages = _e003()
            broken = [
                message for message in messages if message.obj is BrokenJunction
            ]
            self.assertEqual(len(broken), 1)
            self.assertIsInstance(broken[0], Error)
            self.assertIn('malformed', broken[0].msg.lower())
            self.assertEqual(broken[0].id, CHECK_ID_MISSING_DECLARATION)

    def test_check_is_zero_sql_and_does_not_change_records(self):
        catalog = live_catalog()
        before = catalog.records
        with self.assertNumQueries(0):
            messages = check_missing_declarations(None)
        self.assertEqual(_e003(messages), [])
        self.assertEqual(live_catalog().records, before)
        self.assertIs(live_catalog(), catalog)

    def test_manage_py_check_subset_and_direct_invocation(self):
        with self.assertNumQueries(0):
            out = StringIO()
            err = StringIO()
            call_command('check', stdout=out, stderr=err)
            combined = out.getvalue() + err.getvalue()
        self.assertNotIn(CHECK_ID_MISSING_DECLARATION, combined)
        with self.assertNumQueries(0):
            out = StringIO()
            err = StringIO()
            call_command('check', 'trusts', stdout=out, stderr=err)
            subset = out.getvalue() + err.getvalue()
        self.assertNotIn(CHECK_ID_MISSING_DECLARATION, subset)
        with self.assertNumQueries(0):
            subset_messages = check_missing_declarations(app_configs=[live_config()])
        self.assertEqual(_e003(subset_messages), [])

    def test_e003_coexists_and_silencing_does_not_authorize(self):
        class QuietSheet(Content):
            title = models.CharField(max_length=12)

            class Meta:
                app_label = 'trusts_zero_tests'
                managed = False

        with _dynamic_models(QuietSheet):
            all_ids = {message.id for message in run_checks()}
            self.assertIn(CHECK_ID_MISSING_DECLARATION, all_ids)
            condition_ids = {
                message.id for message in check_permission_conditions(None)
            }
            compiler_ids = {message.id for message in check_query_compilers(None)}
            self.assertNotIn(CHECK_ID_MISSING_DECLARATION, condition_ids)
            self.assertNotIn(CHECK_ID_MISSING_DECLARATION, compiler_ids)
            self.assertNotIn(CHECK_ID_OBSOLETE_CALLBACK_SETTING, _e003())
            with override_settings(
                SILENCED_SYSTEM_CHECKS=['trusts.E003', 'fields.W342'],
            ):
                silenced = check_missing_declarations(None)
                self.assertTrue(silenced)
                self.assertTrue(all(message.is_silenced() for message in silenced))
                call_command('check', stdout=StringIO(), stderr=StringIO())
            self.assertFalse(live_catalog().plan_for(QuietSheet).records)
