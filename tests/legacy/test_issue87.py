"""Condition donation and live terminal parity (issue #87).

The static content map is gone. Meta conditions are donated onto a
recorder and read from the compiled catalog. Live ``has_perm`` still
covers Category, Ticket, Trust, and Group.
"""

from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import connection, models
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from tests.apps import build_catalog, forget_models, live_catalog
from tests.legacy.helpers import enable_local_group_grant, get_or_create_root_user
from tests.models import Category, Organization, TestGroupJunction, Ticket
from trusts.inspect.checks import check_permission_conditions
from trusts.zero.backends import TrustModelBackend
from trusts.zero.models import Content, Junction, Trust, TrustUserPermission
from trusts.zero.query import ContentManager
from trusts.zero.registration import (
    donate_content_permission_conditions,
    donate_junction_content_permission_conditions,
    register_zero_content,
)


def _sheet_own(u, p, o):
    return o.trust != None


def _junc_own(u, p, o):
    return o.trust != None


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


class DonatedConditionCatalogTest(SimpleTestCase):
    def test_content_meta_lands_on_an_isolated_catalog(self):
        class IsolatedSheet(Content):
            title = models.CharField(max_length=40)

            class Meta:
                app_label = 'trusts_zero_tests'
                managed = False
                permission_conditions = (
                    ('sheet_own', _sheet_own),
                )

        try:
            def contribute(recorder):
                donate_content_permission_conditions(recorder, IsolatedSheet)
                donate_content_permission_conditions(recorder, IsolatedSheet)

            catalog = build_catalog(contribute)
            record = catalog.get_permission_condition_record(IsolatedSheet, 'sheet_own')
            self.assertIsNotNone(record)
            self.assertIs(record.model, IsolatedSheet)
            self.assertIsNotNone(record.expr)
            self.assertFalse(live_catalog().plan_for(IsolatedSheet).records)
            codes = [
                code for model, code, _record in catalog.iter_permission_conditions()
                if model is IsolatedSheet
            ]
            self.assertEqual(codes, ['sheet_own'])
        finally:
            forget_models(IsolatedSheet)

    def test_junction_meta_lands_on_an_isolated_catalog(self):
        class IsolatedJunction(Junction):
            content = models.ForeignKey(
                Group, unique=True, on_delete=models.CASCADE,
            )

            class Meta:
                app_label = 'trusts_zero_tests'
                managed = False
                content_permission_conditions = (
                    ('junc_own', _junc_own),
                )

        try:
            before = live_catalog().plan_for(Group).records

            def contribute(recorder):
                donate_junction_content_permission_conditions(
                    recorder, IsolatedJunction,
                )

            catalog = build_catalog(contribute)
            record = catalog.get_permission_condition_record(
                IsolatedJunction, 'junc_own',
            )
            self.assertIsNotNone(record)
            self.assertIs(record.model, IsolatedJunction)
            self.assertIsNotNone(record.expr)
            self.assertEqual(live_catalog().plan_for(Group).records, before)
        finally:
            forget_models(IsolatedJunction)

    def test_duplicate_named_filter_keeps_the_last_expression(self):
        def contribute(recorder):
            recorder.add_named_filter(
                Ticket, 'meta_own', lambda u, p, o: o.title == 'first',
            )
            recorder.add_named_filter(
                Ticket, 'meta_own', lambda u, p, o: u == o.owner,
            )

        catalog = build_catalog(contribute)
        record = catalog.get_permission_condition_record(Ticket, 'meta_own')
        self.assertIs(record.model, Ticket)
        self.assertEqual(
            record.expr.to_tuple(),
            ('eq', ('ref', 'principal', ()), ('ref', 'object', ('owner',))),
        )


class LiveConditionTest(TestCase):
    def test_trust_own_and_ticket_meta_own_remain(self):
        catalog = live_catalog()
        own = catalog.get_permission_condition_record(Trust, 'own')
        self.assertIsNotNone(own)
        self.assertIs(own.model, Trust)
        self.assertIsNotNone(own.expr)
        meta_own = catalog.get_permission_condition_record(Ticket, 'meta_own')
        self.assertIsNotNone(meta_own)
        self.assertIs(meta_own.model, Ticket)
        self.assertIsNotNone(meta_own.expr)
        messages = check_permission_conditions(None)
        self.assertEqual([message for message in messages if message.id == 'trusts.E001'], [])


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
        self.assertFalse(live_catalog().plan_for(User).records)


