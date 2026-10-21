"""Early validation of permission conditions via Django system checks (#29).

Invalid builders fail when the recorder is compiled. ``trusts.E001``
scans conditions on the live catalog and does not re-invoke builders.
"""

from io import StringIO

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.checks import run_checks
from django.core.management import call_command
from django.test import TestCase, override_settings

from tests.apps import (
    catalog_from, forget_models, isolated_catalog, isolated_compiler,
    live_catalog, live_config, register_relations,
)
from tests.legacy.helpers import (
    create_test_users,
    get_or_create_root_user,
    reload_test_users,
)
from tests.legacy.test_issue4 import _BuilderLog
from tests.models import AutoAdminCategory, Organization, Ticket
from trusts.conditions import PermissionConditionError
from trusts.inspect.checks import (
    CHECK_ID_INVALID_EXPR,
    CHECK_ID_OBSOLETE_CALLBACK_SETTING,
    check_obsolete_legacy_callback_setting,
    check_permission_conditions,
)
from trusts.zero.models import Content, Trust, TrustUserPermission


def _messages_with_id(messages, check_id):
    return [message for message in messages if message.id == check_id]


def _run_manage_py_check():
    out = StringIO()
    err = StringIO()
    call_command('check', stdout=out, stderr=err)
    return out.getvalue() + err.getvalue()


