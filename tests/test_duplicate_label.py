"""Startup-gate tests for Zero IIa.

C1's duplicate-label clash is obsolete: Step I core already uses
``label='trusts_core'``, so installing ``ZeroConfig`` (``label='trusts'``)
does not collide. IIa's remaining startup gate is the old core backend
path, which must fail rather than act as an alias.
"""

from __future__ import annotations

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from trusts.zero.apps import CANONICAL_BACKEND, LEGACY_CORE_BACKEND, ZeroConfig


class OldBackendPathStartupTests(SimpleTestCase):
    def test_legacy_core_backend_path_is_rejected(self):
        config = apps.get_app_config('trusts')
        with override_settings(AUTHENTICATION_BACKENDS=[LEGACY_CORE_BACKEND]):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                ZeroConfig.ready(config)
        message = str(ctx.exception)
        self.assertIn(CANONICAL_BACKEND, message)
        self.assertIn(LEGACY_CORE_BACKEND, message)
        self.assertNotIn('duplicate', message.lower())
