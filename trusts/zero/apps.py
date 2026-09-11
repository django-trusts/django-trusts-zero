from django.core.exceptions import ImproperlyConfigured

try:
    from trusts.apps import TrustsImplementationConfig
except ImportError:
    raise ImproperlyConfigured(
        'django-trusts-zero 2.0.0.dev2 requires django-trusts>=1.0.0.dev2,<2 '
        '(TrustsImplementationConfig). Upgrade django-trusts; do not '
        'rely on a missing import.'
    )


CANONICAL_BACKEND = 'trusts.zero.backends.TrustModelBackend'
LEGACY_CORE_BACKEND = 'trusts.backends.TrustModelBackend'
CORE_FLOOR = '1.0.0.dev2'
CORE_CEILING = '2'


def _require_step_i_core():
    """Reject cores that lack the Step I helper or miss the version floor."""
    try:
        from trusts.apps import TrustsImplementationConfig as helper  # noqa: F401
    except ImportError:
        raise ImproperlyConfigured(
            'django-trusts-zero 2.0.0.dev2 requires django-trusts>=%s,<%s '
            '(TrustsImplementationConfig). Upgrade django-trusts; do not '
            'rely on a missing import.'
            % (CORE_FLOOR, CORE_CEILING)
        )
    try:
        import importlib.metadata
        from packaging.version import Version

        installed = importlib.metadata.version('django-trusts')
    except importlib.metadata.PackageNotFoundError:
        raise ImproperlyConfigured(
            'django-trusts-zero 2.0.0.dev2 requires django-trusts>=%s,<%s, '
            'but django-trusts is not installed.'
            % (CORE_FLOOR, CORE_CEILING)
        )
    version = Version(installed)
    if version < Version(CORE_FLOOR) or version >= Version(CORE_CEILING):
        raise ImproperlyConfigured(
            'django-trusts-zero 2.0.0.dev2 requires django-trusts>=%s,<%s; '
            'installed django-trusts is %s.'
            % (CORE_FLOOR, CORE_CEILING, installed)
        )


def zero_config(apps_registry=None):
    """Return the installed ``ZeroConfig`` by class identity."""
    from django.apps import apps as django_apps

    registry = django_apps if apps_registry is None else apps_registry
    matches = [
        config for config in registry.get_app_configs()
        if type(config) is ZeroConfig
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ImproperlyConfigured('No installed trusts.zero.apps.ZeroConfig.')
    raise ImproperlyConfigured(
        'Multiple ZeroConfig instances: %r' % (matches,)
    )


class ZeroConfig(TrustsImplementationConfig):
    """Historical concrete Trusts app and the Step IIa registry owner.

    ``name`` is the Python package. ``label`` stays ``trusts`` so migration
    identity, table names, and content-type/permission natural keys remain
    ``('trusts', '0001_initial')`` / ``('trusts', '0002_trustgroup')``.

    Install with the explicit class path ``trusts.zero.apps.ZeroConfig``.
    Do not list ``'trusts'`` (core is a library). Bare ``'trusts.zero'``
    is forbidden by the 2.0 ``migrates.md`` checklist.
    """

    name = 'trusts.zero'
    label = 'trusts'
    verbose_name = "Django Trusts Zero"
    default = True
    default_auto_field = 'django.db.models.AutoField'
    trusts_backend_paths = (CANONICAL_BACKEND,)

    def ready(self):
        from django.apps import apps as django_apps
        from django.conf import settings

        from trusts.apps import implementation_for_path

        _require_step_i_core()

        listed = tuple(getattr(settings, 'AUTHENTICATION_BACKENDS', ()) or ())
        if LEGACY_CORE_BACKEND in listed:
            raise ImproperlyConfigured(
                'django-trusts-zero 2.0.0.dev2 does not use %s. Set '
                'AUTHENTICATION_BACKENDS to %r.'
                % (LEGACY_CORE_BACKEND, CANONICAL_BACKEND)
            )

        super(ZeroConfig, self).ready()

        if django_apps.is_installed('django.contrib.admin'):
            from trusts.zero.admin import register_auto_modeladmins
            register_auto_modeladmins()

        from trusts.zero.models import ContentConditionLookup, register_zero_relations

        owner = implementation_for_path(
            CANONICAL_BACKEND, apps_registry=getattr(self, 'apps', None),
        )
        handle = owner.configured_backend(CANONICAL_BACKEND)
        register_zero_relations(handle.registry)
        handle.registry.set_condition_lookup(ContentConditionLookup())
