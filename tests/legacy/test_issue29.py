"""Copied from django-trusts@948d6666342377b9472debb57d4a1e26e81402d1 ``trusts/test_issue29.py`` for issue #37 Zero-first coverage.

Final-state adaptations: Zero test app label, core registry APIs, no Content._conditions.
"""

"""Early validation of permission conditions via Django system checks (#29).

Follow-up to #28. Does not close #4. Construction-time operator errors stay
exceptions; model-aware semantic failures are ``CheckMessage``s with
stable IDs. Callables are registration-time builders.
"""

from io import StringIO
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.checks import run_checks
from django.core.management import call_command
from django.test import TestCase, override_settings

from trusts.checks import (
    CHECK_ID_INVALID_EXPR,
    CHECK_ID_OBSOLETE_CALLBACK_SETTING,
    check_obsolete_legacy_callback_setting,
    check_permission_conditions,
)
from trusts.conditions import (
    PermissionConditionError,
    validate_expression,
)
from trusts.core import TrustsRegistry
from trusts.zero.models import (
    Content,
    Trust,
    TrustUserPermission,
)
from trusts.zero.registration import donate_content_permission_conditions
from tests.legacy.test_issue4 import _BuilderLog
from tests.legacy.helpers import (
    create_test_users,
    get_or_create_root_user,
    reload_test_users,
)
from tests.apps import (
    live_registry,
    forget_models,
    live_config,
    publish_permission_condition,
)
from tests.models import AutoAdminCategory, Ticket


# Snapshot taken at import, after app loading / class_prepared, before tests
# mutate the registry. Used so check tests do not depend on test order.
_IMPORT_CONDITIONS = dict(live_registry().conditions._records)


def _restore_conditions(snapshot):
    live_registry().conditions._records.clear()
    live_registry().conditions._records.update(snapshot)


def _messages_with_id(messages, check_id):
    return [m for m in messages if m.id == check_id]


def _run_manage_py_check():
    out = StringIO()
    err = StringIO()
    call_command('check', stdout=out, stderr=err)
    return out.getvalue() + err.getvalue()


class ConditionRegistryIsolationMixin(object):
    def setUp(self):
        super(ConditionRegistryIsolationMixin, self).setUp()
        _restore_conditions(_IMPORT_CONDITIONS)

    def tearDown(self):
        _restore_conditions(_IMPORT_CONDITIONS)
        super(ConditionRegistryIsolationMixin, self).tearDown()


