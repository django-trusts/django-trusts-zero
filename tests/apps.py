"""Test app config and catalog fixtures.

``TestsConfig`` hosts Category, Ticket, and Group registrations on its
own recorder. ``TestsCatalogBackend`` is the listed backend for that
catalog. Zero's catalog stays on ``ZeroConfig``.
"""

from contextlib import contextmanager

from trusts.apps import TrustsConfigMixin
from trusts.compile.nodes import Ref
from trusts.errors import TrustsConfigurationError
from trusts.zero.apps import CANONICAL_BACKEND_PATH


ZERO_BACKEND = CANONICAL_BACKEND_PATH
TESTS_BACKEND = 'tests.backends.TestsCatalogBackend'


def new_compiler(path='tests.isolated'):
    """Unfrozen ``Compiler``.

    Deferred import: ``trusts.compile.factory``. This module is an
    AppConfig and loads during populate. Importing the compiler then
    raises AppRegistryNotReady because compile imports contenttypes
    fields.
    """
    from django.contrib.auth import get_user_model
    from trusts.compile.factory import Compiler

    return Compiler(
        user_model=get_user_model(),
        query_compiler=Compiler.default_query_compiler(),
        path=path,
        family=TrustsConfigMixin.family,
    )


class _RegistryLookup(object):
    """Lookup whose ``conditions`` store is one compiler's registry.

    Tests compare ``lookup.conditions is registry.conditions``. The
    store is Core's ``ConditionRegistry``, not a second copy.
    """

    def __init__(self, registry):
        self.conditions = registry

    def compile_q(self, model, perm_string, user, user_model=None):
        del user_model
        return self.conditions.compile_registered_condition_q(
            model, perm_string, user,
        )

    def record_for(self, model, cond_code):
        return self.conditions.get_permission_condition_record(model, cond_code)


class IsolatedTarget(object):
    """Unfrozen compiler used as a registration target in tests.

    ``register`` / ``add_named_filter`` match ``Recorder`` and
    ``Compiler``. ``registry`` is this object so a test can read
    ``target.registry.records``. This is a test fixture. It is not a
    re-export of a removed Core type.
    """

    def __init__(self, path='tests.isolated'):
        self.path = path
        self._compiler = new_compiler(path)
        self.registry = self
        self.condition_lookup = _RegistryLookup(self._compiler.conditions)

    def register(self, **kwargs):
        # Test fixture. Legacy cases still pass root-relative Ref objects.
        # Compiler.register takes a model class plus ``__`` path strings.
        # Convert here so the compiler sees that public signature.
        trust = kwargs.get('trust')
        converted = {}
        for key, value in kwargs.items():
            if key == 'trust':
                continue
            if isinstance(value, Ref):
                if trust is None:
                    trust = value._root
                elif value._root is not trust:
                    raise TrustsConfigurationError(
                        'register roles must share one trust model.'
                    )
                converted[key] = '__'.join(value._path)
            else:
                converted[key] = value
        if trust is None:
            raise TypeError(
                "Compiler.register() missing 1 required keyword-only "
                "argument: 'trust'"
            )
        converted['trust'] = trust
        return self._compiler.register(**converted)

    @property
    def frozen(self):
        return self._compiler.frozen

    def freeze(self):
        """Compile in place. A compiled compiler refuses further register."""
        self._built = self._compiler.compile()
        return self._built

    def plan_for(self, content, **kwargs):
        built = getattr(self, '_built', None)
        if built is None:
            preview = clone_writable_registry(self._compiler)
            built = preview.compile()
        return built.plan_for(content, **kwargs)

    def add_named_filter(self, model, code, predicate=None, **kwargs):
        if predicate is None:
            predicate = kwargs['predicate']
        return self._compiler.add_named_filter(model, code, predicate)

    @property
    def records(self):
        return self._compiler.records

    @property
    def delegations(self):
        return self._compiler.delegations

    @property
    def conditions(self):
        return self._compiler.conditions

    def records_for_root(self, model):
        return [row for row in self._compiler.records if row.root is model]

    def get_permission_condition_record(self, model, code):
        return self._compiler.conditions.get_permission_condition_record(
            model, code,
        )

    def iter_permission_conditions(self):
        return self._compiler.conditions.iter_permission_conditions()

    def register_permission_condition(self, model, code, builder):
        return self.add_named_filter(model, code, builder)

    def set_condition_lookup(self, lookup):
        self.condition_lookup = lookup

    def compile(self):
        return self._compiler.compile()


