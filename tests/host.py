"""Installed test app.

Registration is the end of ``tests.models`` on
``TestsBackend().get_registry()``. This config does not record on
Zero's registry.
"""

from trusts.apps import TrustsConfigMixin


class TestsConfig(TrustsConfigMixin):
    name = 'tests'
    label = 'trusts_zero_tests'
    default_auto_field = 'django.db.models.AutoField'
