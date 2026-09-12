from django.apps import AppConfig as DjangoAppConfig
from django.core.exceptions import ImproperlyConfigured

from trusts.zero.registration import register_zero_meta_option_names


# Phase-1: Zero-only Meta option names must exist before host models
# that declare them are constructed. ready() is too late.
register_zero_meta_option_names()


CANONICAL_BACKEND_PATH = 'trusts.zero.backends.TrustModelBackend'
DEPRECATED_CORE_BACKEND_PATH = 'trusts.backends.TrustModelBackend'
CORE_REQUIREMENT = 'django-trusts>=1.0.0.dev3,<2'
FLOOR_MESSAGE = (
    'django-trusts-zero 1.0.0.dev0 requires %s '
    '(TrustsImplementationConfig and implementation_for_path / '
    'implementation_for_class). The installed django-trusts is below '
    'the supported core floor. Upgrade django-trusts to 1.0.0.dev3 or later.'
    % CORE_REQUIREMENT
)


try:
    from trusts.apps import TrustsImplementationConfig
except ImportError:
    # Raw ImportError is not an accepted IIa fail path. ready() speaks.
    TrustsImplementationConfig = None


_ZeroBase = TrustsImplementationConfig or DjangoAppConfig


class ZeroConfig(_ZeroBase):
    """Historical concrete Trusts implementation owner (Step IIa).

    ``name`` is the Python package. ``label`` stays ``trusts`` so migration
    identity, table names, and content-type/permission natural keys remain
    ``('trusts', '0001_initial')`` / ``('trusts', '0002_trustgroup')``.

    Install with the explicit class path ``trusts.zero.apps.ZeroConfig``.
    Do not list ``'trusts'`` (core is a library) and do not list the
    temporary core historical backend path. Bare ``'trusts.zero'`` is
    forbidden by the 2.0 ``migrates.md`` checklist even when ``default``
    is true.
    """

    name = 'trusts.zero'
    label = 'trusts'
    verbose_name = "Django Trusts Zero"
    default = True
    # Preserve the historical AutoField primary keys from 0001_initial.
    default_auto_field = 'django.db.models.AutoField'
    trusts_backend_paths = (CANONICAL_BACKEND_PATH,)

    def ready(self):
        from django.apps import apps as django_apps
        from django.conf import settings

        if django_apps.is_installed('django.contrib.admin'):
            from trusts.zero.admin import register_auto_modeladmins
            register_auto_modeladmins()

        if TrustsImplementationConfig is None:
            raise ImproperlyConfigured(FLOOR_MESSAGE)

        listed = tuple(getattr(settings, 'AUTHENTICATION_BACKENDS', ()) or ())
        if CANONICAL_BACKEND_PATH not in listed:
            extra = ''
            if DEPRECATED_CORE_BACKEND_PATH in listed:
                extra = (
                    ' Found deprecated %s, which is not Zero IIa '
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
                'Remove %s; Zero IIa owns only %s.'
                % (
                    CANONICAL_BACKEND_PATH,
                    DEPRECATED_CORE_BACKEND_PATH,
                    DEPRECATED_CORE_BACKEND_PATH,
                    CANONICAL_BACKEND_PATH,
                )
            )

        super(ZeroConfig, self).ready()
        self._donate_zero_relations()

    def _donate_zero_relations(self):
        """Register TUP/TGP, donate Meta conditions, bind generic lookup.

        Uses the public owner/resolver API. Never calls
        ``kernel_config()``. Named conditions are donated through
        ``handle.register_permission_condition`` while ``apps.ready``
        is still false. There is no Zero-owned ``Content._conditions``
        store.
        """
        from trusts.apps import implementation_for_path
        from trusts.conditions import RegistryConditionLookup
        from trusts.zero.registration import (
            donate_installed_permission_conditions,
            register_zero_relations,
        )

        owner = implementation_for_path(
            CANONICAL_BACKEND_PATH, apps_registry=self.apps,
        )
        handle = owner.configured_backend(CANONICAL_BACKEND_PATH)
        register_zero_relations(handle.registry)
        donate_installed_permission_conditions(
            handle, apps_registry=self.apps,
        )
        handle.registry.set_condition_lookup(
            RegistryConditionLookup(handle.registry),
        )


def zero_config(apps_registry=None):
    """Return the unique installed ``ZeroConfig`` by class identity.

    Optional ``apps_registry`` is an ``Apps`` instance; the default is
    Django's global registry. Zero or several owners fail loud. Does
    not call ``kernel_config()``.
    """
    from django.apps import apps as django_apps
    from trusts.core import TrustsConfigurationError

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