class _FlushingRecords(dict):
    """``(label, code) → record`` view that writes back onto a catalog.

    ``Catalog.conditions`` is a tuple and ``filter_lookup`` is frozen.
    Isolation tests snapshot and restore rows. Each mutation copies
    the dict onto that tuple and the lookup index.
    """

    def __init__(self, catalog):
        super().__init__()
        self._catalog = catalog
        self._load()

    def _load(self):
        super().clear()
        for model, code, record in self._catalog.conditions:
            super().__setitem__((model._meta.label, code), record)

    def _flush(self):
        rows = []
        index = {}
        for (_label, code), record in self.items():
            model = record.model
            key = (model._meta.label, code)
            index[key] = record
            rows.append((model, code, record))
        catalog = self._catalog
        catalog.conditions = tuple(rows)
        lookup = catalog.filter_lookup
        lookup._index.clear()
        lookup._index.update(index)

    def clear(self):
        super().clear()
        self._flush()

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self._flush()

    def pop(self, *args, **kwargs):
        value = super().pop(*args, **kwargs)
        self._flush()
        return value

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._flush()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._flush()


class _ConditionStore(object):
    """Object with ``_records`` for one built catalog."""

    def __init__(self, catalog):
        self._catalog = catalog
        self._records = _FlushingRecords(catalog)


class _LookupView(object):
    """``condition_lookup`` whose ``conditions`` is the catalog store."""

    def __init__(self, catalog, store):
        self._catalog = catalog
        self.conditions = store

    def record_for(self, model, cond_code):
        return self._catalog.filter_lookup.record_for(model, cond_code)

    def compile_q(self, model, perm_string, user, user_model=None):
        return self._catalog.filter_lookup.compile_q(
            model, perm_string, user,
            user_model or self._catalog.user_model,
        )


class CatalogView(object):
    """Test view of one built catalog.

    Record helpers and a mutable condition dict sit on top of the
    catalog ``ready`` stored. Inquiry methods forward to that catalog.
    """

    def __init__(self, catalog):
        self._catalog = catalog
        self.conditions = _ConditionStore(catalog)
        self.condition_lookup = _LookupView(catalog, self.conditions)

    def __getattr__(self, name):
        return getattr(self._catalog, name)

    @property
    def frozen(self):
        """A built catalog does not accept further registration."""
        return True

    def register(self, *args, **kwargs):
        del args, kwargs
        raise TrustsConfigurationError(
            'register refused: this recorder is frozen. '
            'Record relations before ready().'
        )

    def records_for_root(self, model):
        return [row for row in self._catalog.records if row.root is model]

    def set_condition_lookup(self, lookup):
        self.condition_lookup = lookup


def catalog_view(catalog):
    """One ``CatalogView`` per catalog object so identity checks hold."""
    view = getattr(catalog, '_test_view', None)
    if view is None or view._catalog is not catalog:
        view = CatalogView(catalog)
        catalog._test_view = view
    return view


class _BackendPaths(object):
    """Path → catalog view for listed Trusts backends.

    A backend class lives in one app, so every path whose class is in
    that app shares that app's catalog. Assigning a compiler compiles
    it and stores the catalog on the app config.
    """

    def __init__(self):
        self._order = []

    def _paths(self):
        from django.conf import settings

        found = []
        for path in settings.AUTHENTICATION_BACKENDS:
            if _backend_config(path) is not None:
                found.append(path)
        return tuple(found)

    def __iter__(self):
        return iter(self._paths())

    def __len__(self):
        return len(self._paths())

    def __contains__(self, path):
        return path in self._paths()

    def keys(self):
        return list(self._paths())

    def items(self):
        return [(path, self[path]) for path in self._paths()]

    def __getitem__(self, path):
        config = _backend_config(path)
        if config is None or config.catalog is None:
            raise KeyError(path)
        return catalog_view(config.catalog)

    def __setitem__(self, path, registry):
        config = _backend_config(path)
        if config is None:
            raise KeyError(path)
        catalog = getattr(registry, '_catalog', registry)
        if hasattr(catalog, 'compile') and not hasattr(catalog, 'filter_lookup'):
            catalog = catalog.compile()
        config.catalog = catalog
        clear_backend_cache()

    def pop(self, path, default=None):
        del path
        return default

    def clear(self):
        return None

    def update(self, mapping):
        for path, registry in dict(mapping).items():
            self[path] = registry


