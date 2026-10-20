from django.apps import apps as django_apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from trusts.apps import TrustsImplementationConfig
from trusts.errors import TrustsConfigurationError
from trusts.zero.options import register_zero_meta_option_names


CANONICAL_BACKEND_PATH = 'trusts.zero.backends.TrustModelBackend'
DEPRECATED_CORE_BACKEND_PATH = 'trusts.backends.TrustModelBackend'

# Phase-1: Zero-only Meta option names must exist before host models
# that declare them are constructed. ready() is too late.
register_zero_meta_option_names()


class ZeroConfig(TrustsImplementationConfig):
    """Concrete Trusts app. ``label`` stays ``trusts``.

    Install ``trusts.zero.apps.ZeroConfig`` after apps that register in
    ``ready()``. Do not list ``'trusts'`` or the deprecated backend path.
    """

    name = 'trusts.zero'
    label = 'trusts'
    verbose_name = "Django Trusts Zero"
    default = True
    # Preserve the historical AutoField primary keys from 0001_initial.
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        # AppRegistryNotReady: backends imports Permission; helpers import models.
        from trusts.zero.backends import TrustModelBackend
        from trusts.zero.registration import (
            donate_installed_permission_conditions,
            register_zero_relations,
        )

        if django_apps.is_installed('django.contrib.admin'):
            # AppRegistryNotReady: admin imports models at import.
            from trusts.zero.admin import register_auto_modeladmins
            register_auto_modeladmins()

        listed = tuple(settings.AUTHENTICATION_BACKENDS or ())
        if CANONICAL_BACKEND_PATH not in listed:
            extra = ''
            if DEPRECATED_CORE_BACKEND_PATH in listed:
                extra = (
                    ' Found deprecated %s, which is not Zero '
                    'registry identity.' % DEPRECATED_CORE_BACKEND_PATH
                )
            raise ImproperlyConfigured(
                'ZeroConfig owns %s and requires that exact path in '
                'AUTHENTICATION_BACKENDS.%s Set AUTHENTICATION_BACKENDS '
                "to include %r. Do not use %s."
                % (
                    CANONICAL_BACKEND_PATH,
                    extra,
                    CANONICAL_BACKEND_PATH,
                    DEPRECATED_CORE_BACKEND_PATH,
                )
            )
        if DEPRECATED_CORE_BACKEND_PATH in listed:
            raise ImproperlyConfigured(
                'AUTHENTICATION_BACKENDS lists both %s and the temporary '
                'core historical path %s. Those are different class objects. '
                'Remove %s; Zero owns only %s.'
                % (
                    CANONICAL_BACKEND_PATH,
                    DEPRECATED_CORE_BACKEND_PATH,
                    DEPRECATED_CORE_BACKEND_PATH,
                    CANONICAL_BACKEND_PATH,
                )
            )

        recorder = TrustModelBackend().get_registry()
        register_zero_relations(recorder)
        donate_installed_permission_conditions(
            recorder, apps_registry=self.apps,
        )
        super().ready()


def zero_config(apps_registry=None):
    """Return the unique installed ``ZeroConfig`` by class identity.

    Optional ``apps_registry`` is an ``Apps`` instance; the default is
    Django's global registry. Zero or several owners fail loud.
    """
    registry = django_apps if apps_registry is None else apps_registry
    matches = [
        config for config in registry.get_app_configs()
        if type(config) is ZeroConfig
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise TrustsConfigurationError('No installed ZeroConfig.')
    raise TrustsConfigurationError(
        'Multiple ZeroConfig instances: %r' % (matches,)
    )
