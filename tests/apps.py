from django.apps import AppConfig

from trusts.core import Ref
from trusts.apps import kernel_config


class TestsConfig(AppConfig):
    name = 'tests'
    label = 'trusts_zero_tests'
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        if getattr(self, 'apps', None) is None:
            return
        try:
            kernel_config()
        except LookupError:
            return
        if not self.apps.is_installed('trusts.zero'):
            # ZeroConfig.name is trusts.zero; label is trusts.
            if not any(
                type(cfg).__name__ == 'ZeroConfig'
                for cfg in self.apps.get_app_configs()
            ):
                return

        from tests.models import Category, Ticket
        from trusts.zero.models import TrustUserPermission

        registry = kernel_config().configured_backend().registry
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
