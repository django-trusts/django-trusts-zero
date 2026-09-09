"""Historical migration identity after the r3 import-only rewrite."""

import importlib

from django.db import connection, models as django_models
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase

from trusts.zero import GROUP_MODEL_NAME, PERMISSION_MODEL_NAME
from trusts.zero.models import ReadonlyFieldsMixin
from trusts.zero.management.commands.create_trust_root import create_root_trust


TRUSTS_TABLES = (
    'trusts_trust',
    'trusts_trustuserpermission',
    'trusts_trust_groups',
    'trusts_trustgrouppermission',
    'trusts_role',
    'trusts_rolepermission',
)


def _field_map(op):
    return dict(op.fields)


class HistoricalMigrationIdentityTests(TestCase):
    def test_loader_keys_remain_trusts_label_and_historical_names(self):
        loader = MigrationLoader(connection)
        self.assertIn(('trusts', '0001_initial'), loader.disk_migrations)
        self.assertIn(('trusts', '0002_trustgroup'), loader.disk_migrations)
        self.assertEqual(
            {name for app, name in loader.applied_migrations if app == 'trusts'},
            {'0001_initial', '0002_trustgroup'},
        )
        initial = loader.disk_migrations[('trusts', '0001_initial')]
        self.assertEqual(initial.__module__, 'trusts.zero.migrations.0001_initial')
        trustgroup = loader.disk_migrations[('trusts', '0002_trustgroup')]
        self.assertEqual(trustgroup.__module__, 'trusts.zero.migrations.0002_trustgroup')

    def test_python_imports_are_zero_owned_modules(self):
        initial = importlib.import_module('trusts.zero.migrations.0001_initial')
        self.assertEqual(
            create_root_trust.__module__,
            'trusts.zero.management.commands.create_trust_root',
        )
        self.assertIs(initial.create_root_trust, create_root_trust)
        self.assertIs(initial.ReadonlyFieldsMixin, ReadonlyFieldsMixin)
        self.assertEqual(ReadonlyFieldsMixin.__module__, 'trusts.zero.models')

    def test_historical_migrations_import_pinned_auth_names(self):
        Initial = importlib.import_module('trusts.zero.migrations.0001_initial').Migration
        TrustGroupMigration = importlib.import_module(
            'trusts.zero.migrations.0002_trustgroup'
        ).Migration

        self.assertEqual(GROUP_MODEL_NAME, 'auth.Group')
        self.assertEqual(PERMISSION_MODEL_NAME, 'auth.Permission')

        trust_op = next(op for op in Initial.operations if getattr(op, 'name', None) == 'Trust')
        trust_fields = _field_map(trust_op)
        self.assertEqual(trust_fields['groups'].remote_field.model, 'auth.Group')
        self.assertEqual(trust_fields['settlor'].remote_field.model, 'auth.User')
        self.assertEqual(trust_fields['trust'].remote_field.model, 'trusts.Trust')
        self.assertEqual(trust_op.bases, (ReadonlyFieldsMixin, django_models.Model))

        tup_op = next(
            op for op in Initial.operations
            if getattr(op, 'name', None) == 'TrustUserPermission'
        )
        self.assertEqual(
            _field_map(tup_op)['permission'].remote_field.model, 'auth.Permission'
        )
        self.assertEqual(_field_map(tup_op)['trust'].remote_field.model, 'trusts.Trust')

        role_op = next(op for op in Initial.operations if getattr(op, 'name', None) == 'Role')
        role_fields = _field_map(role_op)
        self.assertEqual(role_fields['groups'].remote_field.model, 'auth.Group')
        self.assertEqual(role_fields['permissions'].remote_field.model, 'auth.Permission')
        self.assertEqual(role_fields['permissions'].remote_field.through, 'trusts.RolePermission')

        state_ops = TrustGroupMigration.operations[0].state_operations
        self.assertEqual(TrustGroupMigration.operations[0].database_operations, [])
        tg_op = next(op for op in state_ops if getattr(op, 'name', None) == 'TrustGroup')
        self.assertEqual(_field_map(tg_op)['group'].remote_field.model, 'auth.Group')
        self.assertEqual(tg_op.options['db_table'], 'trusts_trust_groups')
        tgp_op = next(
            op for op in TrustGroupMigration.operations
            if getattr(op, 'name', None) == 'TrustGroupPermission'
        )
        self.assertEqual(
            _field_map(tgp_op)['permission'].remote_field.model, 'auth.Permission'
        )
        self.assertEqual(
            _field_map(tgp_op)['trustgroup'].remote_field.model, 'trusts.trustgroup'
        )

    def test_schema_tables_and_content_types_use_historical_identity(self):
        table_names = set(connection.introspection.table_names())
        for table in TRUSTS_TABLES:
            self.assertIn(table, table_names)

        from django.contrib.contenttypes.models import ContentType
        from trusts.zero.models import (
            Role, RolePermission, Trust, TrustGroup, TrustGroupPermission,
            TrustUserPermission,
        )

        expected = {
            ('trusts', 'trust'),
            ('trusts', 'trustuserpermission'),
            ('trusts', 'trustgroup'),
            ('trusts', 'trustgrouppermission'),
            ('trusts', 'role'),
            ('trusts', 'rolepermission'),
        }
        found = {
            (ct.app_label, ct.model)
            for ct in ContentType.objects.filter(app_label='trusts')
            if ct.model in {row[1] for row in expected}
        }
        self.assertEqual(found, expected)
        for model in (
            Trust, TrustUserPermission, TrustGroup, TrustGroupPermission,
            Role, RolePermission,
        ):
            self.assertEqual(model._meta.app_label, 'trusts')
            ct = ContentType.objects.get_for_model(model)
            self.assertEqual(ct.app_label, 'trusts')
            self.assertEqual(ct.model, model._meta.model_name)
