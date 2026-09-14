"""Zero-owned legacy request decorator family (Core #191 Zero leg).

Exercises the public ``trusts.zero.decorators`` surface through the
decorator and request/view entry path. Does not create private-helper
contracts.
"""

from pathlib import Path
from unittest.mock import Mock

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.http import Http404, HttpRequest, HttpResponse
from django.test import SimpleTestCase, TestCase

from trusts.zero.decorators import G, K, O, P, R, permission_required
from trusts.zero.models import Trust, TrustUserPermission
from tests.legacy.helpers import create_test_users, get_or_create_root_user
from tests.models import Category


ROOT = Path(__file__).resolve().parents[1]


def _request(user, get=None, post=None):
    request = HttpRequest()
    request.user = user
    request.method = 'POST' if post is not None else 'GET'
    request.GET = get or {}
    request.POST = post or {}
    request.META['SERVER_NAME'] = 'beedesk.com'
    request.META['SERVER_PORT'] = 80
    return request


def _ok_view(request, *args, **kwargs):
    return HttpResponse('ok')


class LegacyDecoratorPublicSurfaceTests(SimpleTestCase):
    def test_public_import_surface(self):
        from trusts.zero.decorators import G, K, O, P, R, permission_required

        self.assertTrue(issubclass(K, R))
        self.assertTrue(issubclass(G, R))
        self.assertTrue(issubclass(O, R))
        self.assertIs(R, R)
        self.assertTrue(callable(permission_required))
        self.assertEqual(K('pk').key, 'pk')
        self.assertEqual(G('q').key, 'q')
        self.assertEqual(O('body').key, 'body')

    def test_p_leaf_and_composed_representations(self):
        leaf = P('auth.change_group', pk=K('pk'))
        self.assertEqual(str(leaf), 'auth.change_group')
        self.assertEqual(repr(leaf), 'auth.change_group')
        composed = leaf & P('auth.delete_group', pk=K('pk'))
        self.assertEqual(str(composed), 'P object')
        self.assertEqual(repr(composed), 'P object')
        self.assertEqual(str(leaf | P('auth.add_group')), 'P object')

    def test_p_type_errors_for_and_or(self):
        leaf = P('auth.change_group')
        with self.assertRaises(TypeError) as and_exc:
            leaf & 'auth.delete_group'
        self.assertIn('unsupported operand type(s) for &', str(and_exc.exception))
        with self.assertRaises(TypeError) as or_exc:
            leaf | 1
        self.assertIn('unsupported operand type(s) for |', str(or_exc.exception))

    def test_docs_name_zero_import_not_core_legacy_home(self):
        rst = (ROOT / 'docs' / 'source' / 'index.rst').read_text()
        readme = (ROOT / 'README.md').read_text()
        migrates = (ROOT / 'migrates.md').read_text()
        self.assertIn(
            'from trusts.zero.decorators import P, R, K, G, O, permission_required',
            rst,
        )
        self.assertNotIn('View decorators remain core APIs', rst)
        self.assertIn('trusts.zero.decorators', readme)
        self.assertIn(
            'from trusts.decorators import P, R, K, G, O, permission_required',
            migrates,
        )
        self.assertIn(
            'from trusts.zero.decorators import P, R, K, G, O, permission_required',
            migrates,
        )
        offenders = []
        scanned = list((ROOT / 'trusts' / 'zero').rglob('*.py')) + list(
            (ROOT / 'tests').rglob('*.py')
        )
        for path in scanned:
            for line in path.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith('#'):
                    continue
                if stripped.startswith('from trusts.decorators import') or (
                    stripped == 'import trusts.decorators'
                ):
                    offenders.append(
                        '%s: %s' % (path.relative_to(ROOT), stripped)
                    )
        self.assertEqual(offenders, [])


