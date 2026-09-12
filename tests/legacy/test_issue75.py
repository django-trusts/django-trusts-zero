"""Copied from django-trusts@948d6666342377b9472debb57d4a1e26e81402d1 ``trusts/test_issue75.py`` for issue #37 Zero-first coverage.

Final-state adaptations: Zero test app label, core registry APIs, no Content._conditions.

Generic multi-path / path-store / compiler-protocol / contribution-path /
compiler-isolation classes were deleted (core-owned; restore under
``tests/core/`` with neutral hosts). Zero keeps runnable live one-path
and Zero-noun assertions — no ``@unittest.skip`` stand-ins.
"""

"""S3a: path-scoped registries and aggregate list authorization (issue #75).

Backend ``has_perm`` / enumeration stay on the historical path. Structural
and behavioral tests only — no source-token or ``inspect.getsource``
assertions.
"""

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import isolate_apps

from tests.apps import TestsConfig, live_config, live_registry
import tests as tests_module
from tests.models import Category, Organization, Ticket
from trusts.checks import check_query_compilers
from trusts.zero.models import Trust, TrustUserPermission
from tests.legacy.helpers import (
    enable_local_group_grant,
    get_or_create_root_user,
)

CONCRETE = 'trusts.zero.backends.TrustModelBackend'
MISSING = 'tests.backends.MissingCompilerBackend'

def _pks(qs):
    return set(qs.values_list('pk', flat=True))

def _perm(model, codename):
    return Permission.objects.get(
        content_type=ContentType.objects.get_for_model(model),
        codename=codename,
    )

@isolate_apps(
    'tests',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    attr_name='isolated_apps',
)
class IsolatedAppsPathStoreTest(SimpleTestCase):
    def test_isolate_apps_without_trusts_does_not_donate(self):
        live = live_config()
        before = live.registry.records
        self.assertFalse(self.isolated_apps.is_installed('trusts'))
        contributor = TestsConfig('tests', tests_module)
        contributor.apps = self.isolated_apps
        contributor.ready()
        self.assertIsNone(
            getattr(contributor, '_trusts_tup_category_registry_id', None)
        )
        self.assertIsNone(
            getattr(contributor, '_trusts_tup_ticket_registry_id', None)
        )
        self.assertIsNone(
            getattr(contributor, '_trusts_tup_group_registry_id', None)
        )
        self.assertEqual(live.registry.records, before)

class CompilerCheckQueryCountTest(TestCase):
    def test_e004_check_issues_zero_sql(self):
        with override_settings(AUTHENTICATION_BACKENDS=(MISSING, CONCRETE)):
            with self.assertNumQueries(0):
                check_query_compilers(None)

class OnePathPermittedUnchangedTest(TestCase):
    def setUp(self):
        super().setUp()
        call_command('create_trust_root')
        get_or_create_root_user(self)
        self.alice = User.objects.create_user('alice', 'alice@example.com', 'x')
        self.carol = User.objects.create_user('carol', 'carol@example.com', 'x')
        for user in (self.alice, self.carol):
            user.is_active = True
            user.save()
        root = Trust.objects.get_root()
        self.trust_a = Trust(settlor=self.alice, trust=root, title='Trust A')
        self.trust_a.save()
        self.cat_a = Category.objects.create(trust=self.trust_a, name='keep')
        self.change = _perm(Category, 'change_category')
        self.change_code = 'trusts_zero_tests.change_category'
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).save()
        self.carol_group = Group.objects.create(name='carol-s3a')
        self.carol.groups.add(self.carol_group)
        self.change.group_set.add(self.carol_group)
        enable_local_group_grant(self.trust_a, self.carol_group, self.change)
        self.alice = User.objects.get(pk=self.alice.pk)
        self.carol = User.objects.get(pk=self.carol.pk)

    def test_category_ticket_trust_object_results_unchanged(self):
        self.assertEqual(
            _pks(Category.objects.permitted(self.change_code, self.alice)),
            {self.cat_a.pk},
        )
        self.assertEqual(
            _pks(Category.objects.permitted(self.change_code, self.carol)),
            {self.cat_a.pk},
        )
        organization = Organization.objects.create(name='Org', manager=self.alice)
        ticket = Ticket.objects.create(
            trust=self.trust_a, title='t', owner=self.alice,
            organization=organization, status='open',
        )
        TrustUserPermission(
            trust=self.trust_a,
            entity=self.alice,
            permission=_perm(Ticket, 'change_ticket'),
        ).save()
        self.alice = User.objects.get(pk=self.alice.pk)
        self.assertIn(
            ticket.pk,
            _pks(Ticket.objects.permitted('trusts_zero_tests.change_ticket', self.alice)),
        )
        child = Trust(settlor=self.alice, trust=self.trust_a, title='Child A')
        child.save()
        TrustUserPermission(
            trust=self.trust_a,
            entity=self.alice,
            permission=_perm(Trust, 'change_trust'),
        ).save()
        self.alice = User.objects.get(pk=self.alice.pk)
        self.assertIn(
            child.pk,
            _pks(Trust.objects.permitted('trusts.change_trust', self.alice)),
        )

class ContentConditionsPreservedTest(TestCase):
    def test_conditions_registry_still_lives_on_content(self):
        self.assertTrue(hasattr(live_registry(), 'conditions'))
        self.assertIsNotNone(
            live_registry().get_permission_condition_record(Trust, 'own')
        )
