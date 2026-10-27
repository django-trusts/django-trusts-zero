"""Named filters and live terminal parity (issue #87).

Live ``has_perm`` covers Category, Ticket, Trust, and Group. Dependent
image rows are on the test app's policy document.
"""

from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.checks import run_checks
from django.core.management import call_command
from django.test import TestCase

from tests.apps import (
    TEST_BACKEND, ZERO_BACKEND, content_row, named_filter_ids, trust_rows,
)
from tests.legacy.helpers import enable_local_group_grant, get_or_create_root_user
from tests.models import (
    Category, Organization, OrphanDoc, Receipt, ReceiptImage,
    ReceiptImageMeta, TestGroupJunction, Ticket,
)
from trusts.decorators import filter_by_permitted_content
from trusts.models import PermittedUsersMixin
from trusts.zero.backends import TrustModelBackend
from trusts.zero.models import Trust, TrustUserPermission


def _perm(model, codename):
    ct, _created = ContentType.objects.get_or_create(
        app_label=model._meta.app_label,
        model=model._meta.model_name,
    )
    permission, _created = Permission.objects.get_or_create(
        content_type=ct,
        codename=codename,
        defaults={'name': codename},
    )
    return permission


class LiveConditionTest(TestCase):
    def test_trust_own_and_ticket_meta_own_remain(self):
        self.assertIn('trusts__Trust__own', named_filter_ids(Trust, ZERO_BACKEND))
        self.assertIn(
            'trusts_zero_tests__Ticket__meta_own',
            named_filter_ids(Ticket, TEST_BACKEND),
        )
        messages = run_checks()
        self.assertEqual(
            [message for message in messages if message.id == 'trusts.E001'],
            [],
        )


class _UsersMixin(object):
    def _make_users(self, suffix):
        get_or_create_root_user(self)
        call_command('create_trust_root')
        self.alice = User.objects.create_user(
            'alice-%s' % suffix, 'alice-%s@example.com' % suffix, 'x',
        )
        self.bob = User.objects.create_user(
            'bob-%s' % suffix, 'bob-%s@example.com' % suffix, 'x',
        )
        self.carol = User.objects.create_user(
            'carol-%s' % suffix, 'carol-%s@example.com' % suffix, 'x',
        )
        for user in (self.alice, self.bob, self.carol):
            user.is_active = True
            user.save()
        root = Trust.objects.get_root()
        self.trust_a = Trust(settlor=self.alice, trust=root, title='S7 A %s' % suffix)
        self.trust_a.save()
        self.trust_b = Trust(settlor=self.alice, trust=root, title='S7 B %s' % suffix)
        self.trust_b.save()

    def _reload(self):
        self.alice = User.objects.get(pk=self.alice.pk)
        self.bob = User.objects.get(pk=self.bob.pk)
        self.carol = User.objects.get(pk=self.carol.pk)


class LiveTerminalParityTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('parity')
        self.cat = Category.objects.create(trust=self.trust_a, name='s7-cat')
        self.change_cat = _perm(Category, 'change_category')
        self.cat_code = 'trusts_zero_tests.change_category'
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change_cat,
        ).save()
        self.carol_group = Group.objects.create(name='carol-s7-parity')
        self.carol.groups.add(self.carol_group)
        self.change_cat.group_set.add(self.carol_group)
        enable_local_group_grant(self.trust_a, self.carol_group, self.change_cat)
        self.group = Group.objects.create(name='s7-protected')
        TestGroupJunction.objects.create(
            trust=self.trust_a, content=self.group, name='s7-j',
        )
        self.change_group = _perm(Group, 'change_group')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.change_group,
        ).save()
        self._reload()

    def test_category_ticket_trust_group_allow_deny(self):
        self.assertTrue(self.alice.has_perm(self.cat_code, self.cat))
        self.assertTrue(self.carol.has_perm(self.cat_code, self.cat))
        self.assertFalse(self.bob.has_perm(self.cat_code, self.cat))
        backend = TrustModelBackend()
        self.assertFalse(backend.has_perm(self.alice, self.cat_code))
        qs = Category.objects.filter(pk=self.cat.pk)
        self.assertTrue(self.alice.has_perm(self.cat_code, qs))
        self.assertIn(self.cat_code, self.alice.get_all_permissions(self.cat))
        self.assertNotIn(self.cat_code, self.alice.get_group_permissions(self.cat))
        self.assertIn(self.cat_code, self.carol.get_group_permissions(self.cat))
        self.assertTrue(self.alice.has_perm('auth.change_group', self.group))
        child = Trust(settlor=self.alice, trust=self.trust_a, title='s7-child')
        child.save()
        change_trust = _perm(Trust, 'change_trust')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=change_trust,
        ).save()
        org = Organization.objects.create(name='s7-org', manager=self.alice)
        ticket = Ticket.objects.create(
            trust=self.trust_a, title='s7-t', owner=self.alice,
            organization=org, status='open',
        )
        ticket_change = _perm(Ticket, 'change_ticket')
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=ticket_change,
        ).save()
        self._reload()
        self.assertTrue(self.alice.has_perm('trusts.change_trust', child))
        self.assertTrue(self.alice.has_perm('trusts.change_trust:own', child))
        self.assertFalse(self.bob.has_perm('trusts.change_trust', child))
        self.assertTrue(self.alice.has_perm('trusts_zero_tests.change_ticket', ticket))
        self.assertTrue(
            self.alice.has_perm('trusts_zero_tests.change_ticket:meta_own', ticket)
        )
        self.assertFalse(self.bob.has_perm('trusts_zero_tests.change_ticket', ticket))
        self.alice.is_active = False
        self.alice.save()
        self._reload()
        self.assertFalse(self.alice.has_perm(self.cat_code, self.cat))
        self.assertFalse(AnonymousUser().has_perm(self.cat_code, self.cat))


