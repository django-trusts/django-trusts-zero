"""Installed test app.

This module is what ``INSTALLED_APPS`` loads. It must not import
``trusts.compile.catalogs``: that module imports ``auth.Permission``,
which is not ready while Django is still importing app configs.
``tests.apps`` holds the catalog helper and imports ``Catalog`` at
module level, the same way Core's tests do, after models are ready.
"""

from django.apps import AppConfig


class TestsConfig(AppConfig):
    name = 'tests'
    label = 'trusts_zero_tests'
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        from tests.apps import register_installed_terminals

        register_installed_terminals(self)
