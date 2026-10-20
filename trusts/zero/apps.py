from django.core.exceptions import ImproperlyConfigured

from trusts.apps import TrustsImplementationConfig
from trusts.errors import TrustsConfigurationError
from trusts.zero.registration import register_zero_meta_option_names


# Phase-1: Zero-only Meta option names must exist before host models
# that declare them are constructed. ready() is too late.
register_zero_meta_option_names()


CANONICAL_BACKEND_PATH = 'trusts.zero.backends.TrustModelBackend'
DEPRECATED_CORE_BACKEND_PATH = 'trusts.backends.TrustModelBackend'


class ZeroConfig(TrustsImplementationConfig):
    """Historical concrete Trusts implementation owner.

    ``name`` is the Python package. ``label`` stays ``trusts`` so migration
    identity, table names, and content-type/permission natural keys remain
    ``('trusts', '0001_initial')`` / ``('trusts', '0002_trustgroup')``.

    Install with the explicit class path ``trusts.zero.apps.ZeroConfig``,
    and list it after any app that registers relations in ``ready()``.
    ``TrustsImplementationConfig.ready`` builds the catalog from the
    recorder, so later ``ready()`` methods cannot add relations.
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

    def ready(self):
        from django.apps import apps as django_apps
        from django.conf import settings

        if django_apps.is_installed('django.contrib.admin'):
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

        self._donate_zero_relations()
        super().ready()

    def _donate_zero_relations(self):
        """Record TUP/TGP and Meta conditions before the catalog is built.

        Named conditions go through ``Recorder.add_named_filter``. The
        superclass build freezes the recorder and stores
        ``Catalog(factory.build())``. Donation is once per recorder.
        """
        from trusts.zero.backends import TrustModelBackend
        from trusts.zero.registration import (
            donate_installed_permission_conditions,
            register_zero_relations,
        )

        recorder = TrustModelBackend().get_registry()
        register_zero_relations(recorder)
        donate_installed_permission_conditions(
            recorder, apps_registry=self.apps,
        )


def zero_config(apps_registry=None):
    """Return the unique installed ``ZeroConfig`` by class identity.

    Optional ``apps_registry`` is an ``Apps`` instance; the default is
    Django's global registry. Zero or several owners fail loud.
    """
    from django.apps import apps as django_apps

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