class LegacyDecoratorRequestTests(TestCase):
    def setUp(self):
        call_command('create_trust_root')
        get_or_create_root_user(self)
        create_test_users(self)
        self.group = Group.objects.create(name='Decorator Group')

    def test_allow_dispatches_legacy_string_and_queryset(self):
        has_perms = Mock(return_value=True)
        self.user.has_perms = has_perms
        request = _request(self.user)
        response = permission_required(
            'auth.change_group',
            fieldlookups_kwargs={'pk': 'pk'},
        )(_ok_view)(request, pk=self.group.pk)
        self.assertEqual(response.content, b'ok')
        self.assertEqual(has_perms.call_args[0][0], ('auth.change_group',))
        items = has_perms.call_args[0][1]
        self.assertEqual(items.count(), 1)
        self.assertEqual(items.first().pk, self.group.pk)

    def test_legacy_condition_string_reaches_has_perms(self):
        has_perms = Mock(return_value=True)
        self.user.has_perms = has_perms
        root = Trust.objects.get_root()
        request = _request(self.user)
        response = permission_required(
            'trusts.change_trust:own',
            fieldlookups_kwargs={'pk': 'pk'},
        )(_ok_view)(request, pk=root.pk)
        self.assertEqual(response.content, b'ok')
        self.assertEqual(has_perms.call_args[0][0], ('trusts.change_trust:own',))
        items = has_perms.call_args[0][1]
        self.assertEqual(list(items), [root])

    def test_raise_exception_denied_is_permission_denied(self):
        self.user.has_perms = Mock(return_value=False)
        request = _request(self.user)
        with self.assertRaises(PermissionDenied):
            permission_required(
                'auth.change_group',
                fieldlookups_kwargs={'pk': 'pk'},
            )(_ok_view)(request, pk=self.group.pk)

    def test_no_lookups_raise_exception_is_404(self):
        request = _request(self.user)
        with self.assertRaises(Http404):
            permission_required('auth.change_group')(_ok_view)(request)

    def test_no_lookups_without_exception_redirects_to_login(self):
        request = _request(self.user)
        response = permission_required(
            'auth.change_group',
            raise_exception=False,
        )(_ok_view)(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)
        self.assertIn('next=', response.url)

    def test_custom_login_url_on_deny(self):
        self.user.has_perms = Mock(return_value=False)
        request = _request(self.user)
        response = permission_required(
            'auth.change_group',
            fieldlookups_kwargs={'pk': 'pk'},
            raise_exception=False,
            login_url='/custom-login/',
        )(_ok_view)(request, pk=self.group.pk)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/custom-login/', response.url)

    def test_missing_k_g_o_values_are_none_in_queryset(self):
        has_perms = Mock(return_value=False)
        self.user.has_perms = has_perms
        request = _request(self.user)
        permission_required(
            P('auth.change_group', pk=K('pk')),
            raise_exception=False,
        )(_ok_view)(request)
        items = has_perms.call_args[0][1]
        self.assertEqual(list(items), [])

        has_perms.reset_mock()
        request = _request(self.user, get={})
        permission_required(
            P('auth.change_group', pk=G('gid')),
            raise_exception=False,
        )(_ok_view)(request)
        self.assertEqual(list(has_perms.call_args[0][1]), [])

        has_perms.reset_mock()
        request = _request(self.user, post={})
        permission_required(
            P('auth.change_group', pk=O('gid')),
            raise_exception=False,
        )(_ok_view)(request)
        self.assertEqual(list(has_perms.call_args[0][1]), [])

        has_perms.reset_mock()
        request = _request(self.user)
        permission_required(
            'auth.change_group',
            fieldlookups_kwargs={'pk': 'pk'},
            raise_exception=False,
        )(_ok_view)(request)
        self.assertEqual(list(has_perms.call_args[0][1]), [])

        has_perms.reset_mock()
        request = _request(self.user, get={})
        permission_required(
            'auth.change_group',
            fieldlookups_getparams={'pk': 'gid'},
            raise_exception=False,
        )(_ok_view)(request)
        self.assertEqual(list(has_perms.call_args[0][1]), [])

        has_perms.reset_mock()
        request = _request(self.user, post={})
        permission_required(
            'auth.change_group',
            fieldlookups_postparams={'pk': 'gid'},
            raise_exception=False,
        )(_ok_view)(request)
        self.assertEqual(list(has_perms.call_args[0][1]), [])

    def test_k_g_o_extract_present_values(self):
        has_perms = Mock(return_value=True)
        self.user.has_perms = has_perms

        request = _request(self.user)
        permission_required(
            P('auth.change_group', pk=K('pk')),
        )(_ok_view)(request, pk=self.group.pk)
        self.assertEqual(has_perms.call_args[0][1].first().pk, self.group.pk)

        request = _request(self.user, get={'gid': str(self.group.pk)})
        permission_required(
            P('auth.change_group', pk=G('gid')),
        )(_ok_view)(request)
        self.assertEqual(has_perms.call_args[0][1].first().pk, self.group.pk)

        request = _request(self.user, post={'gid': str(self.group.pk)})
        permission_required(
            P('auth.change_group', pk=O('gid')),
        )(_ok_view)(request)
        self.assertEqual(has_perms.call_args[0][1].first().pk, self.group.pk)

    def test_p_and_or_short_circuit_order(self):
        calls = []

        def has_perms(perms, items):
            calls.append(perms[0])
            return perms[0] == 'auth.change_group'

        self.user.has_perms = has_perms
        request = _request(self.user)
        allow = P('auth.change_group', fieldlookups_kwargs={'pk': 'pk'})
        deny = P('auth.delete_group', fieldlookups_kwargs={'pk': 'pk'})

        calls.clear()
        permission_required(allow | deny, raise_exception=False)(_ok_view)(
            request, pk=self.group.pk,
        )
        self.assertEqual(calls, ['auth.change_group'])

        calls.clear()
        permission_required(deny | allow, raise_exception=False)(_ok_view)(
            request, pk=self.group.pk,
        )
        self.assertEqual(calls, ['auth.delete_group', 'auth.change_group'])

        calls.clear()
        permission_required(deny & allow, raise_exception=False)(_ok_view)(
            request, pk=self.group.pk,
        )
        self.assertEqual(calls, ['auth.delete_group'])

        calls.clear()
        permission_required(allow & deny, raise_exception=False)(_ok_view)(
            request, pk=self.group.pk,
        )
        self.assertEqual(calls, ['auth.change_group', 'auth.delete_group'])

    def test_real_has_perm_grant_through_decorator(self):
        root = Trust.objects.get_root()
        org = Trust(settlor=self.user, title='Decorator Org', trust=root)
        org.save()
        category = Category(trust=org, name='Decorator Cat')
        category.save()
        change = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Category),
            codename='change_category',
        )
        TrustUserPermission.objects.create(
            trust=org, entity=self.user, permission=change,
        )
        user = User._default_manager.get(pk=self.user.pk)
        request = _request(user)
        response = permission_required(
            'trusts_zero_tests.change_category',
            fieldlookups_kwargs={'pk': 'pk'},
        )(_ok_view)(request, pk=category.pk)
        self.assertEqual(response.content, b'ok')

        other = User._default_manager.get(pk=self.user1.pk)
        request = _request(other)
        with self.assertRaises(PermissionDenied):
            permission_required(
                'trusts_zero_tests.change_category',
                fieldlookups_kwargs={'pk': 'pk'},
            )(_ok_view)(request, pk=category.pk)
