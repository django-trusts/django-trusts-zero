from django.apps import AppConfig

from trusts.core import Ref, TrustsConfigurationError
from trusts.zero.apps import CANONICAL_BACKEND


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
                CANONICAL_BACKEND, apps_registry=self.apps,
            )
        except TrustsConfigurationError:
            return
        if not self.apps.is_installed('trusts.zero'):
            if not any(
                type(cfg).__name__ == 'ZeroConfig'
                for cfg in self.apps.get_app_configs()
            ):
                return

        from tests.models import Category, Ticket
        from trusts.zero.models import TrustUserPermission

        registry = owner.configured_backend(CANONICAL_BACKEND).registry
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