class UnknownTerminalTest(_UsersMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._make_users('unk')
        self._reload()

    def test_unknown_user_and_dict_fail_closed(self):
        backend = TrustModelBackend()
        self.assertEqual(backend.get_group_permissions(self.alice, {}), set())
        self.assertEqual(backend.get_all_permissions(self.alice, {}), set())
        self.assertFalse(backend.has_perm(self.alice, 'auth.change_user', self.alice))
        self.assertIsNone(content_row(User))


class DependentContentAuthorizationTest(_UsersMixin, TestCase):
    """Two-level content registered from the host ``AppConfig.ready()``."""

    def setUp(self):
        super().setUp()
        self.Receipt = Receipt
        self.Image = ReceiptImage
        self.Meta = ReceiptImageMeta
        self.Orphan = OrphanDoc
        self._make_users('dep')
        self.receipt_a1 = self.Receipt.objects.create(
            trust=self.trust_a, title='A1',
        )
        self.receipt_a2 = self.Receipt.objects.create(
            trust=self.trust_a, title='A2',
        )
        self.receipt_b = self.Receipt.objects.create(
            trust=self.trust_b, title='B',
        )
        self.img_a1 = self.Image.objects.create(
            receipt=self.receipt_a1, title='A1',
        )
        self.img_a2 = self.Image.objects.create(
            receipt=self.receipt_a2, title='A2',
        )
        self.img_b = self.Image.objects.create(
            receipt=self.receipt_b, title='B',
        )
        self.meta_a1 = self.Meta.objects.create(image=self.img_a1, title='A1')
        self.meta_a2 = self.Meta.objects.create(image=self.img_a2, title='A2')
        self.meta_b = self.Meta.objects.create(image=self.img_b, title='B')
        self.orphan = self.Orphan.objects.create(
            receipt=self.receipt_a1, title='X',
        )
        extras = [
            self.Image.objects.create(
                receipt=self.Receipt.objects.create(
                    trust=self.trust_a, title='X%s' % i,
                ),
                title='X%s' % i,
            )
            for i in range(6)
        ]
        self.extra_metas = [
            self.Meta.objects.create(image=image, title=image.title)
            for image in extras
        ]
        self.image_code = 'trusts_zero_tests.change_%s' % self.Image._meta.model_name
        self.meta_code = 'trusts_zero_tests.change_%s' % self.Meta._meta.model_name
        self.orphan_code = 'trusts_zero_tests.change_%s' % self.Orphan._meta.model_name
        self.image_perm = _perm(self.Image, 'change_%s' % self.Image._meta.model_name)
        self.meta_perm = _perm(self.Meta, 'change_%s' % self.Meta._meta.model_name)
        self.orphan_perm = _perm(
            self.Orphan, 'change_%s' % self.Orphan._meta.model_name,
        )
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.image_perm,
        ).save()
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.meta_perm,
        ).save()
        TrustUserPermission(
            trust=self.trust_a, entity=self.alice, permission=self.orphan_perm,
        ).save()
        self.carol_group = Group.objects.create(name='carol-s7-dep')
        self.carol.groups.add(self.carol_group)
        self.image_perm.group_set.add(self.carol_group)
        self.meta_perm.group_set.add(self.carol_group)
        enable_local_group_grant(
            self.trust_a, self.carol_group, self.image_perm, self.meta_perm,
        )
        self._reload()

    def test_host_contributed_both_levels(self):
        rev = self.Receipt._meta.get_field('trust').remote_field.get_accessor_name()
        image = trust_rows(self.Image, TrustUserPermission, TEST_BACKEND)[0]
        meta = trust_rows(self.Meta, TrustUserPermission, TEST_BACKEND)[0]
        self.assertEqual(image['content']['path'], 'trust__%s__image' % rev)
        self.assertEqual(meta['content']['path'], 'trust__%s__image__image' % rev)
        self.assertIsNone(content_row(self.Orphan, TEST_BACKEND))
        self.assertIsNone(content_row(self.Receipt, TEST_BACKEND))

    def test_image_object_queryset_enumeration_and_users(self):
        self._assert_terminal(
            self.Image, self.image_code, self.image_perm,
            self.img_a1, self.img_a2, self.img_b, self.receipt_a1, self.receipt_b,
        )

    def test_meta_object_queryset_enumeration_and_users(self):
        self._assert_terminal(
            self.Meta, self.meta_code, self.meta_perm,
            self.meta_a1, self.meta_a2, self.meta_b, self.receipt_a1, self.receipt_b,
        )

    def _assert_terminal(self, model, code, perm, granted, sibling, other,
                         prefix_granted, prefix_denied):
        self.assertTrue(self.alice.has_perm(code, granted))
        self.assertTrue(self.alice.has_perm(code, sibling))
        self.assertFalse(self.alice.has_perm(code, other))
        self.assertFalse(self.bob.has_perm(code, granted))
        self.assertTrue(self.carol.has_perm(code, granted))
        self.assertFalse(self.carol.has_perm(code, other))
        granted_qs = model.objects.filter(pk__in=[granted.pk, sibling.pk])
        mixed_qs = model.objects.filter(pk__in=[granted.pk, other.pk])
        self.assertTrue(self.alice.has_perm(code, granted_qs))
        self.assertFalse(self.alice.has_perm(code, mixed_qs))
        self.assertTrue(self.carol.has_perm(code, granted_qs))
        self.assertFalse(self.carol.has_perm(code, mixed_qs))
        self.assertIn(code, self.alice.get_all_permissions(granted))
        self.assertNotIn(code, self.alice.get_group_permissions(granted))
        self.assertIn(code, self.carol.get_all_permissions(granted))
        self.assertIn(code, self.carol.get_group_permissions(granted))
        self.assertIn(code, self.alice.get_all_permissions(granted_qs))
        self.assertEqual(self.alice.get_group_permissions(granted_qs), set())
        self.assertIn(code, self.carol.get_group_permissions(granted_qs))
        self.assertEqual(self.bob.get_all_permissions(granted), set())
        holders = PermittedUsersMixin.get_permitted_users
        self.assertIn(self.alice.pk, _user_pks(holders(granted, code)))
        self.assertIn(self.carol.pk, _user_pks(holders(granted, code)))
        self.assertNotIn(self.bob.pk, _user_pks(holders(granted, code)))
        self.assertNotIn(self.alice.pk, _user_pks(holders(other, code)))
        prefixes = filter_by_permitted_content(
            self.Receipt.objects.all(), self.alice, perm, content=model,
        )
        prefix_pks = set(prefixes.values_list('pk', flat=True))
        self.assertIn(prefix_granted.pk, prefix_pks)
        self.assertNotIn(prefix_denied.pk, prefix_pks)

    def test_one_sql_independent_of_candidate_count(self):
        image_qs = self.Image.objects.filter(
            pk__in=[self.img_a1.pk, self.img_a2.pk] + list(
                self.Image.objects.exclude(
                    pk__in=[self.img_a1.pk, self.img_a2.pk, self.img_b.pk],
                ).values_list('pk', flat=True)
            ),
        )
        meta_qs = self.Meta.objects.filter(
            pk__in=[self.meta_a1.pk, self.meta_a2.pk] + [
                meta.pk for meta in self.extra_metas
            ],
        )
        with self.assertNumQueries(1):
            self.assertTrue(self.alice.has_perm(self.image_code, self.img_a1))
        with self.assertNumQueries(1):
            self.assertTrue(self.alice.has_perm(self.image_code, image_qs))
        with self.assertNumQueries(1):
            self.assertIn(
                self.image_code, self.alice.get_all_permissions(image_qs),
            )
        with self.assertNumQueries(1):
            self.assertIn(
                self.image_code,
                self.carol.get_group_permissions(image_qs),
            )
        with self.assertNumQueries(1):
            self.assertTrue(self.alice.has_perm(self.meta_code, self.meta_a1))
        with self.assertNumQueries(1):
            self.assertTrue(self.alice.has_perm(self.meta_code, meta_qs))
        with self.assertNumQueries(1):
            self.assertIn(
                self.meta_code, self.alice.get_all_permissions(meta_qs),
            )
        with self.assertNumQueries(1):
            self.assertIn(
                self.meta_code, self.carol.get_group_permissions(meta_qs),
            )

    def test_undeclared_orphan_fails_closed(self):
        self.assertFalse(self.alice.has_perm(self.orphan_code, self.orphan))
        self.assertFalse(self.carol.has_perm(self.orphan_code, self.orphan))
        qs = self.Orphan.objects.filter(pk=self.orphan.pk)
        self.assertFalse(self.alice.has_perm(self.orphan_code, qs))
        self.assertEqual(self.alice.get_all_permissions(self.orphan), set())
        self.assertEqual(
            self.alice.get_group_permissions(self.orphan), set(),
        )
        self.assertFalse(
            filter_by_permitted_content(
                self.Receipt.objects.all(), self.alice, self.orphan_perm,
                content=self.Orphan,
            ).exists()
        )
        self.assertEqual(
            list(PermittedUsersMixin.get_permitted_users(
                self.orphan, self.orphan_code,
            )),
            [],
        )

    def test_inactive_anonymous_obj_none(self):
        self.assertFalse(self.alice.has_perm(self.image_code))
        self.assertEqual(self.alice.get_all_permissions(), set())
        self.alice.is_active = False
        self.alice.save()
        self._reload()
        self.assertFalse(self.alice.has_perm(self.image_code, self.img_a1))
        self.assertFalse(AnonymousUser().has_perm(self.image_code, self.img_a1))
        self.assertEqual(AnonymousUser().get_all_permissions(self.img_a1), set())


def _user_pks(qs):
    return set(qs.values_list('pk', flat=True))
