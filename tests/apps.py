from contextlib import contextmanager

from django.apps import AppConfig

from trusts.apps import TrustsImplementationConfig
from trusts.core import Ref, TrustsConfigurationError
from trusts.zero.apps import CANONICAL_BACKEND_PATH


ZERO_BACKEND = CANONICAL_BACKEND_PATH


class IsolatedOwnerConfig(TrustsImplementationConfig):
    """Unbound pair-test owner. Not installed; constructed in isolation."""

    name = 'tests'
    label = 'trusts_isolated_owner'
    default = False
    trusts_backend_paths = (ZERO_BACKEND,)

    def ready(self):
        for path in self.owned_backend_paths():
            self._ensure(path)


def isolated_owner():
    """Construct a standalone implementation owner for isolation tests."""
    import tests as tests_module

    return IsolatedOwnerConfig('tests', tests_module)


def live_config(apps_registry=None):
    """The unique installed ``TrustsImplementationConfig`` (ZeroConfig)."""
    from trusts.apps import implementation_configs

    configs = implementation_configs(apps_registry)
    if len(configs) == 1:
        return configs[0]
    raise TrustsConfigurationError(
        'live_config() needs exactly one implementation owner; got %r'
        % (configs,)
    )


def live_registry(apps_registry=None):
    """Configured Zero handle registry."""
    return live_config(apps_registry).configured_backend(CANONICAL_BACKEND_PATH).registry


def junction_content_field(junction_model):
    """Return the Junction→content field from the concrete Junction contract."""
    content_model = junction_model.get_content_model()._meta.concrete_model
    matches = [
        field for field in junction_model._meta.fields
        if field.remote_field is not None
        and field.remote_field.model._meta.concrete_model is content_model
    ]
    if len(matches) != 1:
        raise TrustsConfigurationError(
            '%s does not expose exactly one content field for %s.'
            % (junction_model._meta.label, content_model._meta.label)
        )
    return matches[0]


def junction_group_content_ref(root_ref, junction_model):
    """J1 content ref: TUP → Trust ← Junction → Group/content."""
    rev = junction_model._meta.get_field('trust').remote_field.get_accessor_name()
    content_name = junction_content_field(junction_model).name
    return getattr(getattr(root_ref.trust, rev), content_name)


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
            return

        try:
            from tests.models import Category, TestGroupJunction, Ticket
            from trusts.zero.models import TrustUserPermission
        except ImportError:
            return

        registry = owner.configured_backend(CANONICAL_BACKEND_PATH).registry
        j = Ref(TrustUserPermission)

        donated_category = getattr(self, '_trusts_tup_category_registry_id', None)
        if donated_category is not registry:
            rev = Category._meta.get_field('trust').remote_field.get_accessor_name()
            registry.register(
                content=getattr(j.trust, rev),
                user=j.entity,
                permission=j.permission,
            )
            self._trusts_tup_category_registry_id = registry

        donated_ticket = getattr(self, '_trusts_tup_ticket_registry_id', None)
        if donated_ticket is not registry:
            rev = Ticket._meta.get_field('trust').remote_field.get_accessor_name()
            registry.register(
                content=getattr(j.trust, rev),
                user=j.entity,
                permission=j.permission,
            )
            self._trusts_tup_ticket_registry_id = registry

        donated_group = getattr(self, '_trusts_tup_group_registry_id', None)
        if donated_group is not registry:
            registry.register(
                content=junction_group_content_ref(j, TestGroupJunction),
                user=j.entity,
                permission=j.permission,
            )
            self._trusts_tup_group_registry_id = registry


@contextmanager
def override_apps_ready(ready, apps_registry=None):
    from django.apps import apps as django_apps

    target = django_apps if apps_registry is None else apps_registry
    was = target.ready
    target.ready = ready
    try:
        yield
    finally:
        target.ready = was


def isolate_live_registry(config, registry, path=None):
    if path is None:
        paths = config._configured_trusts_paths()
        path = paths[0]
    config.registries[path] = registry
    return registry


def install_writable_registry(config, path, contribute=None):
    from trusts.core import TrustsRegistry

    registry = TrustsRegistry()
    if contribute is not None:
        contribute(registry)
    config.registries[path] = registry
    return registry


def forget_models(*model_classes):
    from django.apps import apps as django_apps

    all_models = django_apps.all_models
    for model in model_classes:
        app_models = all_models.get(model._meta.app_label, {})
        app_models.pop(model._meta.model_name, None)
        for name, existing in list(app_models.items()):
            if existing is model:
                app_models.pop(name, None)
    django_apps.clear_cache()


def apply_zero_trust_donation(config):
    from django.utils.module_loading import import_string

    from trusts.zero.backends import TrustModelBackend
    from trusts.zero.models import register_zero_relations

    paths = config._configured_trusts_paths()
    for path in paths:
        cls = import_string(path)
        if not issubclass(cls, TrustModelBackend):
            continue
        registry = config._ensure(path)
        register_zero_relations(registry)
        ids = dict(getattr(config, '_trusts_tup_trust_registry_ids', None) or {})
        ids[path] = registry
        config._trusts_tup_trust_registry_ids = ids
        if len(paths) == 1:
            config._trusts_tup_trust_registry_id = registry
    return config


def clone_writable_registry(registry):
    from trusts.core import TrustsRegistry

    cloned = TrustsRegistry()
    cloned._by_root = {
        root: list(rows) for root, rows in registry._by_root.items()
    }
    cloned._order = list(registry._order)
    return cloned
