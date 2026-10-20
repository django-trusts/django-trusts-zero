"""Compiler checks and single-catalog authorization (issue #75).

Path-scoped registries, alias stores, and cross-backend OR were removed
with Core's catalog. One catalog ORs trustee and group records.
"""

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.checks import Error, run_checks
from django.core.management import call_command
from django.db.models.query import QuerySet
from django.test import SimpleTestCase, TestCase, override_settings

from tests.legacy.helpers import enable_local_group_grant, get_or_create_root_user
from tests.models import Category, Organization, Ticket
from trusts.inspect.checks import CHECK_ID_MISSING_COMPILER, check_query_compilers
from trusts.zero.models import Trust, TrustUserPermission


MISSING = 'tests.backends.MissingCompilerBackend'
MALFORMED = 'tests.backends.MalformedCompilerBackend'
CONCRETE = 'trusts.zero.backends.TrustModelBackend'


def _pks(qs):
    return set(qs.values_list('pk', flat=True))


def _perm(model, codename):
    return Permission.objects.get(
        content_type=ContentType.objects.get_for_model(model),
        codename=codename,
    )


class CompilerCheckTest(SimpleTestCase):
    def test_malformed_compiler_is_e004(self):
        with override_settings(AUTHENTICATION_BACKENDS=(MISSING,)):
            errors = [
                message for message in check_query_compilers(None)
                if message.id == CHECK_ID_MISSING_COMPILER
            ]
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], Error)
            self.assertIn('not query-capable', errors[0].msg)
        with override_settings(AUTHENTICATION_BACKENDS=(MALFORMED,)):
            errors = [
                message for message in check_query_compilers(None)
                if message.id == CHECK_ID_MISSING_COMPILER
            ]
            self.assertEqual(len(errors), 1)

    def test_listed_zero_backend_emits_no_e004(self):
        with override_settings(AUTHENTICATION_BACKENDS=(CONCRETE,)):
            errors = [
                message for message in check_query_compilers(None)
                if message.id == CHECK_ID_MISSING_COMPILER
            ]
        self.assertEqual(errors, [])


class CompilerCheckQueryCountTest(TestCase):
    def test_e004_check_issues_zero_sql(self):
        with override_settings(AUTHENTICATION_BACKENDS=(MISSING, CONCRETE)):
            with self.assertNumQueries(0):
                check_query_compilers(None)

    def test_valid_compilers_emit_no_e004(self):
        messages = [
            message for message in run_checks()
            if message.id == CHECK_ID_MISSING_COMPILER
        ]
        self.assertEqual(messages, [])


class OnePathPermittedTest(TestCase):
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

    def test_category_ticket_trust_object_results(self):
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
            _pks(Ticket.objects.permitted(
                'trusts_zero_tests.change_ticket', self.alice,
            )),
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


class TrusteeAndGroupAggregateTest(TestCase):
    def setUp(self):
        super().setUp()
        call_command('create_trust_root')
        get_or_create_root_user(self)
        self.alice = User.objects.create_user('alice75', 'alice75@example.com', 'x')
        self.carol = User.objects.create_user('carol75', 'carol75@example.com', 'x')
        for user in (self.alice, self.carol):
            user.is_active = True
            user.save()
        root = Trust.objects.get_root()
        self.trust_a = Trust(settlor=self.alice, trust=root, title='S3a A')
        self.trust_a.save()
        self.trust_b = Trust(settlor=self.alice, trust=root, title='S3a B')
        self.trust_b.save()
        self.cat_a = Category.objects.create(trust=self.trust_a, name='c-a')
        self.cat_b = Category.objects.create(trust=self.trust_b, name='c-b')
        self.change = _perm(Category, 'change_category')
        self.change_code = 'trusts_zero_tests.change_category'
        self.ticket_perm = _perm(Ticket, 'change_ticket')
        self.ticket_code = 'trusts_zero_tests.change_ticket'

    def _reload(self):
        self.alice = User.objects.get(pk=self.alice.pk)
        self.carol = User.objects.get(pk=self.carol.pk)

    def test_grant_through_neither(self):
        self.assertFalse(
            Category.objects.permitted(self.change_code, self.alice).exists()
        )

    def test_aggregate_ors_trustee_and_group_in_one_statement(self):
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).save()
        alice_group = Group.objects.create(name='alice-s3a-or')
        self.alice.groups.add(alice_group)
        self.change.group_set.add(alice_group)
        enable_local_group_grant(self.trust_b, alice_group, self.change)
        self._reload()
        permitted = Category.objects.permitted(self.change_code, self.alice)
        self.assertIsInstance(permitted, QuerySet)
        self.assertIsNone(permitted._result_cache)
        with self.assertNumQueries(1):
            self.assertEqual(_pks(permitted), {self.cat_a.pk, self.cat_b.pk})
        page = Category.objects.permitted(
            self.change_code, self.alice,
        ).order_by('pk')[:1]
        self.assertIsNone(page._result_cache)
        with self.assertNumQueries(1):
            self.assertEqual(list(page), [self.cat_a])

    def test_failed_ceiling_denies(self):
        self.carol_group = Group.objects.create(name='carol-s3a-ceiling')
        self.carol.groups.add(self.carol_group)
        self.change.group_set.add(self.carol_group)
        enable_local_group_grant(self.trust_a, self.carol_group, self.change)
        self.change.group_set.remove(self.carol_group)
        self._reload()
        self.assertFalse(
            Category.objects.permitted(self.change_code, self.carol).exists()
        )

    def test_different_terminals_stay_on_their_permissions(self):
        organization = Organization.objects.create(name='S3aOrg', manager=self.alice)
        ticket = Ticket.objects.create(
            trust=self.trust_a, title='s3a-t', owner=self.alice,
            organization=organization, status='open',
        )
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change,
        ).save()
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.ticket_perm,
        ).save()
        self._reload()
        self.assertEqual(
            _pks(Category.objects.permitted(self.change_code, self.alice)),
            {self.cat_a.pk},
        )
        self.assertEqual(
            _pks(Ticket.objects.permitted(self.ticket_code, self.alice)),
            {ticket.pk},
        )