class PermissionConditionCheckTest(ConditionRegistryIsolationMixin, TestCase):
    """System-check diagnostics. Runtime fail-closed is covered with a grant."""

    def setUp(self):
        super(PermissionConditionCheckTest, self).setUp()
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
        from tests.models import Organization
        return Organization.objects.create(name='CheckCo', manager=self.user)

    def test_import_time_meta_and_builtin_own_are_valid(self):
        own = live_registry().get_permission_condition_record(Trust, 'own')
        self.assertIsNotNone(own)
        self.assertIs(own.model, Trust)
        validate_expression(own.expr, Trust)

        meta_own = live_registry().get_permission_condition_record(Ticket, 'meta_own')
        self.assertIsNotNone(meta_own)
        self.assertIs(meta_own.model, Ticket)
        validate_expression(meta_own.expr, Ticket)

        messages = check_permission_conditions(None)
        self.assertEqual(_messages_with_id(messages, CHECK_ID_INVALID_EXPR), [])
        self.assertEqual(_messages_with_id(messages, CHECK_ID_OBSOLETE_CALLBACK_SETTING), [])
        self.assertTrue(self.user.has_perm('%s:meta_own' % self.change, self.ticket))
        self.assertIn(
            self.ticket.pk,
            Ticket.objects.permitted('%s:meta_own' % self.change, self.user).values_list(
                'pk', flat=True
            ),
        )

    def test_valid_custom_builder_proxy_and_cross_app_fk_pass_check(self):
        publish_permission_condition(Ticket, 'owned', lambda u, p, o: u == o.owner)
        publish_permission_condition(
            AutoAdminCategory, 'named', lambda u, p, o: o.name == 'ok',
        )
        with self.assertNumQueries(0):
            messages = check_permission_conditions(None)
        self.assertEqual(_messages_with_id(messages, CHECK_ID_INVALID_EXPR), [])
        owned = live_registry().get_permission_condition_record(Ticket, 'owned')
        self.assertIs(owned.model, Ticket)
        named = live_registry().get_permission_condition_record(AutoAdminCategory, 'named')
        self.assertIs(named.model, AutoAdminCategory)

    def test_builder_unresolved_field_fails_at_register(self):
        isolated = TrustsRegistry()
        with self.assertRaises(PermissionConditionError) as ctx:
            isolated.register_permission_condition(
                Ticket, 'missing', lambda u, p, o: u == o.not_a_field,
            )
        self.assertIn('not_a_field', str(ctx.exception))
        self.assertIsNone(isolated.get_permission_condition_record(Ticket, 'missing'))

    def test_registration_before_models_ready_retains_identity(self):
        with patch.object(apps, 'models_ready', False):
            record = publish_permission_condition(
                Ticket, 'deferred_own', lambda u, p, o: u == o.owner,
            )
        self.assertIs(record.model, Ticket)
        self.assertIsNotNone(record.expr)
        messages = check_permission_conditions(None)
        self.assertEqual(_messages_with_id(messages, CHECK_ID_INVALID_EXPR), [])

        isolated = TrustsRegistry()
        with patch.object(apps, 'models_ready', False):
            with self.assertRaises(PermissionConditionError) as ctx:
                isolated.register_permission_condition(
                    Ticket, 'deferred_bad',
                    lambda u, p, o: u == o.deferred_missing,
                )
        self.assertIn('deferred_missing', str(ctx.exception))
        self.assertIsNone(
            isolated.get_permission_condition_record(Ticket, 'deferred_bad')
        )

    def test_meta_permission_conditions_fail_at_donate(self):
        class ImportTimeBadTicket(Content):
            class Meta:
                app_label = 'trusts_zero_tests'
                managed = False
                permission_conditions = (
                    ('bad_a', lambda u, p, o: u == o.missing_a),
                    ('bad_b', lambda u, p, o: o.trust == 1),
                )

        isolated = TrustsRegistry()
        with self.assertRaises(PermissionConditionError) as ctx:
            donate_content_permission_conditions(isolated, ImportTimeBadTicket)
        self.assertIn('missing_a', str(ctx.exception))
        self.assertIsNone(
            isolated.get_permission_condition_record(ImportTimeBadTicket, 'bad_a')
        )
        self.assertIsNone(
            isolated.get_permission_condition_record(ImportTimeBadTicket, 'bad_b')
        )
        forget_models(ImportTimeBadTicket)

    def test_incompatible_builder_fails_at_register(self):
        isolated = TrustsRegistry()
        with self.assertRaises(PermissionConditionError) as ctx:
            isolated.register_permission_condition(
                Ticket, 'types', lambda u, p, o: o.status == 1,
            )
        self.assertIn('incompatible', str(ctx.exception))
        self.assertIsNone(isolated.get_permission_condition_record(Ticket, 'types'))

    def test_manage_py_check_stays_green_when_invalid_builder_does_not_land(self):
        isolated = TrustsRegistry()
        with self.assertRaises(PermissionConditionError):
            isolated.register_permission_condition(
                Ticket, 'typo', lambda u, p, o: u == o.nope,
            )
        self.assertIsNone(isolated.get_permission_condition_record(Ticket, 'typo'))
        self.assertIsNone(live_registry().get_permission_condition_record(Ticket, 'typo'))
        output = _run_manage_py_check()
        self.assertNotIn(CHECK_ID_INVALID_EXPR, output)
        self.assertNotIn("'typo'", output)

    def test_manage_py_check_passes_for_valid_registrations(self):
        output = _run_manage_py_check()
        self.assertNotIn(CHECK_ID_INVALID_EXPR, output)
        self.assertNotIn(CHECK_ID_OBSOLETE_CALLBACK_SETTING, output)

    @override_settings(SILENCED_SYSTEM_CHECKS=['trusts.E001', 'trusts.E003', 'fields.W342'])
    def test_silenced_expr_check_does_not_register_invalid_builder(self):
        isolated = TrustsRegistry()
        with self.assertRaises(PermissionConditionError) as ctx:
            isolated.register_permission_condition(
                Ticket, 'missing', lambda u, p, o: u == o.not_a_field,
            )
        self.assertIn('not_a_field', str(ctx.exception))
        self.assertIsNone(isolated.get_permission_condition_record(Ticket, 'missing'))
        self.assertIsNone(
            live_registry().get_permission_condition_record(Ticket, 'missing')
        )
        _run_manage_py_check()
        missing = '%s:missing' % self.change
        with self.assertRaises(AttributeError):
            self.user.has_perm(missing, self.ticket)
        with self.assertRaises(AttributeError):
            list(Ticket.objects.permitted(missing, self.user))
        self.assertTrue(self.user.has_perm(self.change, self.ticket))

    def test_builder_once_and_checks_do_not_reinvoke(self):
        log = _BuilderLog(lambda u, p, o: u == o.owner)
        publish_permission_condition(Ticket, 'spy', log)
        self.assertEqual(len(log.calls), 1)
        with self.assertNumQueries(0):
            messages = check_permission_conditions(None)
        self.assertEqual(len(log.calls), 1)
        self.assertEqual(
            _messages_with_id(messages, CHECK_ID_OBSOLETE_CALLBACK_SETTING),
            [],
        )
        spy = '%s:spy' % self.change
        self.assertTrue(self.user.has_perm(spy, self.ticket))
        self.assertIn(
            self.ticket.pk,
            Ticket.objects.permitted(spy, self.user).values_list('pk', flat=True),
        )
        self.assertEqual(len(log.calls), 1)
        run_checks()
        self.assertEqual(len(log.calls), 1)

    @override_settings(TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS=True)
    def test_leftover_setting_is_error_and_does_not_reinvoke_builder(self):
        log = _BuilderLog(lambda u, p, o: u == o.owner)
        publish_permission_condition(Ticket, 'spy', log)
        leftover = check_obsolete_legacy_callback_setting(None)
        self.assertEqual(len(leftover), 1)
        self.assertEqual(leftover[0].id, CHECK_ID_OBSOLETE_CALLBACK_SETTING)
        self.assertTrue(self.user.has_perm('%s:spy' % self.change, self.ticket))
        self.assertEqual(len(log.calls), 1)

    def test_boolean_builder_fails_at_register(self):
        isolated = TrustsRegistry()
        exploding = _BuilderLog(lambda u, p, o: (_ for _ in ()).throw(
            AssertionError('callable must not run during checks')
        ))
        with self.assertRaises(PermissionConditionError) as ctx:
            isolated.register_permission_condition(Ticket, 'boom', exploding)
        self.assertIn('AssertionError', str(ctx.exception))
        self.assertEqual(len(exploding.calls), 1)
        self.assertIsNone(isolated.get_permission_condition_record(Ticket, 'boom'))

    def test_ready_does_not_raise_when_invalid_builder_fails_at_register(self):
        isolated = TrustsRegistry()
        with self.assertRaises(PermissionConditionError):
            isolated.register_permission_condition(
                Ticket, 'typo', lambda u, p, o: u == o.nope,
            )
        live_config().ready()
        errors = _messages_with_id(
            check_permission_conditions(None), CHECK_ID_INVALID_EXPR
        )
        self.assertEqual(errors, [])
