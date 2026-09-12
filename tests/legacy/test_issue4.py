"""Copied from django-trusts@948d6666342377b9472debb57d4a1e26e81402d1 ``trusts/test_issue4.py`` for issue #37 Zero-first coverage.

Final-state adaptations: Zero test app label, core registry APIs, no Content._conditions.
"""

"""Queryable V1 permission conditions (issue #4).

Parity between ``has_perm`` and ``ContentQuerySet.permitted`` for
named queryable conditions. Callables are registration-time builders.
"""

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from django_trusts import Query as DjangoTrustsQuery, TQ as DjangoTrustsTQ, condition_refs as django_condition_refs
from trusts.conditions import (
    Const,
    Expr,
    PermissionConditionBooleanError,
    PermissionConditionError,
    PermissionConditionUnsupported,
    Query,
    Ref,
    TQ,
    condition_refs,
    is_predicate,
    object_ref,
    permission_ref,
    principal_ref,
    validate_expression,
)
from trusts.zero.models import (
    Content,
    Trust,
    TrustUserPermission,
)
from trusts.core import TrustsRegistry
from tests.legacy.helpers import (
    create_test_users,
    get_or_create_root_user,
    reload_test_users,
)
from tests.apps import live_registry, publish_permission_condition
from tests.models import Organization, Ticket


u, p, o = condition_refs()
OWNED_OR_MANAGER_UNLOCKED = (
    (u == o.owner) |
    ((u == o.organization.manager) & (o.status != 'locked'))
)


class _BuilderLog(object):
    """Builder that records the one registration-time symbolic invoke."""

    def __init__(self, impl):
        self.impl = impl
        self.calls = []

    def __call__(self, u, p, o):
        self.calls.append((u, p, o))
        return self.impl(u, p, o)

    def saw_only_refs(self):
        return all(
            isinstance(arg, Ref) for call in self.calls for arg in call
        )


