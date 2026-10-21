"""Installed test app.

Each app owns its recorder. ``ready`` records this app's terminals and
named filters, then ``TrustsConfigMixin.ready`` freezes that recorder.
Zero's recorder is not this app's.
"""

from trusts.apps import TrustsConfigMixin


class TestsConfig(TrustsConfigMixin):
    name = 'tests'
    label = 'trusts_zero_tests'
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        # Forced: tests.models imports ContentQuerySet, which imports
        # trusts.models, and that module imports auth.Permission. That
        # import is not safe while Django is still loading app configs.
        from tests.apps import register_test_terminals

        register_test_terminals(self.recorder)
        super().ready()
