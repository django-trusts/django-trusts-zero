"""Zero #18: declarative models, Meta names, TGP alternatives, moved UI."""

import ast
import inspect
import os
import subprocess
import sys
from pathlib import Path

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db.models import options
from django.template.loader import get_template
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from trusts.core import PlanQueryCompiler, TrustsRegistry
from trusts.zero.backends import TrustModelBackend
from trusts.zero.models import (
    Role,
    Trust,
    TrustGroupPermission,
    TrustUserPermission,
)
from trusts.zero.policy import (
    get_group_global_ceiling,
    permission_in_global_ceiling,
)
from trusts.zero.query import filter_scope_rows
from trusts.zero.registration import (
    ZERO_META_OPTION_NAMES,
    register_zero_group,
    register_zero_meta_option_names,
    register_zero_relations,
)
from tests.legacy.helpers import (
    enable_local_group_grant,
    get_or_create_root_user,
)
from tests.models import AutoAdminCategory, Category


ROOT = Path(__file__).resolve().parents[1]
MODELS_PATH = ROOT / 'trusts' / 'zero' / 'models.py'


FORBIDDEN_MODELS_HELPERS = (
    'reject_queryable_condition',
    'compile_registered_condition_q',
    'resolve_content_permission',
    'django_permission_filter',
    '_content_via_trust',
    'register_zero_direct',
    'register_zero_group',
    'register_zero_relations',
    '_has_tgp_records',
    'filter_scope_rows',
    'get_group_global_ceiling',
    'permission_in_global_ceiling',
    'donate_content_permission_conditions',
    'donate_junction_content_permission_conditions',
    'donate_installed_permission_conditions',
)


class ModelsDeclarativeOnlyTests(SimpleTestCase):
    def test_ast_rejects_module_level_execution_helpers(self):
        source = MODELS_PATH.read_text()
        tree = ast.parse(source)
        helpers = [
            node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertEqual(
            helpers, [],
            'trusts.zero.models must not define module-level helpers; found %r'
            % helpers,
        )
        for name in FORBIDDEN_MODELS_HELPERS:
            self.assertNotIn('def %s(' % name, source)
        self.assertNotIn('options.DEFAULT_NAMES', source)
        self.assertNotIn('zero_config()', source)
        self.assertNotIn('permission_in(', source)
        import trusts.zero.models as models_mod
        for name in FORBIDDEN_MODELS_HELPERS:
            self.assertFalse(hasattr(models_mod, name), name)
        self.assertFalse(hasattr(models_mod, 'PermissionConditionNotQueryable'))
        self.assertFalse(hasattr(models_mod, 'ContentQuerySet'))
        self.assertFalse(hasattr(models_mod, 'TrustManager'))
        src = inspect.getsource(filter_scope_rows)
        self.assertIn('filter_authorized_scopes', src)
        self.assertNotIn('trust_grant_q', src)

    def test_models_import_does_not_register_meta_names(self):
        source = inspect.getsourcefile(__import__('trusts.zero.models', fromlist=['Trust']))
        self.assertTrue(source.endswith('models.py'))
        self.assertNotIn('DEFAULT_NAMES', MODELS_PATH.read_text())


class MetaOptionRegistrationTests(SimpleTestCase):
    def test_zero_only_names_registered_once_and_idempotent(self):
        before = tuple(options.DEFAULT_NAMES)
        for name in ZERO_META_OPTION_NAMES:
            self.assertEqual(before.count(name), 1, name)
        self.assertNotIn('permission_conditions', ZERO_META_OPTION_NAMES)
        added = register_zero_meta_option_names()
        self.assertEqual(added, ())
        self.assertEqual(tuple(options.DEFAULT_NAMES), before)
        register_zero_meta_option_names()
        self.assertEqual(tuple(options.DEFAULT_NAMES), before)

    def test_host_models_see_zero_meta_options(self):
        self.assertTrue(hasattr(Category._meta, 'roles'))
        self.assertTrue(hasattr(AutoAdminCategory._meta, 'auto_modeladmin'))
        self.assertTrue(AutoAdminCategory._meta.auto_modeladmin)

    def test_cold_start_host_model_after_apps_import(self):
        env = os.environ.copy()
        env['DJANGO_SETTINGS_MODULE'] = 'tests.settings'
        script = (
            'from trusts.zero.apps import register_zero_meta_option_names\n'
            'from django.db.models import options\n'
            'register_zero_meta_option_names()\n'
            'assert options.DEFAULT_NAMES.count("auto_modeladmin") == 1\n'
            'assert options.DEFAULT_NAMES.count("roles") == 1\n'
            'print("cold-start-meta-ok")\n'
        )
        out = subprocess.check_output(
            [sys.executable, '-c', script],
            env=env,
            cwd=str(ROOT),
            text=True,
        )
        self.assertIn('cold-start-meta-ok', out)


class BackendAndRegistrationTests(SimpleTestCase):
    def test_backend_uses_plan_query_compiler(self):
        self.assertIsInstance(
            TrustModelBackend.query_compiler, PlanQueryCompiler,
        )
        self.assertFalse(hasattr(
            __import__('trusts.zero.backends', fromlist=['x']),
            'HistoricalGroupQueryCompiler',
        ))

    def test_register_zero_relations_is_idempotent(self):
        registry = TrustsRegistry()
        register_zero_relations(registry)
        first = list(registry.records)
        register_zero_relations(registry)
        self.assertEqual(list(registry.records), first)
        tgp = registry.records_for_root(TrustGroupPermission)
        self.assertEqual(len(tgp), 2)

    def test_register_zero_group_two_alternatives(self):
        registry = TrustsRegistry()
        register_zero_group(registry, (Trust,))
        rows = registry.records_for_root(TrustGroupPermission)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0].condition, rows[1].condition)


