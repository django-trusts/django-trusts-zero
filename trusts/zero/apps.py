"""Zero's Django app config.

The catalog is built from ``self.recorder`` by ``TrustsConfigMixin.ready``.
Named filters and relations are recorded here, before that build.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from trusts.apps import TrustsConfigMixin
from trusts.errors import TrustsConfigurationError
from trusts.zero.registration import register_zero_meta_option_names


# Phase-1: Zero-only Meta option names must exist before host models
# that declare them are constructed. ready() is too late.
register_zero_meta_option_names()


CANONICAL_BACKEND_PATH = 'trusts.zero.backends.TrustModelBackend'
DEPRECATED_CORE_BACKEND_PATH = 'trusts.backends.TrustModelBackend'


class ZeroConfig(TrustsConfigMixin):
    """Historical concrete Trusts implementation (Step IIa).

    ``name`` is the Python package. ``label`` stays ``trusts`` so migration
    identity, table names, and content-type/permission natural keys remain
    ``('trusts', '0001_initial')`` / ``('trusts', '0002_trustgroup')``.

    Install with the explicit class path ``trusts.zero.apps.ZeroConfig``.
    Do not list ``'trusts'`` (core is a library) and do not list the
    temporary core historical backend path. Bare ``'trusts.zero'`` is
    forbidden by the 2.0 ``migrates.md`` checklist even when ``default``
    is true.

    ``query_compiler`` stays unset so ``ready`` stores Core's default
    plan compiler on this app's catalog. The backend class does not
    carry a compiler; it reads this catalog.
    """

    name = 'trusts.zero'
    label = 'trusts'
    verbose_name = "Django Trusts Zero"
    default = True
    # Preserve the historical AutoField primary keys from 0001_initial.
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        # Deferred import: django.apps. Same populate constraint as
        # zero_config().
        from django.apps import apps as django_apps

        # Deferred import: trusts.zero.admin, optional contrib.admin.
        # The admin module imports Zero models and registers ModelAdmins.
        # Importing it at module level would require admin on every install.
        if django_apps.is_installed('django.contrib.admin'):
            from trusts.zero.admin import register_auto_modeladmins
            register_auto_modeladmins()

        self._require_canonical_backend()
        if self.recorder.frozen:
            return
        self._donate_zero_relations()
        super().ready()

    def _require_canonical_backend(self):
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

    def _donate_zero_relations(self):
        """Record Trust relations and ``Trust:own`` on this app's recorder.

        ``TrustsConfigMixin.ready`` freezes the recorder and builds the
        catalog. The backend in this app reads that catalog. There is
        no ``Meta.permission_conditions`` walk.
        """
        # Deferred import: trusts.zero.models. This module is imported
        # while the app registry is still populating. Importing models
        # at module level raises AppRegistryNotReady.
        from trusts.zero.models import Trust
        from trusts.zero.registration import (
            register_zero_relations,
            trust_settlor_owns,
        )

        backend = self.recorder
        register_zero_relations(backend)
        backend.add_named_filter(Trust, 'own', predicate=trust_settlor_owns)


def zero_config(apps_registry=None):
    """Return the unique installed ``ZeroConfig`` by class identity.

    Optional ``apps_registry`` is an ``Apps`` instance; the default is
    Django's global registry. Zero or several owners fail loud.
    """
    # Deferred import: django.apps. This module is an AppConfig and is
    # imported while populate is still running.
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
