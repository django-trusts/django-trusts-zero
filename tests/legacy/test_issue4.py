"""Queryable permission conditions (issue #4).

Ad-hoc builders are registered on an isolated factory. Object checks
use ``catalog.has_perm``. List checks use ``catalog.filter_authorized``
plus the compiled condition. ``:own`` and ``Trust:own`` are on the live catalog.
"""

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase

from tests.apps import (
    catalog_from, isolated_catalog, isolated_compiler, isolated_recorder,
    live_catalog, register_relations,
)
from tests.legacy.helpers import (
    create_test_users,
    get_or_create_root_user,
    reload_test_users,
)
from tests.models import Organization, Ticket
from trusts.conditions import (
    PermissionConditionBooleanError,
    PermissionConditionError,
    PermissionConditionUnsupported,
)
from trusts.zero.models import Trust, TrustUserPermission
class _BuilderLog(object):
    """Builder that records the one registration-time symbolic invoke."""

    def __init__(self, impl):
        self.impl = impl
        self.calls = []

    def __call__(self, u, p, o):
        self.calls.append((u, p, o))
        return self.impl(u, p, o)


class QueryableConditionTest(TestCase):
    def setUp(self):
        super().setUp()
        call_command('create_trust_root')
        get_or_create_root_user(self)
        create_test_users(self)

        self.org_trust = Trust(
            settlor=self.user, trust=Trust.objects.get_root(), title='Tickets Org'
        )
        self.org_trust.save()
        self.other_trust = Trust(
            settlor=self.user1, trust=Trust.objects.get_root(), title='Other Org'
        )
        self.other_trust.save()

        self.company = Organization.objects.create(name='Acme', manager=self.user)
        self.other_company = Organization.objects.create(
            name='OtherCo', manager=self.user1
        )

        self.owned_open = Ticket.objects.create(
            trust=self.org_trust, title='owned-open', owner=self.user,
            organization=self.other_company, status='open',
        )
        self.owned_locked = Ticket.objects.create(
            trust=self.org_trust, title='owned-locked', owner=self.user,
            organization=self.other_company, status='locked', region='west',
        )
        self.managed_open = Ticket.objects.create(
            trust=self.org_trust, title='managed-open', owner=self.user1,
            organization=self.company, status='open',
        )
        self.managed_locked = Ticket.objects.create(
            trust=self.org_trust, title='managed-locked', owner=self.user1,
            organization=self.company, status='locked',
        )
        self.unrelated = Ticket.objects.create(
            trust=self.org_trust, title='unrelated', owner=self.user1,
            organization=self.other_company, status='open',
        )
        self.no_grant = Ticket.objects.create(
            trust=self.other_trust, title='owned-no-grant', owner=self.user,
            organization=self.company, status='open',
        )

        self.perm_change = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Ticket),
            codename='change_ticket',
        )
        TrustUserPermission(
            trust=self.org_trust, entity=self.user, permission=self.perm_change
        ).save()
        reload_test_users(self)

        self.spy_log = _BuilderLog(lambda u, p, o: u == o.owner)

        def register(factory):
            register_relations(factory, Ticket)
            factory.add_named_filter(
                Ticket, 'editable',
                lambda u, p, o: (
                    (u == o.owner)
                    | ((u == o.organization.manager) & (o.status != 'locked'))
                ),
            )
            factory.add_named_filter(
                Ticket, 'unlocked',
                lambda u, p, o: (
                    ((u == o.owner) | (u == o.organization.manager))
                    & (o.status != 'locked')
                ),
            )
            factory.add_named_filter(
                Ticket, 'open', lambda u, p, o: o.status == 'open',
            )
            factory.add_named_filter(
                Ticket, 'never', lambda u, p, o: o.title == '__never__',
            )
            factory.add_named_filter(
                Ticket, 'unset_region', lambda u, p, o: o.region == None,
            )
            factory.add_named_filter(
                Ticket, 'named', lambda u, p, o: u.username == o.region,
            )
            factory.add_named_filter(
                Ticket, 'same_people',
                lambda u, p, o: o.owner == o.organization.manager,
            )
            factory.add_named_filter(
                Ticket, 'status_eq_str', lambda u, p, o: o.status == '1',
            )
            factory.add_named_filter(Ticket, 'spy', self.spy_log)

        self.catalog = isolated_catalog(register)
        self.change = 'trusts_zero_tests.change_ticket'
        self.change_editable = 'trusts_zero_tests.change_ticket:editable'
        self.change_own = 'trusts_zero_tests.change_ticket:own'
        self.change_open = 'trusts_zero_tests.change_ticket:open'

    def _reject(self, code, builder, exc=PermissionConditionError):
        def register(factory):
            factory.add_named_filter(Ticket, code, builder)

        with self.assertRaises(exc) as ctx:
            isolated_catalog(register)
        self.assertIsNone(
            live_catalog().get_permission_condition_record(Ticket, code)
        )
        return str(ctx.exception)

    def _catalog_qs(self, perm, user):
        qs = self.catalog.filter_authorized(
            Ticket.objects.all(), user, self.perm_change,
        )
        if ':' in perm:
            overlay = self.catalog.compile_registered_condition_q(
                Ticket, perm, user,
            )
            qs = qs.filter(overlay)
        return qs

    def _catalog_pks(self, perm, user):
        return set(self._catalog_qs(perm, user).values_list('pk', flat=True))

    def _catalog_direct(self, perm, user):
        return {
            obj.pk for obj in Ticket.objects.all()
            if self.catalog.has_perm(user, perm, obj)
        }

    def _assert_catalog_parity(self, perm, user):
        qs = self._catalog_qs(perm, user)
        self.assertEqual(
            set(qs.values_list('pk', flat=True)),
            self._catalog_direct(perm, user),
        )
        sql = str(qs.query)
        self.assertTrue(
            'JOIN' in sql.upper() or 'EXISTS' in sql.upper()
            or 'trusts_trustuserpermission' in sql,
            'permitted rows must filter in SQL. SQL was: %s' % sql,
        )
        self.assertEqual(list(qs[:50]), list(qs))

    def _live_direct(self, perm, user):
        return {
            obj.pk for obj in Ticket.objects.all()
            if user.has_perm(perm, obj)
        }

    def _assert_live_parity(self, perm, user):
        qs = Ticket.objects.permitted(perm, user)
        self.assertEqual(
            set(qs.values_list('pk', flat=True)),
            self._live_direct(perm, user),
        )
        sql = str(qs.query)
        self.assertTrue(
            'JOIN' in sql.upper() or 'EXISTS' in sql.upper()
            or 'trusts_trustuserpermission' in sql,
            'permitted() must filter in SQL. SQL was: %s' % sql,
        )
        self.assertEqual(list(qs[:50]), list(qs))

    def test_nested_expression_object_and_queryset_parity(self):
        self.assertTrue(self.catalog.has_perm(self.user, self.change, self.owned_open))
        self.assertTrue(
            self.catalog.has_perm(self.user, self.change_editable, self.owned_open)
        )
        self.assertTrue(
            self.catalog.has_perm(self.user, self.change_editable, self.owned_locked)
        )
        self.assertTrue(
            self.catalog.has_perm(self.user, self.change_editable, self.managed_open)
        )
        self.assertFalse(
            self.catalog.has_perm(self.user, self.change_editable, self.managed_locked)
        )
        self.assertFalse(
            self.catalog.has_perm(self.user, self.change_editable, self.unrelated)
        )
        self.assertFalse(self.catalog.has_perm(self.user, self.change, self.no_grant))
        self.assertFalse(
            self.catalog.has_perm(self.user, self.change_editable, self.no_grant)
        )

        self.assertEqual(
            self._catalog_pks(self.change_editable, self.user),
            {self.owned_open.pk, self.owned_locked.pk, self.managed_open.pk},
        )
        self._assert_catalog_parity(self.change_editable, self.user)

        unlocked = 'trusts_zero_tests.change_ticket:unlocked'
        self.assertTrue(self.catalog.has_perm(self.user, unlocked, self.owned_open))
        self.assertFalse(self.catalog.has_perm(self.user, unlocked, self.owned_locked))
        self.assertTrue(self.catalog.has_perm(self.user, unlocked, self.managed_open))
        self.assertFalse(self.catalog.has_perm(self.user, unlocked, self.managed_locked))
        self.assertEqual(
            self._catalog_pks(unlocked, self.user),
            {self.owned_open.pk, self.managed_open.pk},
        )
        self._assert_catalog_parity(unlocked, self.user)

    def test_relationship_traversal_and_constants(self):
        self.assertTrue(self.user.has_perm(self.change_own, self.owned_open))
        self.assertFalse(self.user.has_perm(self.change_own, self.managed_open))
        self.assertTrue(self.catalog.has_perm(self.user, self.change_open, self.owned_open))
        self.assertFalse(
            self.catalog.has_perm(self.user, self.change_open, self.managed_locked)
        )

        own_pks = set(
            Ticket.objects.permitted(self.change_own, self.user).values_list('pk', flat=True)
        )
        self.assertEqual(own_pks, {self.owned_open.pk, self.owned_locked.pk})
        self.assertEqual(
            self._catalog_pks(self.change_open, self.user),
            {self.owned_open.pk, self.managed_open.pk, self.unrelated.pk},
        )
        self._assert_live_parity(self.change_own, self.user)
        self._assert_catalog_parity(self.change_open, self.user)

    def test_condition_does_not_grant_without_base_permission(self):
        self.assertTrue(self.user.has_perm(self.change_own, self.owned_open))
        self.assertFalse(self.user.has_perm(self.change_own, self.no_grant))
        self.assertNotIn(
            self.no_grant.pk,
            Ticket.objects.permitted(self.change_own, self.user).values_list('pk', flat=True),
        )
        self.assertFalse(self.user1.has_perm(self.change, self.owned_open))
        self.assertFalse(self.user1.has_perm(self.change_own, self.owned_open))
        self.assertFalse(Ticket.objects.permitted(self.change_own, self.user1).exists())

    def test_inactive_user_empty_on_both_paths(self):
        self.user.is_active = False
        self.user.save()
        reload_test_users(self)
        self.assertFalse(self.user.has_perm(self.change, self.owned_open))
        self.assertFalse(self.catalog.has_perm(self.user, self.change_editable, self.owned_open))
        self.assertFalse(Ticket.objects.permitted(self.change, self.user).exists())
        self.assertFalse(self._catalog_qs(self.change_editable, self.user).exists())

    def test_unconditioned_grant_is_still_unfiltered(self):
        pks = set(
            Ticket.objects.permitted(self.change, self.user).values_list('pk', flat=True)
        )
        self.assertEqual(
            pks,
            {
                self.owned_open.pk, self.owned_locked.pk, self.managed_open.pk,
                self.managed_locked.pk, self.unrelated.pk,
            },
        )
        self._assert_live_parity(self.change, self.user)

    def test_always_false_builder_is_queryable_and_denies(self):
        never = 'trusts_zero_tests.change_ticket:never'
        self.assertTrue(self.catalog.has_perm(self.user, self.change, self.owned_open))
        self.assertFalse(self.catalog.has_perm(self.user, never, self.owned_open))
        self.assertFalse(self._catalog_qs(never, self.user).exists())
        self.assertIn(
            self.owned_open.pk,
            Ticket.objects.permitted(self.change, self.user).values_list('pk', flat=True),
        )

    def test_python_or_builder_fails_at_build(self):
        message = self._reject(
            'python_or',
            lambda u, p, o: (u == o.owner) or (o.status == 'open'),
            PermissionConditionBooleanError,
        )
        self.assertTrue(message)

    def test_method_call_builder_fails_at_build(self):
        self._reject(
            'called',
            lambda u, p, o: o.status.lower() == 'open',
            PermissionConditionUnsupported,
        )

    def test_non_callable_and_boolean_builder_fail_at_build(self):
        self._reject('bad', 'not-a-condition', TypeError)
        self._reject('truth', lambda u, p, o: True, PermissionConditionError)

    def test_builder_own_is_queryable(self):
        self.assertTrue(self.user.has_perm(self.change_own, self.owned_open))
        self.assertFalse(self.user.has_perm(self.change_own, self.managed_open))
        self._assert_live_parity(self.change_own, self.user)

    def test_builder_invoked_once_with_refs_never_during_auth(self):
        self.assertEqual(len(self.spy_log.calls), 1)
        spy = 'trusts_zero_tests.change_ticket:spy'
        self.assertTrue(self.catalog.has_perm(self.user, spy, self.owned_open))
        self.assertFalse(self.catalog.has_perm(self.user, spy, self.managed_open))
        self.assertEqual(
            self._catalog_pks(spy, self.user),
            {self.owned_open.pk, self.owned_locked.pk},
        )
        self.assertEqual(len(self.spy_log.calls), 1)

    def test_add_named_filter_does_not_invoke_the_builder(self):
        log = _BuilderLog(lambda u, p, o: u == o.owner)
        recorder = isolated_recorder()
        recorder.add_named_filter(Ticket, 'late', log)
        self.assertEqual(len(log.calls), 0)
        factory = isolated_compiler()
        factory.add_named_filter(Ticket, 'late', log)
        catalog = catalog_from(factory)
        self.assertEqual(len(log.calls), 1)
        self.assertIsNotNone(catalog.get_permission_condition_record(Ticket, 'late'))

    def test_invalid_field_path_fails_closed(self):
        message = self._reject('missing', lambda u, p, o: u == o.not_a_field)
        self.assertIn('not_a_field', message)

    def test_misspelled_principal_field_does_not_match_null_object_field(self):
        message = self._reject('typo', lambda u, p, o: u.regoin == o.region)
        self.assertIn('regoin', message)
        self.assertIsNone(self.owned_open.region)
        self.assertTrue(self.user.has_perm(self.change, self.owned_open))

    def test_nullable_object_field_none_is_not_a_missing_attribute(self):
        unset = 'trusts_zero_tests.change_ticket:unset_region'
        self.assertTrue(self.catalog.has_perm(self.user, unset, self.owned_open))
        self.assertFalse(self.catalog.has_perm(self.user, unset, self.owned_locked))
        pks = self._catalog_pks(unset, self.user)
        self.assertIn(self.owned_open.pk, pks)
        self.assertNotIn(self.owned_locked.pk, pks)
        self._assert_catalog_parity(unset, self.user)

    def test_validated_principal_field_path(self):
        self.owned_open.region = self.user.username
        self.owned_open.save()
        named = 'trusts_zero_tests.change_ticket:named'
        self.assertTrue(self.catalog.has_perm(self.user, named, self.owned_open))
        self.assertFalse(self.catalog.has_perm(self.user, named, self.owned_locked))
        self.assertEqual(self._catalog_pks(named, self.user), {self.owned_open.pk})
        self._assert_catalog_parity(named, self.user)

    def test_nonempty_permission_path_fails_closed(self):
        message = self._reject('ptypo', lambda u, p, o: p.codenmae == None)
        self.assertIn('Permission', message)
        self._reject('pcode', lambda u, p, o: p.codename == None)
        self.assertTrue(self.user.has_perm(self.change, self.owned_open))

    def test_terminal_m2m_and_reverse_o2m_fail_closed(self):
        group = Group.objects.create(name='cond-group')
        self.user.groups.add(group)
        message = self._reject(
            'ingroup', lambda u, p, o: o.owner.groups == group,
        )
        self.assertIn('groups', message)
        message = self._reject(
            'siblings', lambda u, p, o: o.organization.tickets == None,
        )
        self.assertIn('tickets', message)
        self.assertTrue(self.user.has_perm(self.change, self.owned_open))

    def test_two_object_field_equality_parity(self):
        perm = 'trusts_zero_tests.change_ticket:same_people'
        self._assert_catalog_parity(perm, self.user)

    def test_charfield_integer_literal_rejected_on_eq_and_ne(self):
        self.owned_open.status = '1'
        self.owned_open.save()
        self.assertIn('incompatible', self._reject(
            'status_eq_int', lambda u, p, o: o.status == 1,
        ))
        self.assertIn('incompatible', self._reject(
            'status_ne_int', lambda u, p, o: o.status != 1,
        ))
        code = 'trusts_zero_tests.change_ticket:status_eq_str'
        self.assertTrue(self.catalog.has_perm(self.user, code, self.owned_open))
        self.assertIn(self.owned_open.pk, self._catalog_pks(code, self.user))

    def test_relation_raw_pk_rejected_on_eq_and_ne(self):
        for code, builder in (
            ('owner_eq_str', lambda u, p, o: o.owner == '1'),
            ('owner_ne_str', lambda u, p, o: o.owner != '1'),
            ('owner_eq_int', lambda u, p, o: o.owner == 1),
            ('owner_ne_int', lambda u, p, o: o.owner != 1),
        ):
            message = self._reject(code, builder)
            self.assertIn('incompatible', message)
            self.assertIn('primary keys', message)
        self.assertTrue(self.user.has_perm(self.change_own, self.owned_open))

    def test_builtin_own_is_registered_expression(self):
        record = live_catalog().get_permission_condition_record(Trust, 'own')
        self.assertIsNotNone(record)
        self.assertIsNotNone(record.expr)
        self.assertIs(record.model, Trust)
        self.assertEqual(
            record.expr.to_tuple(),
            ('eq', ('ref', 'principal', ()), ('ref', 'object', ('settlor',))),
        )

        change_trust = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Trust),
            codename='change_trust',
        )
        TrustUserPermission(
            trust=self.org_trust, entity=self.user, permission=change_trust
        ).save()
        TrustUserPermission(
            trust=self.org_trust, entity=self.user1, permission=change_trust
        ).save()
        reload_test_users(self)
        child = Trust(
            settlor=self.user, title='Child owned', trust=self.org_trust
        )
        child.save()
        perm = 'trusts.change_trust:own'
        self.assertTrue(self.user.has_perm('trusts.change_trust', child))
        self.assertTrue(self.user.has_perm(perm, child))
        self.assertTrue(self.user1.has_perm('trusts.change_trust', child))
        self.assertFalse(self.user1.has_perm(perm, child))
        self.assertIn(
            child.pk,
            Trust.objects.permitted(perm, self.user).values_list('pk', flat=True),
        )
        self.assertNotIn(
            child.pk,
            Trust.objects.permitted(perm, self.user1).values_list('pk', flat=True),
        )
        self.assertEqual(
            set(Trust.objects.permitted(perm, self.user).values_list('pk', flat=True)),
            set(t.pk for t in Trust.objects.all() if self.user.has_perm(perm, t)),
        )