def _backend_config(path):
    from django.apps import apps as django_apps
    from django.utils.module_loading import import_string

    from trusts.apps import TrustsConfigMixin as Mixin
    from trusts.backends import TrustModelBackendMixin

    try:
        cls = import_string(path)
    except Exception:
        return None
    if not isinstance(cls, type) or not issubclass(cls, TrustModelBackendMixin):
        return None
    config = django_apps.get_containing_app_config(cls.__module__)
    if not isinstance(config, Mixin):
        return None
    return config


class LiveOwnerView(object):
    """Test view of ``ZeroConfig``.

    ``registry`` is Zero's catalog. ``registries`` maps each listed
    backend path to the catalog of the app that contains that class.
    """

    def __init__(self, config):
        self._config = config
        self.registries = _BackendPaths()
        self._paths_override = None

    def __getattr__(self, name):
        return getattr(self._config, name)

    @property
    def registry(self):
        return catalog_view(self._config.get_catalog())

    @registry.setter
    def registry(self, value):
        catalog = getattr(value, '_catalog', value)
        if hasattr(catalog, 'compile') and not hasattr(catalog, 'filter_lookup'):
            catalog = catalog.compile()
        self._config.catalog = catalog
        clear_backend_cache()

    def configured_handles(self):
        return tuple(configured_backend(path) for path in self._configured_trusts_paths())

    def configured_backend(self, path=None):
        return configured_backend(path)

    @property
    def trusts_backend_paths(self):
        if self._paths_override is not None:
            return self._paths_override
        return self._configured_trusts_paths()

    @trusts_backend_paths.setter
    def trusts_backend_paths(self, value):
        self._paths_override = value

    def _configured_trusts_paths(self):
        if self._paths_override is not None:
            return tuple(self._paths_override)
        return tuple(self.registries)


class BackendView(object):
    """Constructed backend plus the catalog view tests already read.

    ``register`` and ``add_named_filter`` are the app recorder. After
    ``ready`` that recorder is frozen and those calls raise.
    """

    def __init__(self, backend):
        self._backend = backend
        self.catalog = backend.catalog
        self.registry = catalog_view(backend.catalog)
        self.recorder = backend.recorder
        self.path = '%s.%s' % (
            type(backend).__module__, type(backend).__qualname__,
        )
        self.compiler = backend.catalog.compiler
        self.historical_fallback = False

    def __getattr__(self, name):
        return getattr(self._backend, name)

    def register(self, *args, **kwargs):
        return self.recorder.register(*args, **kwargs)

    def add_named_filter(self, *args, **kwargs):
        return self.recorder.add_named_filter(*args, **kwargs)


class IsolatedOwnerConfig(TrustsConfigMixin):
    """Unbound pair-test owner. Not installed; constructed in isolation."""

    name = 'tests'
    label = 'trusts_isolated_owner'
    default = False

    def ready(self):
        if self.recorder.frozen:
            return
        super().ready()

    @property
    def registry(self):
        if self.catalog is None:
            raise TrustsConfigurationError('catalog not built yet')
        return catalog_view(self.catalog)

    @registry.setter
    def registry(self, value):
        catalog = getattr(value, '_catalog', value)
        if hasattr(catalog, 'compile') and not hasattr(catalog, 'filter_lookup'):
            catalog = catalog.compile()
        self.catalog = catalog


def isolated_owner():
    """Construct a standalone mixin config for isolation tests."""
    import tests as tests_module

    return IsolatedOwnerConfig('tests', tests_module)


def live_config(apps_registry=None):
    """Installed ``ZeroConfig`` (label ``trusts``), as a catalog view."""
    from django.apps import apps as django_apps

    registry = django_apps if apps_registry is None else apps_registry
    return LiveOwnerView(registry.get_app_config('trusts'))


def tests_config(apps_registry=None):
    """Installed ``TestsConfig``."""
    from django.apps import apps as django_apps

    registry = django_apps if apps_registry is None else apps_registry
    return registry.get_app_config('trusts_zero_tests')


def live_catalog(apps_registry=None):
    """Zero's built catalog."""
    return live_config(apps_registry).get_catalog()


