from django.apps import AppConfig

from trusts.core import Ref, TrustsConfigurationError
from trusts.zero.apps import CANONICAL_BACKEND_PATH


class TestsConfig(AppConfig):
    name = 'tests'
    label = 'trusts_zero_tests'
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        if getattr(self, 'apps', None) is None:
            return
        from trusts.apps import implementation_for_path

        try:
            owner = implementation_for_path(
                CANONICAL_BACKEND_PATH, apps_registry=self.apps,
            )
        except (TrustsConfigurationError, ImportError, LookupError):
            # isolate_apps() / owner-absent hosts must not donate onto
            # a live registry. Fail closed; do not call kernel_config().
            return

        from tests.models import Category, Ticket
        from trusts.zero.models import TrustUserPermission

        registry = owner.configured_backend(CANONICAL_BACKEND_PATH).registry
        donated = getattr(self, '_zero_host_registry_id', None)
        if donated is registry:
            return
        j = Ref(TrustUserPermission)
        for model in (Category, Ticket):
            rev = model._meta.get_field('trust').remote_field.get_accessor_name()
            registry.register(
                content=getattr(j.trust, rev),
                user=j.entity,
                permission=j.permission,
            )
        self._zero_host_registry_id = registry