class PermissionConditionCheckTest(TestCase):
    """System-check diagnostics. Runtime fail-closed is covered with a grant."""

    def setUp(self):
        super().setUp()
        call_command('create_trust_root')
        get_or_create_root_user(self)
        create_test_users(self)
        self.org_trust = Trust(
            settlor=self.user, trust=Trust.objects.get_root(), title='Check Org'
        )
        self.org_trust.save()
        self.ticket = Ticket.objects.create(
            trust=self.org_trust, title='owned', owner=self.user,
            organization=self._organization(), status='open',
        )
        self.perm_change = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Ticket),
            codename='change_ticket',
        )
        TrustUserPermission(
            trust=self.org_trust, entity=self.user, permission=self.perm_change
        ).save()
        reload_test_users(self)
        self.change = 'trusts_zero_tests.change_ticket'

    def _organization(self):
        return Organization.objects.create(name='CheckCo', manager=self.user)

    def test_import_time_meta_and_builtin_own_are_valid(self):
        catalog = live_catalog()
        own = catalog.get_permission_condition_record(Trust, 'own')
        self.assertIsNotNone(own)
        self.assertIs(own.model, Trust)
        self.assertIsNotNone(own.expr)

        meta_own = catalog.get_permission_condition_record(Ticket, 'meta_own')
        self.assertIsNotNone(meta_own)
        self.assertIs(meta_own.model, Ticket)
        self.assertIsNotNone(meta_own.expr)
        ticket_own = catalog.get_permission_condition_record(Ticket, 'own')
        self.assertIsNotNone(ticket_own)
        donated = {
            (model, code)
            for model, code, _record in catalog.iter_permission_conditions()
        }
        self.assertIn((Trust, 'own'), donated)
        self.assertIn((Ticket, 'own'), donated)
        self.assertIn((Ticket, 'meta_own'), donated)

        messages = check_permission_conditions(None)
        self.assertEqual(_messages_with_id(messages, CHECK_ID_INVALID_EXPR), [])
        self.assertEqual(
            _messages_with_id(messages, CHECK_ID_OBSOLETE_CALLBACK_SETTING), []
        )
        self.assertTrue(self.user.has_perm('%s:meta_own' % self.change, self.ticket))
        self.assertIn(
            self.ticket.pk,
            Ticket.objects.permitted(
                '%s:meta_own' % self.change, self.user,
            ).values_list('pk', flat=True),
        )

    def test_valid_custom_builder_proxy_and_cross_app_fk_pass_check(self):
        def register(factory):
            factory.add_named_filter(
                Ticket, 'owned', lambda u, p, o: u == o.owner,
            )
            factory.add_named_filter(
                AutoAdminCategory, 'named', lambda u, p, o: o.name == 'ok',
            )

        catalog = isolated_catalog(register)
        with self.assertNumQueries(0):
            messages = check_permission_conditions(None)
        self.assertEqual(_messages_with_id(messages, CHECK_ID_INVALID_EXPR), [])
        owned = catalog.get_permission_condition_record(Ticket, 'owned')
        self.assertIs(owned.model, Ticket)
        named = catalog.get_permission_condition_record(AutoAdminCategory, 'named')
        self.assertIs(named.model, AutoAdminCategory)

    def test_builder_unresolved_field_fails_at_register(self):
        def register(factory):
            factory.add_named_filter(
                Ticket, 'missing', lambda u, p, o: u == o.not_a_field,
            )

        with self.assertRaises(PermissionConditionError) as ctx:
            isolated_catalog(register)
        self.assertIn('not_a_field', str(ctx.exception))
        self.assertIsNone(
            live_catalog().get_permission_condition_record(Ticket, 'missing')
        )

    def test_register_permission_condition_invokes_the_builder_once(self):
        factory = isolated_compiler()
        factory.add_named_filter(
            Ticket, 'deferred_own', lambda u, p, o: u == o.owner,
        )
        catalog = catalog_from(factory)
        record = catalog.get_permission_condition_record(Ticket, 'deferred_own')
        self.assertIs(record.model, Ticket)
        self.assertIsNotNone(record.expr)
        messages = check_permission_conditions(None)
        self.assertEqual(_messages_with_id(messages, CHECK_ID_INVALID_EXPR), [])

        bad = isolated_compiler()
        with self.assertRaises(PermissionConditionError) as ctx:
            bad.add_named_filter(
                Ticket, 'deferred_bad',
                lambda u, p, o: u == o.deferred_missing,
            )
        self.assertIn('deferred_missing', str(ctx.exception))

    def test_bad_named_filter_fails_at_register(self):
        class ImportTimeBadTicket(Content):
            class Meta:
                app_label = 'trusts_zero_tests'
                managed = False

        try:
            factory = isolated_compiler()
            with self.assertRaises(PermissionConditionError) as ctx:
                factory.add_named_filter(
                    ImportTimeBadTicket, 'bad_a',
                    lambda u, p, o: u == o.missing_a,
                )
            self.assertIn('missing_a', str(ctx.exception))
        finally:
            forget_models(ImportTimeBadTicket)

    def test_incompatible_builder_fails_at_register(self):
        def register(factory):
            factory.add_named_filter(
                Ticket, 'types', lambda u, p, o: o.status == 1,
            )

        with self.assertRaises(PermissionConditionError) as ctx:
            isolated_catalog(register)
        self.assertIn('incompatible', str(ctx.exception))
        self.assertIsNone(live_catalog().get_permission_condition_record(Ticket, 'types'))

    def test_manage_py_check_stays_green_when_invalid_builder_does_not_land(self):
        def register(factory):
            factory.add_named_filter(
                Ticket, 'typo', lambda u, p, o: u == o.nope,
            )

        with self.assertRaises(PermissionConditionError):
            isolated_catalog(register)
        self.assertIsNone(live_catalog().get_permission_condition_record(Ticket, 'typo'))
        output = _run_manage_py_check()
        self.assertNotIn(CHECK_ID_INVALID_EXPR, output)
        self.assertNotIn("'typo'", output)

    def test_manage_py_check_passes_for_valid_registrations(self):
        output = _run_manage_py_check()
        self.assertNotIn(CHECK_ID_INVALID_EXPR, output)
        self.assertNotIn(CHECK_ID_OBSOLETE_CALLBACK_SETTING, output)

    @override_settings(SILENCED_SYSTEM_CHECKS=['trusts.E001', 'trusts.E003', 'fields.W342'])
    def test_silenced_expr_check_does_not_register_invalid_builder(self):
        def register(factory):
            factory.add_named_filter(
                Ticket, 'missing', lambda u, p, o: u == o.not_a_field,
            )

        with self.assertRaises(PermissionConditionError) as ctx:
            isolated_catalog(register)
        self.assertIn('not_a_field', str(ctx.exception))
        self.assertIsNone(live_catalog().get_permission_condition_record(Ticket, 'missing'))
        _run_manage_py_check()
        missing = '%s:missing' % self.change
        with self.assertNumQueries(0):
            self.assertFalse(self.user.has_perm(missing, self.ticket))
        with self.assertRaises(AttributeError):
            list(Ticket.objects.permitted(missing, self.user))
        self.assertTrue(self.user.has_perm(self.change, self.ticket))

    def test_builder_once_and_checks_do_not_reinvoke(self):
        log = _BuilderLog(lambda u, p, o: u == o.owner)

        def register(factory):
            register_relations(factory, Ticket)
            factory.add_named_filter(Ticket, 'spy', log)

        catalog = isolated_catalog(register)
        self.assertEqual(len(log.calls), 1)
        with self.assertNumQueries(0):
            messages = check_permission_conditions(None)
        self.assertEqual(len(log.calls), 1)
        self.assertEqual(
            _messages_with_id(messages, CHECK_ID_OBSOLETE_CALLBACK_SETTING),
            [],
        )
        spy = '%s:spy' % self.change
        self.assertTrue(catalog.has_perm(self.user, spy, self.ticket))
        overlay = catalog.compile_registered_condition_q(Ticket, spy, self.user)
        pks = set(
            catalog.filter_authorized(
                Ticket.objects.all(), self.user, self.perm_change,
            ).filter(overlay).values_list('pk', flat=True)
        )
        self.assertIn(self.ticket.pk, pks)
        self.assertEqual(len(log.calls), 1)
        run_checks()
        self.assertEqual(len(log.calls), 1)

    @override_settings(TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS=True)
    def test_leftover_setting_is_error_and_does_not_reinvoke_builder(self):
        log = _BuilderLog(lambda u, p, o: u == o.owner)

        factory = isolated_compiler()
        factory.add_named_filter(Ticket, 'spy', log)
        catalog_from(factory)
        leftover = check_obsolete_legacy_callback_setting(None)
        self.assertEqual(len(leftover), 1)
        self.assertEqual(leftover[0].id, CHECK_ID_OBSOLETE_CALLBACK_SETTING)
        self.assertTrue(self.user.has_perm('%s:meta_own' % self.change, self.ticket))
        self.assertEqual(len(log.calls), 1)

    def test_boolean_builder_fails_at_build(self):
        exploding = _BuilderLog(lambda u, p, o: (_ for _ in ()).throw(
            AssertionError('callable must not run during checks')
        ))

        def register(factory):
            factory.add_named_filter(Ticket, 'boom', exploding)

        with self.assertRaises(PermissionConditionError) as ctx:
            isolated_catalog(register)
        self.assertIn('AssertionError', str(ctx.exception))
        self.assertEqual(len(exploding.calls), 1)

    def test_ready_does_not_raise_when_invalid_builder_fails_at_build(self):
        def register(factory):
            factory.add_named_filter(
                Ticket, 'typo', lambda u, p, o: u == o.nope,
            )

        with self.assertRaises(PermissionConditionError):
            isolated_catalog(register)
        live_config().ready()
        errors = _messages_with_id(
            check_permission_conditions(None), CHECK_ID_INVALID_EXPR
        )
        self.assertEqual(errors, [])