def tests_catalog(apps_registry=None):
    """Tests app catalog (Category, Ticket, Group)."""
    return tests_config(apps_registry).get_catalog()


def clear_backend_cache():
    """Drop Django's loaded auth backends so the next inquiry rebuilds them.

    A backend copies ``config.catalog`` in ``__init__``. After a test
    swaps a catalog, cached instances would keep the previous one.
    """
    from django.contrib.auth import load_backend
    import django.contrib.auth as auth

    clearer = getattr(load_backend, 'cache_clear', None)
    if clearer is not None:
        clearer()
    for name in ('backend_cache', '_backend_cache'):
        cache = getattr(auth, name, None)
        if isinstance(cache, dict):
            cache.clear()
    from django.contrib.auth import backends as auth_backends
    for name in ('backend_cache', '_backend_cache'):
        cache = getattr(auth_backends, name, None)
        if isinstance(cache, dict):
            cache.clear()


def configured_backend(path=None, apps_registry=None):
    """Construct the backend class at ``path``. Default is Zero's."""
    del apps_registry
    from django.utils.module_loading import import_string

    dotted = ZERO_BACKEND if path is None else path
    return BackendView(import_string(dotted)())


def live_backend(apps_registry=None):
    """Constructed Zero backend. Its catalog is ``ZeroConfig``'s."""
    del apps_registry
    from trusts.zero.backends import TrustModelBackend

    return BackendView(TrustModelBackend())


live_handle = live_backend


def live_registry(apps_registry=None):
    """View of Zero's catalog. Ticket and Category live on ``tests_registry``."""
    return catalog_view(live_catalog(apps_registry))


def tests_registry(apps_registry=None):
    """View of the tests app catalog (Category, Ticket, Group)."""
    return catalog_view(tests_catalog(apps_registry))


@contextmanager
def override_user_on(config, name, expr):
    """Rebuild ``config``'s catalog with a user override, then restore.

    The override is recorded on a fresh compiler before the frozen
    recorder replays ``register``. Plans bake the override in at
    ``compile``; assigning ``catalog.user_override`` afterwards does not.
    """
    compiler = new_compiler(config.catalog_path())
    compiler.set_user_override(name, expr)
    config.recorder.play(compiler)
    built = compiler.compile()
    saved = config.catalog
    config.catalog = built
    clear_backend_cache()
    try:
        yield built
    finally:
        config.catalog = saved
        clear_backend_cache()


def catalog_for_content(model, apps_registry=None):
    """Installed catalog that recorded ``model`` as a content terminal."""
    from django.apps import apps as django_apps

    concrete = getattr(getattr(model, '_meta', None), 'concrete_model', model)
    registry = django_apps if apps_registry is None else apps_registry
    for config in registry.get_app_configs():
        if not isinstance(config, TrustsConfigMixin) or config.catalog is None:
            continue
        catalog = config.get_catalog()
        for record in catalog.records:
            if record.content_model is model or record.content_model is concrete:
                return catalog
        for record in catalog.delegations:
            if record.content_model is model or record.content_model is concrete:
                return catalog
    raise TrustsConfigurationError(
        'No installed catalog records %s.' % getattr(
            getattr(model, '_meta', None), 'label', model,
        )
    )


def publish_permission_condition(model, cond_code, builder_or_expr, registry=None):
    """Register on an unfrozen compiler, then copy the IR onto a catalog.

    After ``ready``, the recorder is frozen and ``add_named_filter``
    raises before a builder runs. Tests that need an extra condition
    copy the resulting record into the catalog lookup. This talks to
    Core's store directly; it is not an application-facing path.
    """
    isolated = new_compiler('tests.publish')
    record = isolated.add_named_filter(model, cond_code, builder_or_expr)
    target = tests_catalog() if registry is None else registry
    if hasattr(target, 'get_catalog'):
        target = target.get_catalog()
    if hasattr(target, 'filter_lookup'):
        key = (model._meta.label, cond_code)
        target.filter_lookup._index[key] = record
        rows = [
            row for row in target.conditions
            if not (row[0] is model and row[1] == cond_code)
        ]
        rows.append((model, cond_code, record))
        target.conditions = tuple(rows)
        return record
    store = getattr(target, 'conditions', target)
    store._records[(model._meta.label, cond_code)] = record
    return record