class ConditionGrammarTest(SimpleTestCase):
    def test_supported_nodes_to_tuple(self):
        u, p, o = condition_refs()
        eq = u == o.owner
        ne = o.status != 'locked'
        conjunction = eq & ne
        disjunction = eq | ne
        self.assertEqual(
            eq.to_tuple(),
            ('eq', ('ref', 'principal', ()), ('ref', 'object', ('owner',))),
        )
        self.assertEqual(
            ne.to_tuple(),
            ('ne', ('ref', 'object', ('status',)), ('const', 'locked')),
        )
        self.assertEqual(conjunction.to_tuple()[0], 'and')
        self.assertEqual(disjunction.to_tuple()[0], 'or')
        self.assertEqual(Const(None).to_tuple(), ('const', None))
        self.assertEqual(principal_ref().to_tuple(), ('ref', 'principal', ()))
        self.assertEqual(permission_ref().to_tuple(), ('ref', 'permission', ()))
        self.assertEqual(object_ref().to_tuple(), ('ref', 'object', ()))
        self.assertTrue(is_predicate(eq))
        self.assertTrue(is_predicate(conjunction))
        self.assertFalse(is_predicate(o.owner))

    def test_nested_grouping_is_preserved(self):
        self.assertEqual(
            OWNED_OR_MANAGER_UNLOCKED.to_tuple(),
            (
                'or',
                ('eq', ('ref', 'principal', ()), ('ref', 'object', ('owner',))),
                (
                    'and',
                    (
                        'eq',
                        ('ref', 'principal', ()),
                        ('ref', 'object', ('organization', 'manager')),
                    ),
                    ('ne', ('ref', 'object', ('status',)), ('const', 'locked')),
                ),
            ),
        )

    def test_python_or_at_construction_raises_boolean_error(self):
        u, p, o = condition_refs()
        with self.assertRaises(PermissionConditionBooleanError) as ctx:
            (u == o.owner) or (o.status == 'open')
        self.assertIn('&', str(ctx.exception))
        self.assertIn('|', str(ctx.exception))

    def test_chained_comparison_raises_boolean_error(self):
        u, p, o = condition_refs()
        with self.assertRaises(PermissionConditionBooleanError) as ctx:
            0 < o.amount < 100
        self.assertIn('chained', str(ctx.exception))

    def test_ordering_expr_is_not_a_v1_predicate(self):
        u, p, o = condition_refs()
        ordering = o.amount < 100
        self.assertIsInstance(ordering, Expr)
        self.assertFalse(is_predicate(ordering))
        with self.assertRaises(PermissionConditionError):
            TrustsRegistry().register_permission_condition(Ticket, 'range', ordering)

    def test_calls_indexing_arithmetic_setters_rejected(self):
        u, p, o = condition_refs()
        with self.assertRaises(PermissionConditionUnsupported):
            o.status.lower()
        with self.assertRaises(PermissionConditionUnsupported):
            o.status[0]
        with self.assertRaises(PermissionConditionUnsupported):
            o.amount + 1
        with self.assertRaises(PermissionConditionUnsupported):
            o.owner = u
        with self.assertRaises(PermissionConditionUnsupported):
            o.status[0] = 'x'
        with self.assertRaises(PermissionConditionUnsupported):
            ~ (u == o.owner)
        with self.assertRaises(PermissionConditionUnsupported):
            1 in o.status
        with self.assertRaises(PermissionConditionUnsupported):
            list(o.owner)

    def test_tq_namespace_is_reserved_without_v1_lookups(self):
        self.assertIs(Query, TQ)
        self.assertIs(DjangoTrustsQuery, Query)
        self.assertIs(DjangoTrustsTQ, TQ)
        self.assertEqual(django_condition_refs()[0].to_tuple(), ('ref', 'principal', ()))
        with self.assertRaises(PermissionConditionUnsupported) as ctx:
            TQ.iexact
        self.assertIn('iexact', str(ctx.exception))
        with self.assertRaises(PermissionConditionUnsupported):
            TQ.isin

    def test_non_predicate_and_non_callable_rejected_at_register(self):
        u, p, o = condition_refs()
        isolated = TrustsRegistry()
        with self.assertRaises(PermissionConditionError):
            isolated.register_permission_condition(Ticket, 'bare', o.owner)
        with self.assertRaises(TypeError):
            isolated.register_permission_condition(Ticket, 'bad', 'not-a-condition')
        with self.assertRaises(PermissionConditionError):
            isolated.register_permission_condition(
                Ticket, 'truth', lambda u, p, o: True,
            )

    def test_incompatible_literal_types_rejected_at_validate(self):
        u, p, o = condition_refs()
        with self.assertRaises(PermissionConditionError) as ctx:
            validate_expression(o.status == 1, Ticket)
        self.assertIn('incompatible', str(ctx.exception))
        with self.assertRaises(PermissionConditionError):
            validate_expression(o.status != 1, Ticket)
        with self.assertRaises(PermissionConditionError):
            validate_expression(o.owner == '1', Ticket)
        with self.assertRaises(PermissionConditionError):
            validate_expression(o.owner != 1, Ticket)
        validate_expression(o.status == 'open', Ticket)
        validate_expression(u == o.owner, Ticket)
        validate_expression(o.region == None, Ticket)


