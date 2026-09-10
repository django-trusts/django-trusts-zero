"""Issue #3 r2 freezes: missing is_active, PathError façades, AuthorizationDenied alias."""

import inspect

from unittest.mock import patch

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection

from trusts.decorators import request_passes_test as kernel_request_passes_test
from trusts.path import AuthorizationPathError
from trusts.runtime import AuthorizationDenied as KernelAuthorizationDenied
from trusts.zero.authorization import (
    AuthorizationDenied,
    add_group_member,
    associate_group_with_trust,
    can_administer_content,
    can_administer_trust,
    can_manage_group_membership,
    can_read_content,
    create_team,
    disassociate_group_from_trust,
    grant_trust_group_permission,
    grant_trustee,
    has_trust_row_perm,
    refuse_group_permission_write,
    remove_group_member,
    resolve_entity_id,
    revoke_trust_group_permission,
    revoke_trustee,
    set_trust_group_permissions,
)
from trusts.zero.backends import TrustModelBackend
from trusts.zero.decorators import request_passes_test as zero_request_passes_test
from trusts.zero.models import ContentQuerySet, Trust, TrustManager, TrustUserPermission
from trusts.zero.query import (
    require_configured_operation,
    require_configured_requester,
    trust_grant_q,
)
from trusts.zero.views import NewTeamForm, NewTeamView, TeamView


class _ConfiguredRequesterWithoutIsActive(object):
    """Configured AUTH_USER_MODEL instance with no ``is_active`` attribute."""

    def __init__(self, user):
        object.__setattr__(self, '_inner', user)

    def __getattribute__(self, name):
        if name == '_inner':
            return object.__getattribute__(self, name)
        if name == 'is_active':
            raise AttributeError('is_active')
        if name == '__class__':
            return type(object.__getattribute__(self, '_inner'))
        return getattr(object.__getattribute__(self, '_inner'), name)


def _grant_sql(sql):
    compact = ' '.join(sql.lower().split())
    return any(
        token in compact
        for token in (
            'trusts_trustuserpermission',
            'trusts_trustgrouppermission',
            'trusts_trust_groups',
            'trusts_rolepermission',
        )
    )


class Issue3FixtureMixin(object):
    def setUp(self):
        super(Issue3FixtureMixin, self).setUp()
        call_command('create_trust_root')
        self.user = User.objects.create_user('daniel', 'daniel@example.com', 'pass')
        self.other = User.objects.create_user('other', 'other@example.com', 'pass')
        self.root = Trust.objects.get(pk=1)
        self.org = Trust(settlor=self.user, title='Org', trust=self.root)
        self.org.save()
        self.child = Trust(settlor=self.user, title='Child', trust=self.org)
        self.child.save()
        ct = ContentType.objects.get_for_model(Trust)
        self.change = Permission.objects.get(content_type=ct, codename='change_trust')
        self.read = Permission.objects.get(content_type=ct, codename='read_trust')
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=self.change,
        ).save()
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=self.read,
        ).save()
        self.group = Group.objects.create(name='issue3-team')
        self.org.groups.add(self.group)
        self.backend = TrustModelBackend()
        # Freeze registries / warm content types so later 0-SQL asserts are honest.
        list(Trust.objects.permitted('change', self.user))
        self.user.has_perm('trusts.change_trust', self.child)
        has_trust_row_perm(self.user, self.org, 'change')


class MissingIsActiveDenyTests(Issue3FixtureMixin, TestCase):
    def _requester(self):
        user = User.objects.get(pk=self.user.pk)
        wrapped = _ConfiguredRequesterWithoutIsActive(user)
        self.assertFalse(getattr(wrapped, 'is_anonymous', False))
        self.assertIsNot(getattr(wrapped, 'is_authenticated', None), False)
        self.assertFalse(hasattr(wrapped, 'is_active'))
        return wrapped

    def _assert_zero_grant_sql(self, fn):
        with CaptureQueriesContext(connection) as ctx:
            result = fn()
        grant_queries = [q['sql'] for q in ctx.captured_queries if _grant_sql(q['sql'])]
        self.assertEqual(
            grant_queries, [],
            'missing is_active must deny with 0 grant SQL; saw %s' % grant_queries,
        )
        return result

    def test_permitted_denies_with_zero_grant_sql(self):
        requester = self._requester()
        pks = self._assert_zero_grant_sql(
            lambda: list(Trust.objects.permitted('change', requester).values_list('pk', flat=True))
        )
        self.assertEqual(pks, [])

    def test_object_has_perm_denies_with_zero_grant_sql(self):
        requester = self._requester()
        granted = self._assert_zero_grant_sql(
            lambda: self.backend.has_perm(requester, 'trusts.change_trust', self.child)
        )
        self.assertFalse(granted)

    def test_filter_by_user_content_perm_denies_with_zero_grant_sql(self):
        requester = self._requester()
        pks = self._assert_zero_grant_sql(
            lambda: list(
                Trust.objects.filter_by_user_content_perm(
                    requester, Trust, 'change',
                ).values_list('pk', flat=True)
            )
        )
        self.assertEqual(pks, [])

    def test_has_trust_row_perm_denies_with_zero_grant_sql(self):
        requester = self._requester()
        granted = self._assert_zero_grant_sql(
            lambda: has_trust_row_perm(requester, self.org, 'change')
        )
        self.assertFalse(granted)

    def test_can_helpers_deny_with_zero_grant_sql(self):
        requester = self._requester()
        self.assertFalse(self._assert_zero_grant_sql(
            lambda: can_read_content(requester, self.child)
        ))
        self.assertFalse(self._assert_zero_grant_sql(
            lambda: can_administer_content(requester, self.child)
        ))
        self.assertFalse(self._assert_zero_grant_sql(
            lambda: can_administer_trust(requester, self.org)
        ))
        self.assertFalse(self._assert_zero_grant_sql(
            lambda: can_manage_group_membership(requester, self.group)
        ))