def publish_donated_conditions(source, target=None):
    """Copy condition IR records from an unfrozen compiler onto a catalog."""
    dest = live_catalog() if target is None else target
    if hasattr(dest, 'get_catalog'):
        dest = dest.get_catalog()
    store = getattr(source, 'conditions', source)
    rows = list(getattr(dest, 'conditions', ()) or ())
    for model, code, record in store.iter_permission_conditions():
        if hasattr(dest, 'filter_lookup'):
            dest.filter_lookup._index[(model._meta.label, code)] = record
        rows = [
            row for row in rows
            if not (row[0] is model and row[1] == code)
        ]
        rows.append((model, code, record))
    if hasattr(dest, 'conditions'):
        dest.conditions = tuple(rows)


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


def junction_group_content_path(prefix, junction_model):
    """Public ``__`` path: TUP/TGP prefix → Trust ← Junction → Group/content."""
    rev = junction_model._meta.get_field('trust').remote_field.get_accessor_name()
    content_name = junction_content_field(junction_model).name
    parts = (prefix, 'trust', rev, content_name)
    return '__'.join(part for part in parts if part)


def isolated_backend(registry=None, path='tests.isolated'):
    """Unfrozen registration target for isolated tests."""
    if registry is not None:
        target = IsolatedTarget(path)
        target._compiler = registry
        return target
    return IsolatedTarget(path)


isolated_handle = isolated_backend


def register_tests_terminals(recorder):
    """Category, Ticket, and Group relations plus Ticket named filters.

    Same log ``TestsConfig.ready`` records. ``recorder`` is an app
    ``Recorder`` or an unfrozen ``Compiler``.
    """
    # Deferred import: tests.models and auth.Group. tests.apps loads in
    # phase 1, before those models exist.
    from django.contrib.auth.models import Group
    from tests.models import (
        Category,
        TestGroupJunction,
        Ticket,
        ticket_meta_own,
        ticket_own,
    )
    from trusts.zero.registration import register_zero_content

    register_zero_content(recorder, Category)
    register_zero_content(recorder, Ticket)
    register_zero_content(
        recorder,
        Group,
        content_via=lambda prefix, model: junction_group_content_path(
            prefix, TestGroupJunction,
        ),
    )
    recorder.add_named_filter(Ticket, 'own', ticket_own)
    recorder.add_named_filter(Ticket, 'meta_own', ticket_meta_own)


class TestsConfig(TrustsConfigMixin):
    name = 'tests'
    label = 'trusts_zero_tests'
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        if getattr(self, 'apps', None) is None:
            return
        if self.recorder.frozen:
            return
        register_tests_terminals(self.recorder)
        super().ready()


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
    """Point ``config.catalog`` at ``registry`` (compiled if it is a compiler).

    A ``LiveOwnerView`` stores the catalog on the wrapped app config.
    Assigning ``view.catalog`` would only shadow the attribute.
    """
    del path
    owner = getattr(config, '_config', config)
    inner = getattr(registry, '_catalog', None)
    if inner is not None and hasattr(inner, 'filter_lookup'):
        registry = inner
    if hasattr(registry, 'compile') and not hasattr(registry, 'filter_lookup'):
        catalog = registry.compile()
    else:
        catalog = registry
    owner.catalog = catalog
    clear_backend_cache()
    return catalog


def install_writable_registry(config, path, contribute=None):
    compiler = new_compiler(path or config.catalog_path())
    if contribute is not None:
        contribute(compiler)
    config.catalog = compiler.compile()
    return compiler


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
    # Deferred import: trusts.zero.models. See TestsConfig.ready.
    from trusts.zero.models import Trust
    from trusts.zero.registration import register_zero_relations, trust_settlor_owns

    if config.recorder.frozen:
        return config
    register_zero_relations(config.recorder)
    config.recorder.add_named_filter(Trust, 'own', predicate=trust_settlor_owns)
    return config


def clone_writable_registry(registry):
    source = getattr(registry, '_compiler', registry)
    cloned = new_compiler(getattr(source, 'path', 'tests.cloned'))
    cloned._by_root = {
        root: list(rows) for root, rows in source._by_root.items()
    }
    cloned._order = list(source._order)
    cloned._delegations_by_root = {
        root: list(rows) for root, rows in source._delegations_by_root.items()
    }
    cloned._delegation_order = list(source._delegation_order)
    return cloned