class GroupCeilingPathTests(TestCase):
    def setUp(self):
        get_or_create_root_user(self)
        call_command('create_trust_root')
        self.user = User.objects.create_user('ceil', 'ceil@example.com', 'x')
        self.user.is_active = True
        self.user.save()
        self.root = Trust.objects.get_root()
        self.org = Trust(settlor=self.user, trust=self.root, title='Ceil Org')
        self.org.save()
        self.category = Category.objects.create(trust=self.org, name='ceil-cat')
        self.perm = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Category),
            codename='read_category',
        )
        self.group = Group.objects.create(name='ceil-group')
        self.group.user_set.add(self.user)
        self.code = 'trusts_zero_tests.read_category'

    def _reload(self):
        self.user = User.objects.get(pk=self.user.pk)

    def test_direct_group_permissions_ceiling_grants(self):
        self.group.permissions.add(self.perm)
        enable_local_group_grant(self.org, self.group, self.perm)
        self._reload()
        self.assertTrue(self.user.has_perm(self.code, self.category))
        self.assertIn(
            self.category.pk,
            Category.objects.permitted('read', self.user).values_list('pk', flat=True),
        )
        trusts = Trust.objects.filter_by_user_content_perm(
            self.user, Category, 'read',
        )
        self.assertIn(self.org.pk, trusts.values_list('pk', flat=True))

    def test_role_permissions_ceiling_grants(self):
        call_command('update_roles_permissions')
        Role.objects.get(name='public').groups.add(self.group)
        enable_local_group_grant(self.org, self.group, self.perm)
        self._reload()
        self.assertTrue(permission_in_global_ceiling(self.group, self.perm))
        self.assertIn(self.perm, get_group_global_ceiling(self.group))
        self.assertTrue(self.user.has_perm(self.code, self.category))
        self.assertIn(
            self.category.pk,
            Category.objects.permitted('read', self.user).values_list('pk', flat=True),
        )

    def test_neither_ceiling_denies_and_write_is_rejected(self):
        self.assertFalse(permission_in_global_ceiling(self.group, self.perm))
        self.assertFalse(self.user.has_perm(self.code, self.category))
        from django.core.exceptions import ValidationError
        from trusts.zero.models import TrustGroup
        tg, _ = TrustGroup.objects.get_or_create(trust=self.org, group=self.group)
        with self.assertRaises(ValidationError):
            TrustGroupPermission.objects.create(trustgroup=tg, permission=self.perm)

    def test_inactive_and_anonymous_fail_closed(self):
        self.group.permissions.add(self.perm)
        enable_local_group_grant(self.org, self.group, self.perm)
        self.user.is_active = False
        self.user.save()
        self._reload()
        self.assertFalse(self.user.has_perm(self.code, self.category))
        self.assertFalse(Category.objects.permitted('read', self.user).exists())
        from django.contrib.auth.models import AnonymousUser
        self.assertFalse(
            Category.objects.permitted('read', AnonymousUser()).exists()
        )


class MovedUiSurfaceTests(TestCase):
    def setUp(self):
        get_or_create_root_user(self)
        call_command('create_trust_root')
        self.user = User.objects.create_user('ui', 'ui@example.com', 'x')
        self.user.is_active = True
        self.user.save()
        self.org = Trust(
            settlor=self.user, trust=Trust.objects.get_root(), title='UI Org',
        )
        self.org.save()
        self.group = Group.objects.create(name='UI Team')
        self.org.groups.add(self.group)
        change = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Trust),
            codename='change_trust',
        )
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=change,
        ).save()
        self.client = Client()
        self.client.force_login(self.user)

    def test_zero_url_namespace_and_templates(self):
        self.assertEqual(reverse('trusts:team_create'), '/teams/new/')
        self.assertEqual(
            reverse('trusts:team_detail', args=[self.group.pk]),
            '/teams/%s/' % self.group.pk,
        )
        form = get_template('trusts_zero/team_form.html')
        detail = get_template('trusts_zero/team_detail.html')
        self.assertIn('Create new team', form.render({}))
        response = self.client.get('/teams/%s/' % self.group.pk)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Members')


class InstalledUiScriptTests(SimpleTestCase):
    def test_verify_installed_ui_script_exists(self):
        script = ROOT / 'scripts' / 'verify-installed-ui.py'
        self.assertTrue(script.is_file())
        text = script.read_text()
        self.assertIn('trusts.zero.urls', text)
        self.assertIn('trusts_zero/team_form.html', text)
        self.assertIn('trusts_zero/team_detail.html', text)