def dependent_content_path(prefix, content_model, *suffixes):
    """Public ``__`` path: Trust reverse onto ``content_model``, then suffixes."""
    rev = content_model._meta.get_field('trust').remote_field.get_accessor_name()
    parts = (prefix, 'trust', rev) + suffixes
    return '__'.join(part for part in parts if part)


def _receipt_chain():
    """Receipt → image → image, plus an unregistered orphan on the receipt."""

    class Receipt(Content):
        title = models.CharField(max_length=40)

        class Meta:
            app_label = 'trusts_zero_tests'

    class Image(models.Model):
        receipt = models.ForeignKey(
            Receipt, related_name='image', on_delete=models.CASCADE,
        )
        title = models.CharField(max_length=40)
        objects = ContentManager()

        class Meta:
            app_label = 'trusts_zero_tests'

    class MetaRow(models.Model):
        image = models.ForeignKey(
            Image, related_name='image', on_delete=models.CASCADE,
        )
        title = models.CharField(max_length=40)
        objects = ContentManager()

        class Meta:
            app_label = 'trusts_zero_tests'

    class Orphan(models.Model):
        receipt = models.ForeignKey(
            Receipt, related_name='orphan', on_delete=models.CASCADE,
        )
        title = models.CharField(max_length=40)
        objects = ContentManager()

        class Meta:
            app_label = 'trusts_zero_tests'

    return Receipt, Image, MetaRow, Orphan


