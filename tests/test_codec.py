"""Zero codec, registration, manager, and condition compatibility on C1 APIs."""

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase

from trusts.apps import kernel_config
from trusts.core import TrustsConfigurationError, TrustsRegistry
from trusts.query import AuthorizedQuerySet
from trusts.zero.models import (
    ContentConditionLookup,
    ContentQuerySet,
    PermissionConditionNotQueryable,
    Trust,
    TrustGroupPermission,
    TrustUserPermission,
    django_permission_filter,
    register_zero_direct,
    register_zero_group,
)
from tests.models import Category, Ticket


class RegistrationAndCodecTests(TestCase):
    def setUp(self):
        call_command('create_trust_root')
        self.user = User.objects.create_user('daniel', 'daniel@example.com', 'pass')
        self.other = User.objects.create_user('other', 'other@example.com', 'pass')
        self.root = Trust.objects.get(pk=1)
        self.org = Trust(settlor=self.user, title='Org', trust=self.root)
        self.org.save()
        self.child = Trust(settlor=self.user, title='Child', trust=self.org)
        self.child.save()
        self.isolated = Trust(settlor=self.other, title='OtherOrg', trust=self.root)
        self.isolated.save()
        ct = ContentType.objects.get_for_model(Trust)
        self.change = Permission.objects.get(content_type=ct, codename='change_trust')
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=self.change,
        ).save()

    def test_content_queryset_is_authorized_queryset_subclass(self):
        import inspect
        self.assertTrue(issubclass(ContentQuerySet, AuthorizedQuerySet))
        src = inspect.getsource(ContentQuerySet.permitted)
        self.assertIn('return django_permission_filter(', src)

    def test_tup_register_on_isolated_registry(self):
        registry = TrustsRegistry()
        register_zero_direct(registry, (Trust,))
        records = registry.records_for_root(TrustUserPermission)
        self.assertEqual(len(records), 1)
        self.assertIs(records[0].content_model, Trust)
        self.assertEqual(records[0].user_field, 'entity')

    def test_tgp_register_uses_only_c1_public_grammar(self):
        registry = TrustsRegistry()
        try:
            register_zero_group(registry, (Trust,))
        except TrustsConfigurationError:
            self.assertEqual(registry.records, ())
            return
        records = registry.records_for_root(TrustGroupPermission)
        self.assertTrue(records)
        self.assertIs(records[0].content_model, Trust)

    def test_live_registry_has_tup_trust_and_bound_condition_lookup(self):
        handle = kernel_config().configured_backend()
        records = handle.registry.records_for_root(TrustUserPermission)
        content_models = {row.content_model for row in records}
        self.assertIn(Trust, content_models)
        self.assertIn(Category, content_models)
        self.assertIn(Ticket, content_models)
        lookup = handle.registry.condition_lookup
        self.assertIsInstance(lookup, ContentConditionLookup)
        own = lookup.record_for(Trust, 'own')
        self.assertIsNotNone(own)
        self.assertIsNotNone(own.expr)

    def test_permitted_and_has_perm_trustee_isolation(self):
        user = User.objects.get(pk=self.user.pk)
        other = User.objects.get(pk=self.other.pk)
        child = Trust.objects.get(pk=self.child.pk)
        isolated = Trust.objects.get(pk=self.isolated.pk)

        self.assertTrue(user.has_perm('trusts.change_trust', child))
        self.assertFalse(user.has_perm('trusts.change_trust', isolated))
        self.assertFalse(other.has_perm('trusts.change_trust', child))
        permitted = list(Trust.objects.permitted('change', user))
        self.assertIn(child, permitted)
        self.assertNotIn(isolated, permitted)

    def test_inactive_and_anonymous_are_empty(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(list(Trust.objects.permitted('change', self.user)), [])
        class Anon(object):
            is_anonymous = True
            is_authenticated = False
            is_active = False
        self.assertEqual(list(Trust.objects.permitted('change', Anon())), [])

    def test_get_permission_and_manager_surfaces(self):
        perm = Trust.objects.get_permission('change')
        self.assertEqual(perm.codename, 'change_trust')
        self.assertEqual(Trust.objects.get_root().pk, 1)
        trusts = Trust.objects.filter_by_user_perm(self.user)
        self.assertIn(self.org, trusts)
        self.assertNotIn(self.isolated, trusts)

    def test_filter_by_user_content_perm_trustee_and_fail_closed(self):
        qs = Trust.objects.filter_by_user_content_perm(
            self.user, Trust, 'change',
        )
        self.assertIn(self.org, qs)
        self.assertNotIn(self.root, qs)
        self.assertNotIn(self.isolated, qs)
        empty = Trust.objects.filter_by_user_content_perm(
            self.user, Category, 'add',
        )
        # Category is declared; user has no add grant.
        self.assertEqual(list(empty), [])

    def test_filter_by_user_content_perm_rejects_condition(self):
        with self.assertRaises(PermissionConditionNotQueryable):
            Trust.objects.filter_by_user_content_perm(
                self.user, Trust, 'change:own',
            )

    def test_trust_own_condition_compiles_on_permitted(self):
        # Trust-as-content is the parent hop: a TUP on org authorizes child
        # Trust rows, not the org identity row.
        permitted = list(Trust.objects.permitted('change:own', self.user))
        self.assertIn(self.child, permitted)
        self.assertNotIn(self.isolated, permitted)

    def test_ticket_own_condition_and_unregistered_code(self):
        ticket = Ticket(title='t', owner=self.user, trust=self.org)
        ticket.save()
        other_ticket = Ticket(title='o', owner=self.other, trust=self.org)
        other_ticket.save()
        read = Ticket.objects.get_permission('read')
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=read,
        ).save()
        permitted = list(Ticket.objects.permitted('read:own', self.user))
        self.assertIn(ticket, permitted)
        self.assertNotIn(other_ticket, permitted)
        with self.assertRaises(AttributeError):
            list(Ticket.objects.permitted('read:nope', self.user))

    def test_callable_condition_raises_before_sql(self):
        def never_called(user, perm, obj):
            raise AssertionError('callable must not run')
        ContentQuerySet  # keep import used
        from trusts.zero.models import Content
        Content.register_permission_condition(Category, 'cb', never_called)
        cat = Category(name='n', trust=self.org)
        cat.save()
        with self.assertRaises(PermissionConditionNotQueryable):
            list(Category.objects.permitted('read:cb', self.user))

    def test_group_local_grant_still_authorizes_via_c1_compiler(self):
        group = Group.objects.create(name='writers')
        group.user_set.add(self.user)
        group.permissions.add(self.change)
        other_child = Trust(settlor=self.other, title='GChild', trust=self.isolated)
        other_child.save()
        self.isolated.grant_group_permission(group, self.change)
        user = User.objects.get(pk=self.user.pk)
        self.assertTrue(user.has_perm('trusts.change_trust', other_child))
        permitted = list(Trust.objects.permitted('change', user))
        self.assertIn(other_child, permitted)

    def test_django_permission_filter_is_the_codec(self):
        qs = Trust.objects.all()
        filtered = django_permission_filter(qs, 'change', self.user)
        self.assertIn(self.child, list(filtered))