class RequireConfiguredFacadeTests(Issue3FixtureMixin, TransactionTestCase):
    reset_sequences = True

    def test_require_configured_requester_rejects_raw_pk(self):
        with self.assertRaises(AuthorizationPathError) as ctx:
            require_configured_requester(self.user.pk)
        self.assertIn('primary key', str(ctx.exception).lower())

    def test_require_configured_requester_rejects_wrong_model(self):
        with self.assertRaises(AuthorizationPathError) as ctx:
            require_configured_requester(self.org)
        self.assertIn('requester', str(ctx.exception))

    def test_require_configured_operation_rejects_user(self):
        with self.assertRaises(AuthorizationPathError) as ctx:
            require_configured_operation(self.user)
        self.assertIn('operation', str(ctx.exception))

    def test_trust_grant_q_rejects_wrong_operation(self):
        with self.assertRaises(AuthorizationPathError):
            trust_grant_q(self.user, self.user)

    def test_permitted_rejects_raw_pk(self):
        with self.assertRaises(AuthorizationPathError):
            Trust.objects.permitted('change', self.user.pk)


class AuthorizationDeniedAliasTests(Issue3FixtureMixin, TestCase):
    def test_zero_import_is_exact_kernel_alias(self):
        self.assertIs(AuthorizationDenied, KernelAuthorizationDenied)
        self.assertTrue(issubclass(AuthorizationDenied, PermissionDenied))

    def test_bool_helpers_stay_bool(self):
        self.assertIs(can_read_content(self.other, self.child), False)
        self.assertIs(can_administer_content(self.other, self.child), False)
        self.assertIs(can_administer_trust(self.other, self.org), False)
        self.assertIs(can_manage_group_membership(self.other, self.group), False)
        self.assertIs(has_trust_row_perm(self.other, self.org, 'change'), False)

    def test_mutations_raise_aliased_class(self):
        surfaces = (
            lambda: grant_trustee(self.other, self.child, self.user, 'change'),
            lambda: revoke_trustee(self.other, self.child, self.user, 'change'),
            lambda: associate_group_with_trust(self.other, self.child, self.group),
            lambda: disassociate_group_from_trust(self.other, self.child, self.group),
            lambda: grant_trust_group_permission(
                self.other, self.child, self.group, 'change',
            ),
            lambda: revoke_trust_group_permission(
                self.other, self.child, self.group, 'change',
            ),
            lambda: set_trust_group_permissions(
                self.other, self.child, self.group, [],
            ),
            lambda: add_group_member(self.other, self.group, self.user),
            lambda: remove_group_member(self.other, self.group, self.user),
            lambda: create_team(self.other, self.org, 'denied-team'),
            lambda: resolve_entity_id(User, 999999),
            lambda: refuse_group_permission_write(),
        )
        for call in surfaces:
            with self.assertRaises(AuthorizationDenied) as ctx:
                call()
            self.assertIs(type(ctx.exception), KernelAuthorizationDenied)
            self.assertIsInstance(ctx.exception, PermissionDenied)

    def test_new_team_view_catches_zero_import(self):
        factory = RequestFactory()
        request = factory.post('/teams/new/', {'name': 'x', 'trust': self.org.pk})
        request.user = self.other
        view = NewTeamView()
        view.request = request
        form = NewTeamForm(user=self.user, data={'name': 'x', 'trust': self.org.pk})
        self.assertTrue(form.is_valid(), form.errors)
        response = view.form_valid(form)
        self.assertEqual(response.status_code, 403)

    def test_team_view_post_catches_zero_import(self):
        factory = RequestFactory()
        request = factory.post(
            '/teams/%s/' % self.group.pk, {'user': self.other.pk},
        )
        request.user = self.user
        with patch(
            'trusts.zero.views.add_group_member',
            side_effect=AuthorizationDenied('denied'),
        ):
            response = TeamView.as_view()(request, pk=self.group.pk)
        self.assertEqual(response.status_code, 403)


class KernelConsumptionSourceTests(TestCase):
    def test_permitted_uses_filter_authorized(self):
        source = inspect.getsource(ContentQuerySet.permitted)
        self.assertIn('filter_authorized', source)
        self.assertNotIn('trust_grant_q', source)
        self.assertNotIn('compose_zero_path', source)
        self.assertNotIn('path.grant_q', source)
        self.assertNotIn('path.filter_granted', source)

    def test_filter_by_user_content_perm_uses_scope_origin(self):
        source = inspect.getsource(TrustManager.filter_by_user_content_perm)
        self.assertIn('filter_authorized_scope', source)
        self.assertNotIn('trust_grant_q', source)

    def test_has_trust_row_perm_uses_is_scope_authorized(self):
        source = inspect.getsource(has_trust_row_perm)
        self.assertIn('is_scope_authorized', source)
        self.assertNotIn('trust_grant_q', source)

    def test_query_module_has_no_local_path_rewalk(self):
        import trusts.zero.query as query_mod
        source = inspect.getsource(query_mod)
        self.assertIn('filter_authorized', source)
        self.assertIn('is_authorized', source)
        self.assertIn('authorized_scope_q', source)
        self.assertNotIn('path.filter_granted', source)
        self.assertNotIn('path.row_is_granted', source)
        self.assertNotIn('Trustee.grant_q', source)

    def test_request_passes_test_is_kernel(self):
        self.assertIs(zero_request_passes_test, kernel_request_passes_test)

    def test_authorization_denied_alias_in_module(self):
        import trusts.zero.authorization as auth_mod
        self.assertIs(auth_mod.AuthorizationDenied, KernelAuthorizationDenied)
