"""Zero paired with Core #268: dotted codes use the queryset content model."""

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase

from tests.models import Category
from tests.runtests import NORMAL_SUITE


class ExactCodenameResolutionZeroTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('create_trust_root')

    def test_module_is_on_the_zero_suite(self):
        self.assertIn('tests.test_issue268', NORMAL_SUITE)

    def test_dotted_code_resolves_on_the_queryset_model_not_the_codename_suffix(self):
        category_type = ContentType.objects.get_for_model(Category)
        permission = Permission.objects.get(
            content_type=category_type, codename='read_category',
        )
        resolved = Category.objects.get_permission('trusts_zero_tests.read_category')
        self.assertEqual(resolved.pk, permission.pk)
        self.assertEqual(resolved.content_type, category_type)

    def test_dotted_codename_without_underscore_stays_exact(self):
        category_type = ContentType.objects.get_for_model(Category)
        approve = Permission.objects.create(
            content_type=category_type, codename='approve', name='Can approve',
        )
        Permission.objects.create(
            content_type=category_type, codename='approve_category',
            name='Can approve category',
        )
        resolved = Category.objects.get_permission('trusts_zero_tests.approve')
        self.assertEqual(resolved.pk, approve.pk)

    def test_dotted_codename_is_not_expanded_when_only_the_suffixed_row_exists(self):
        Permission.objects.create(
            content_type=ContentType.objects.get_for_model(Category),
            codename='approve_category', name='Can approve category',
        )
        with self.assertRaises(Permission.DoesNotExist):
            Category.objects.get_permission('trusts_zero_tests.approve')
        self.assertEqual(
            Category.objects.get_permission('approve').codename,
            'approve_category',
        )
