"""Zero #37: donate first-party relations through public register()."""

import ast
import inspect
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from trusts.zero.models import Trust, TrustGroupPermission, TrustUserPermission
from trusts.zero.registration import (
    register_zero_direct,
    register_zero_group,
    register_zero_relations,
)
from tests.apps import isolated_backend, live_backend
from tests.legacy.helpers import enable_local_group_grant, get_or_create_root_user
from tests.models import Category


ROOT = Path(__file__).resolve().parents[1]
CORE_PIN = '8bfe6151b5a65af2d0667ab3a71680eecc90a691'
REGISTRATION = ROOT / 'trusts' / 'zero' / 'registration.py'
MIGRATES = ROOT / 'migrates.md'


class RegisterMigrationSurfaceTests(SimpleTestCase):
    def test_registration_uses_public_register_and_contains_grammar(self):
        source = REGISTRATION.read_text()
        self.assertIn('backend.register(', source)
        self.assertIn('trust=TrustUserPermission', source)
        self.assertIn('trust=TrustGroupPermission', source)
        self.assertIn(
            't.trustgroup.group.permissions.contains(', source,
        )
        self.assertIn(
            't.trustgroup.group.roles.permissions.contains(', source,
        )
        self.assertIn('t.permission', source)
        self.assertNotIn('register_relationship(', source)
        self.assertNotIn('permission_in(', source)
        self.assertNotIn('predicate=', source)
        self.assertNotIn(' in t.', source)
        for helper in (register_zero_direct, register_zero_group):
            tree = ast.parse(inspect.getsource(helper))
            self.assertEqual(
                [node for node in ast.walk(tree)
                 if isinstance(node, (ast.In, ast.NotIn))],
                [],
                helper.__name__,
            )

    def test_migrates_records_old_and_new_relationship_forms(self):
        text = MIGRATES.read_text()
        self.assertIn(
            'backend.register_relationship(\n'
            '    TrustUserPermission,\n'
            '    user="entity",\n'
            '    permission="permission",\n'
            '    content="trust__<reverse>",\n'
            ')',
            text,
        )
        self.assertIn(
            'condition=permission_in("trustgroup__group__permissions")',
            text,
        )
        self.assertIn(
            'condition=permission_in("trustgroup__group__roles__permissions")',
            text,
        )
        self.assertIn(
            'backend.register(\n'
            '    trust=TrustUserPermission,\n'
            '    user="entity",\n'
            '    permission="permission",\n'
            '    content="trust__<reverse>",\n'
            ')',
            text,
        )
        self.assertIn(
            'condition=lambda t: t.trustgroup.group.permissions.contains('
            't.permission)',
            text,
        )
        self.assertIn(
            't.trustgroup.group.roles.permissions.contains(',
            text,
        )
        self.assertIn('register_relationship(', text)
        self.assertIn('permission_in(', text)
        self.assertIn("Python 'in' is unsupported", text)
        self.assertIn(
            'do not write `t.permission in t.trustgroup.group.permissions`',
            text,
        )

    def test_companion_pin_is_reviewed_django_trusts_211(self):
        req = (ROOT / 'requirements.txt').read_text()
        ci = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text()
        self.assertIn(CORE_PIN, req)
        self.assertIn('COMPANION_KERNEL_SHA: %s' % CORE_PIN, ci)


class PublicRegisterDonationTests(SimpleTestCase):
    def test_direct_group_and_role_ceilings_register_on_public_backend(self):
        backend = isolated_backend()
        self.assertTrue(callable(backend.register))
        self.assertFalse(hasattr(backend, 'register_relationship'))

        register_zero_direct(backend, (Trust,))
        tup = backend.registry.records_for_root(TrustUserPermission)
        self.assertEqual(len(tup), 1)
        self.assertIs(tup[0].content_model, Trust)
        self.assertEqual(tup[0].user_field, 'entity')
        self.assertIsNone(tup[0].condition)
        self.assertFalse(callable(tup[0].condition))

        register_zero_group(backend, (Trust,))
        tgp = backend.registry.records_for_root(TrustGroupPermission)
        self.assertEqual(len(tgp), 2)
        self.assertEqual(tgp[0].user_path, tgp[1].user_path)
        self.assertEqual(tgp[0].permission_path, tgp[1].permission_path)
        self.assertNotEqual(tgp[0].condition, tgp[1].condition)
        representations = {repr(row.condition) for row in tgp}
        self.assertTrue(
            any('roles' not in item and 'permissions' in item
                for item in representations),
            representations,
        )
        self.assertTrue(
            any('roles' in item and 'permissions' in item
                for item in representations),
            representations,
        )
        for row in tgp:
            self.assertFalse(callable(row.condition))
            self.assertFalse(callable(row))
            self.assertNotIsInstance(row.condition, type(lambda: None))

    def test_donation_is_idempotent_zero_sql_and_stores_no_callable(self):
        backend = isolated_backend()
        with self.assertNumQueries(0):
            register_zero_relations(backend)
            first = list(backend.registry.records)
            register_zero_relations(backend)
        self.assertEqual(list(backend.registry.records), first)
        self.assertEqual(len(first), 3)
        for row in first:
            self.assertFalse(callable(row.condition))
            for value in (row.condition, row.user_path, row.permission_path):
                self.assertFalse(inspect.isfunction(value))
                self.assertFalse(inspect.isbuiltin(value))


class PublicRegisterAuthorizationTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group, Permission, User
        from django.contrib.contenttypes.models import ContentType
        from django.core.management import call_command
        from trusts.zero.models import Role

        get_or_create_root_user(self)
        call_command('create_trust_root')
        self.User = User
        self.Role = Role
        self.user = User.objects.create_user('iss37', 'iss37@example.com', 'x')
        self.user.is_active = True
        self.user.save()
        self.root = Trust.objects.get_root()
        self.org = Trust(settlor=self.user, trust=self.root, title='Iss37 Org')
        self.org.save()
        self.category = Category.objects.create(trust=self.org, name='iss37-cat')
        self.perm = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Category),
            codename='read_category',
        )
        self.group = Group.objects.create(name='iss37-group')
        self.group.user_set.add(self.user)
        self.code = 'trusts_zero_tests.read_category'

    def _reload(self):
        self.user = self.User.objects.get(pk=self.user.pk)

    def _assert_allowed(self):
        self._reload()
        self.assertTrue(self.user.has_perm(self.code, self.category))
        self.assertIn(
            self.category.pk,
            Category.objects.permitted('read', self.user).values_list(
                'pk', flat=True,
            ),
        )

    def _assert_denied(self):
        self._reload()
        self.assertFalse(self.user.has_perm(self.code, self.category))
        self.assertNotIn(
            self.category.pk,
            Category.objects.permitted('read', self.user).values_list(
                'pk', flat=True,
            ),
        )

    def _assert_local_grant_remains(self):
        self.assertTrue(
            TrustGroupPermission.objects.filter(
                trustgroup__trust=self.org,
                trustgroup__group=self.group,
                permission=self.perm,
            ).exists()
        )

    def test_live_backend_exposes_public_register_only(self):
        backend = live_backend()
        self.assertTrue(callable(backend.register))
        self.assertFalse(hasattr(backend, 'register_relationship'))
        tup = backend.registry.records_for_root(TrustUserPermission)
        tgp = backend.registry.records_for_root(TrustGroupPermission)
        self.assertTrue(any(row.content_model is Category for row in tup))
        self.assertGreaterEqual(len([row for row in tgp if row.content_model is Category]), 2)
        for row in tup + tgp:
            self.assertFalse(callable(row.condition))

    def test_direct_user_grant_still_allows(self):
        from trusts.zero.models import TrustUserPermission as TUP

        TUP.objects.create(
            trust=self.org, entity=self.user, permission=self.perm,
        )
        self._reload()
        self.assertTrue(self.user.has_perm(self.code, self.category))

    def test_group_permissions_ceiling_still_allows(self):
        self.group.permissions.add(self.perm)
        enable_local_group_grant(self.org, self.group, self.perm)
        self._assert_allowed()

    def test_role_permissions_ceiling_still_allows(self):
        role, _created = self.Role.objects.get_or_create(name='iss37-public')
        role.permissions.add(self.perm)
        role.groups.add(self.group)
        enable_local_group_grant(self.org, self.group, self.perm)
        self._reload()
        self.assertTrue(self.user.has_perm(self.code, self.category))

    def test_missing_ceiling_still_denies(self):
        self._reload()
        self.assertFalse(self.user.has_perm(self.code, self.category))
        self.assertFalse(
            Category.objects.permitted('read', self.user).exists()
        )

    def test_removing_direct_group_ceiling_denies_with_local_grant(self):
        # Direct group-permission ceiling only. No role overlay.
        self.assertFalse(self.group.roles.exists())
        self.group.permissions.add(self.perm)
        enable_local_group_grant(self.org, self.group, self.perm)
        self._assert_allowed()

        self.group.permissions.remove(self.perm)
        self._assert_local_grant_remains()
        self.assertFalse(self.group.permissions.filter(pk=self.perm.pk).exists())
        self._assert_denied()

    def test_removing_role_ceiling_denies_with_local_grant(self):
        # Role-permission ceiling only. No direct Group.permissions overlay.
        role, _created = self.Role.objects.get_or_create(name='iss37-role')
        role.permissions.add(self.perm)
        role.groups.add(self.group)
        self.assertFalse(self.group.permissions.filter(pk=self.perm.pk).exists())
        enable_local_group_grant(self.org, self.group, self.perm)
        self._assert_allowed()

        role.permissions.remove(self.perm)
        self._assert_local_grant_remains()
        self.assertFalse(self.group.permissions.filter(pk=self.perm.pk).exists())
        self.assertFalse(role.permissions.filter(pk=self.perm.pk).exists())
        self._assert_denied()