class QueryableConditionTest(TestCase):
    def setUp(self):
        super(QueryableConditionTest, self).setUp()
        self._saved_conditions = dict(live_registry().conditions._records)
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

        publish_permission_condition(
            Ticket, 'editable',
            lambda u, p, o: (
                (u == o.owner)
                | ((u == o.organization.manager) & (o.status != 'locked'))
            ),
        )
        publish_permission_condition(
            Ticket, 'unlocked',
            lambda u, p, o: (
                ((u == o.owner) | (u == o.organization.manager))
                & (o.status != 'locked')
            ),
        )
        publish_permission_condition(Ticket, 'own', lambda u, p, o: u == o.owner)
        publish_permission_condition(Ticket, 'open', lambda u, p, o: o.status == 'open')
        publish_permission_condition(Ticket, 'never', lambda u, p, o: o.pk == -1)

        self.change = 'trusts_zero_tests.change_ticket'
        self.change_editable = 'trusts_zero_tests.change_ticket:editable'
        self.change_own = 'trusts_zero_tests.change_ticket:own'
        self.change_open = 'trusts_zero_tests.change_ticket:open'

    def tearDown(self):
        live_registry().conditions._records.clear()
        live_registry().conditions._records.update(self._saved_conditions)
        super(QueryableConditionTest, self).tearDown()

    def _direct_pks(self, perm, user):
        return set(
            obj.pk for obj in Ticket.objects.all()
            if user.has_perm(perm, obj)
        )

    def _assert_parity(self, perm, user):
        qs = Ticket.objects.permitted(perm, user)
        self.assertEqual(set(qs.values_list('pk', flat=True)), self._direct_pks(perm, user))
        sql = str(qs.query)
        self.assertTrue(
            'JOIN' in sql.upper() or 'EXISTS' in sql.upper() or 'trusts_trustuserpermission' in sql,
            'permitted() must filter in SQL. SQL was: %s' % sql,
        )
        self.assertEqual(list(qs[:50]), list(qs))

    def test_expression_tree_preserves_nested_grouping(self):
        u, p, o = condition_refs()
        expr = (u == o.owner) | ((u == o.organization.manager) & (o.status != 'locked'))
        self.assertEqual(expr.to_tuple(), OWNED_OR_MANAGER_UNLOCKED.to_tuple())

    def test_nested_expression_object_and_queryset_parity(self):
        self.assertTrue(self.user.has_perm(self.change, self.owned_open))
        self.assertTrue(self.user.has_perm(self.change_editable, self.owned_open))
        self.assertTrue(self.user.has_perm(self.change_editable, self.owned_locked))
        self.assertTrue(self.user.has_perm(self.change_editable, self.managed_open))
        self.assertFalse(self.user.has_perm(self.change_editable, self.managed_locked))
        self.assertFalse(self.user.has_perm(self.change_editable, self.unrelated))
        self.assertFalse(self.user.has_perm(self.change, self.no_grant))
        self.assertFalse(self.user.has_perm(self.change_editable, self.no_grant))

        pks = set(Ticket.objects.permitted(self.change_editable, self.user).values_list('pk', flat=True))
        self.assertEqual(pks, {self.owned_open.pk, self.owned_locked.pk, self.managed_open.pk})
        self._assert_parity(self.change_editable, self.user)

        unlocked = 'trusts_zero_tests.change_ticket:unlocked'
        self.assertTrue(self.user.has_perm(unlocked, self.owned_open))
        self.assertFalse(self.user.has_perm(unlocked, self.owned_locked))
        self.assertTrue(self.user.has_perm(unlocked, self.managed_open))
        self.assertFalse(self.user.has_perm(unlocked, self.managed_locked))
        unlocked_pks = set(Ticket.objects.permitted(unlocked, self.user).values_list('pk', flat=True))
        self.assertEqual(unlocked_pks, {self.owned_open.pk, self.managed_open.pk})
        self._assert_parity(unlocked, self.user)

    def test_relationship_traversal_and_constants(self):
        self.assertTrue(self.user.has_perm(self.change_own, self.owned_open))
        self.assertFalse(self.user.has_perm(self.change_own, self.managed_open))
        self.assertTrue(self.user.has_perm(self.change_open, self.owned_open))
        self.assertFalse(self.user.has_perm(self.change_open, self.managed_locked))

        own_pks = set(Ticket.objects.permitted(self.change_own, self.user).values_list('pk', flat=True))
        self.assertEqual(own_pks, {self.owned_open.pk, self.owned_locked.pk})
        open_pks = set(Ticket.objects.permitted(self.change_open, self.user).values_list('pk', flat=True))
        self.assertEqual(
            open_pks,
            {self.owned_open.pk, self.managed_open.pk, self.unrelated.pk},
        )
        self._assert_parity(self.change_own, self.user)
        self._assert_parity(self.change_open, self.user)

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
        self.assertFalse(self.user.has_perm(self.change_editable, self.owned_open))
        self.assertFalse(Ticket.objects.permitted(self.change, self.user).exists())
        self.assertFalse(Ticket.objects.permitted(self.change_editable, self.user).exists())

    def test_unconditioned_grant_is_still_unfiltered(self):
        pks = set(Ticket.objects.permitted(self.change, self.user).values_list('pk', flat=True))
        self.assertEqual(
            pks,
            {
                self.owned_open.pk, self.owned_locked.pk, self.managed_open.pk,
                self.managed_locked.pk, self.unrelated.pk,
            },
        )
        self._assert_parity(self.change, self.user)

    def test_always_false_builder_is_queryable_and_denies(self):
        never = 'trusts_zero_tests.change_ticket:never'
        self.assertTrue(self.user.has_perm(self.change, self.owned_open))
        self.assertFalse(self.user.has_perm(never, self.owned_open))
        self.assertFalse(Ticket.objects.permitted(never, self.user).exists())
        self.assertIn(
            self.owned_open.pk,
            Ticket.objects.permitted(self.change, self.user).values_list('pk', flat=True),
        )

    def test_python_or_builder_fails_at_register(self):
        isolated = TrustsRegistry()
        with self.assertRaises(PermissionConditionBooleanError):
            isolated.register_permission_condition(
                Ticket, 'python_or',
                lambda u, p, o: (u == o.owner) or (o.status == 'open'),
            )
        self.assertIsNone(isolated.get_permission_condition_record(Ticket, 'python_or'))

    def test_method_call_builder_fails_at_register(self):
        isolated = TrustsRegistry()
        with self.assertRaises(PermissionConditionUnsupported):
            isolated.register_permission_condition(
                Ticket, 'called',
                lambda u, p, o: o.status.lower() == 'open',
            )
        self.assertIsNone(isolated.get_permission_condition_record(Ticket, 'called'))

    def test_builder_own_is_queryable(self):
        legacy = 'trusts_zero_tests.change_ticket:own'
        self.assertTrue(self.user.has_perm(legacy, self.owned_open))
        self.assertFalse(self.user.has_perm(legacy, self.managed_open))
        self._assert_parity(legacy, self.user)

    def test_builder_invoked_once_with_refs_never_during_auth(self):
        log = _BuilderLog(lambda u, p, o: u == o.owner)
        publish_permission_condition(Ticket, 'spy', log)
        self.assertEqual(len(log.calls), 1)
        self.assertTrue(log.saw_only_refs())
        spy = 'trusts_zero_tests.change_ticket:spy'
        self.assertTrue(self.user.has_perm(spy, self.owned_open))
        self.assertFalse(self.user.has_perm(spy, self.managed_open))
        pks = set(Ticket.objects.permitted(spy, self.user).values_list('pk', flat=True))
        self.assertEqual(pks, {self.owned_open.pk, self.owned_locked.pk})
        self.assertEqual(len(log.calls), 1)

    def test_invalid_field_path_fails_closed(self):
        isolated = TrustsRegistry()
        with self.assertRaises(PermissionConditionError) as missing:
            isolated.register_permission_condition(
                Ticket, 'missing', lambda u, p, o: u == o.not_a_field,
            )
        self.assertIn('not_a_field', str(missing.exception))
        self.assertIsNone(isolated.get_permission_condition_record(Ticket, 'missing'))

    def test_misspelled_principal_field_does_not_match_null_object_field(self):
        """A typo on ``u`` must not compile to ``region__isnull=True``.

        ``owned_open.region`` is NULL and the user has a base grant. Binding
        a missing principal attribute as ``None`` would allow that row.
        """
        isolated = TrustsRegistry()
        with self.assertRaises(PermissionConditionError) as typo:
            isolated.register_permission_condition(
                Ticket, 'typo', lambda u, p, o: u.regoin == o.region,
            )
        self.assertIn('regoin', str(typo.exception))
        self.assertIsNone(isolated.get_permission_condition_record(Ticket, 'typo'))
        self.assertIsNone(self.owned_open.region)
        self.assertTrue(self.user.has_perm(self.change, self.owned_open))

    def test_nullable_object_field_none_is_not_a_missing_attribute(self):
        publish_permission_condition(
            Ticket, 'unset_region', lambda u, p, o: o.region == None,
        )
        unset = 'trusts_zero_tests.change_ticket:unset_region'
        self.assertTrue(self.user.has_perm(unset, self.owned_open))
        self.assertFalse(self.user.has_perm(unset, self.owned_locked))
        pks = set(Ticket.objects.permitted(unset, self.user).values_list('pk', flat=True))
        self.assertIn(self.owned_open.pk, pks)
        self.assertNotIn(self.owned_locked.pk, pks)
        self._assert_parity(unset, self.user)

    def test_validated_principal_field_path(self):
        self.owned_open.region = self.user.username
        self.owned_open.save()
        publish_permission_condition(
            Ticket, 'named', lambda u, p, o: u.username == o.region,
        )
        named = 'trusts_zero_tests.change_ticket:named'
        self.assertTrue(self.user.has_perm(named, self.owned_open))
        self.assertFalse(self.user.has_perm(named, self.owned_locked))
        pks = set(Ticket.objects.permitted(named, self.user).values_list('pk', flat=True))
        self.assertEqual(pks, {self.owned_open.pk})
        self._assert_parity(named, self.user)

    def test_nonempty_permission_path_fails_closed(self):
        """``p.codenmae`` must not become an always-true ``None == None``."""
        isolated = TrustsRegistry()
        with self.assertRaises(PermissionConditionError) as ptypo:
            isolated.register_permission_condition(
                Ticket, 'ptypo', lambda u, p, o: p.codenmae == None,
            )
        self.assertIn('Permission', str(ptypo.exception))
        with self.assertRaises(PermissionConditionError):
            isolated.register_permission_condition(
                Ticket, 'pcode', lambda u, p, o: p.codename == None,
            )
        self.assertTrue(self.user.has_perm(self.change, self.owned_open))

    def test_terminal_m2m_and_reverse_o2m_fail_closed_on_both_paths(self):
        group = Group.objects.create(name='cond-group')
        self.user.groups.add(group)
        isolated = TrustsRegistry()
        with self.assertRaises(PermissionConditionError) as ingroup:
            isolated.register_permission_condition(
                Ticket, 'ingroup', lambda u, p, o: o.owner.groups == group,
            )
        self.assertIn('groups', str(ingroup.exception))
        with self.assertRaises(PermissionConditionError) as siblings:
            isolated.register_permission_condition(
                Ticket, 'siblings', lambda u, p, o: o.organization.tickets == None,
            )
        self.assertIn('tickets', str(siblings.exception))
        self.assertTrue(self.user.has_perm(self.change, self.owned_open))

    def test_two_object_field_equality_parity(self):
        publish_permission_condition(
            Ticket, 'same_people',
            lambda u, p, o: o.owner == o.organization.manager,
        )
        perm = 'trusts_zero_tests.change_ticket:same_people'
        self._assert_parity(perm, self.user)

    def test_charfield_integer_literal_rejected_on_eq_and_ne(self):
        """Django would coerce Q(status=1) to '1'; Python '"1" == 1' is False."""
        self.owned_open.status = '1'
        self.owned_open.save()
        isolated = TrustsRegistry()
        with self.assertRaises(PermissionConditionError) as eq_int:
            isolated.register_permission_condition(
                Ticket, 'status_eq_int', lambda u, p, o: o.status == 1,
            )
        self.assertIn('incompatible', str(eq_int.exception))
        with self.assertRaises(PermissionConditionError) as ne_int:
            isolated.register_permission_condition(
                Ticket, 'status_ne_int', lambda u, p, o: o.status != 1,
            )
        self.assertIn('incompatible', str(ne_int.exception))
        publish_permission_condition(
            Ticket, 'status_eq_str', lambda u, p, o: o.status == '1',
        )
        self.assertTrue(self.user.has_perm('trusts_zero_tests.change_ticket:status_eq_str', self.owned_open))
        self.assertIn(
            self.owned_open.pk,
            Ticket.objects.permitted('trusts_zero_tests.change_ticket:status_eq_str', self.user).values_list('pk', flat=True),
        )

    def test_relation_raw_pk_rejected_on_eq_and_ne(self):
        """Django would coerce Q(owner='1') through the FK; Python compares the User."""
        isolated = TrustsRegistry()
        for code, builder in (
            ('owner_eq_str', lambda u, p, o: o.owner == '1'),
            ('owner_ne_str', lambda u, p, o: o.owner != '1'),
            ('owner_eq_int', lambda u, p, o: o.owner == 1),
            ('owner_ne_int', lambda u, p, o: o.owner != 1),
        ):
            with self.assertRaises(PermissionConditionError) as ctx:
                isolated.register_permission_condition(Ticket, code, builder)
            self.assertIn('incompatible', str(ctx.exception))
            self.assertIn('primary keys', str(ctx.exception))
        self.assertTrue(self.user.has_perm(self.change_own, self.owned_open))

    def test_builtin_own_is_registered_expression(self):
        record = live_registry().get_permission_condition_record(Trust, 'own')
        self.assertIsNotNone(record)
        self.assertIsNotNone(record.expr)
        self.assertFalse(hasattr(record, 'func'))
        self.assertIs(record.model, Trust)
        self.assertTrue(is_predicate(record.expr))
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
            set(
                t.pk for t in Trust.objects.all()
                if self.user.has_perm(perm, t)
            ),
        )