class DependentContentAuthorizationTest(_UsersMixin, TransactionTestCase):
    """Two-level content a host contributes on an isolated catalog."""

    def setUp(self):
        super().setUp()
        self.Receipt, self.Image, self.Meta, self.Orphan = _receipt_chain()
        self._models = (self.Receipt, self.Image, self.Meta, self.Orphan)
        with connection.schema_editor() as editor:
            for model in self._models:
                editor.create_model(model)
        try:
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

            def contribute(recorder):
                register_zero_content(
                    recorder,
                    self.Image,
                    content_via=lambda prefix, model: dependent_content_path(
                        prefix, self.Receipt, 'image',
                    ),
                )
                register_zero_content(
                    recorder,
                    self.Meta,
                    content_via=lambda prefix, model: dependent_content_path(
                        prefix, self.Receipt, 'image', 'image',
                    ),
                )

            self.catalog = build_catalog(contribute)
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
        except Exception:
            self._drop_tables()
            raise

    def tearDown(self):
        self._drop_tables()
        super().tearDown()

    def _drop_tables(self):
        if getattr(self, '_dropped', False):
            return
        self._dropped = True
        with connection.schema_editor() as editor:
            for model in reversed(self._models):
                editor.delete_model(model)
        forget_models(*self._models)

    def test_host_contributed_both_levels(self):
        rev = self.Receipt._meta.get_field('trust').remote_field.get_accessor_name()
        image_paths = [
            record.content_path for record in self.catalog.plan_for(self.Image).records
        ]
        meta_paths = [
            record.content_path for record in self.catalog.plan_for(self.Meta).records
        ]
        self.assertIn(('trust', rev, 'image'), image_paths)
        self.assertIn(('trust', rev, 'image', 'image'), meta_paths)
        self.assertFalse(self.catalog.plan_for(self.Orphan).records)
        self.assertFalse(self.catalog.plan_for(self.Receipt).records)

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
        catalog = self.catalog
        self.assertTrue(catalog.has_perm(self.alice, code, granted))
        self.assertTrue(catalog.has_perm(self.alice, code, sibling))
        self.assertFalse(catalog.has_perm(self.alice, code, other))
        self.assertFalse(catalog.has_perm(self.bob, code, granted))
        self.assertTrue(catalog.has_perm(self.carol, code, granted))
        self.assertFalse(catalog.has_perm(self.carol, code, other))
        granted_qs = model.objects.filter(pk__in=[granted.pk, sibling.pk])
        mixed_qs = model.objects.filter(pk__in=[granted.pk, other.pk])
        self.assertTrue(catalog.has_perm(self.alice, code, granted_qs))
        self.assertFalse(catalog.has_perm(self.alice, code, mixed_qs))
        self.assertTrue(catalog.has_perm(self.carol, code, granted_qs))
        self.assertFalse(catalog.has_perm(self.carol, code, mixed_qs))
        self.assertIn(code, catalog.get_all_permissions(self.alice, granted))
        self.assertNotIn(code, catalog.get_group_permissions(self.alice, granted))
        self.assertIn(code, catalog.get_all_permissions(self.carol, granted))
        self.assertIn(code, catalog.get_group_permissions(self.carol, granted))
        self.assertIn(code, catalog.get_all_permissions(self.alice, granted_qs))
        self.assertEqual(catalog.get_group_permissions(self.alice, granted_qs), set())
        self.assertIn(code, catalog.get_group_permissions(self.carol, granted_qs))
        self.assertEqual(catalog.get_all_permissions(self.bob, granted), set())
        self.assertIn(
            self.alice.pk, _user_pks(catalog.permitted_users(granted, code)),
        )
        self.assertIn(
            self.carol.pk, _user_pks(catalog.permitted_users(granted, code)),
        )
        self.assertNotIn(
            self.bob.pk, _user_pks(catalog.permitted_users(granted, code)),
        )
        self.assertNotIn(
            self.alice.pk, _user_pks(catalog.permitted_users(other, code)),
        )
        prefixes = catalog.filter_by_permitted_content(
            self.Receipt.objects.all(), self.alice, perm, content=model,
        )
        prefix_pks = set(prefixes.values_list('pk', flat=True))
        self.assertIn(prefix_granted.pk, prefix_pks)
        self.assertNotIn(prefix_denied.pk, prefix_pks)

    def test_one_sql_independent_of_candidate_count(self):
        catalog = self.catalog
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
            self.assertTrue(catalog.has_perm(self.alice, self.image_code, self.img_a1))
        with self.assertNumQueries(1):
            self.assertTrue(catalog.has_perm(self.alice, self.image_code, image_qs))
        with self.assertNumQueries(1):
            self.assertIn(
                self.image_code, catalog.get_all_permissions(self.alice, image_qs),
            )
        with self.assertNumQueries(1):
            self.assertIn(
                self.image_code,
                catalog.get_group_permissions(self.carol, image_qs),
            )
        with self.assertNumQueries(1):
            self.assertTrue(catalog.has_perm(self.alice, self.meta_code, self.meta_a1))
        with self.assertNumQueries(1):
            self.assertTrue(catalog.has_perm(self.alice, self.meta_code, meta_qs))
        with self.assertNumQueries(1):
            self.assertIn(
                self.meta_code, catalog.get_all_permissions(self.alice, meta_qs),
            )
        with self.assertNumQueries(1):
            self.assertIn(
                self.meta_code, catalog.get_group_permissions(self.carol, meta_qs),
            )

    def test_undeclared_orphan_fails_closed(self):
        catalog = self.catalog
        self.assertFalse(catalog.has_perm(self.alice, self.orphan_code, self.orphan))
        self.assertFalse(catalog.has_perm(self.carol, self.orphan_code, self.orphan))
        qs = self.Orphan.objects.filter(pk=self.orphan.pk)
        self.assertFalse(catalog.has_perm(self.alice, self.orphan_code, qs))
        self.assertEqual(catalog.get_all_permissions(self.alice, self.orphan), set())
        self.assertEqual(
            catalog.get_group_permissions(self.alice, self.orphan), set(),
        )
        self.assertFalse(
            catalog.filter_by_permitted_content(
                self.Receipt.objects.all(), self.alice, self.orphan_perm,
                content=self.Orphan,
            ).exists()
        )
        self.assertEqual(
            list(catalog.permitted_users(self.orphan, self.orphan_code)), [],
        )


def _user_pks(qs):
    return set(qs.values_list('pk', flat=True))
