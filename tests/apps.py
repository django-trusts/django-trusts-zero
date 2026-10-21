from contextlib import contextmanager

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from tests.models import (
    Category,
    Receipt,
    ReceiptImage,
    ReceiptImageMeta,
    TestGroupJunction,
    Ticket,
    ticket_meta_own,
    ticket_own,
)
from trusts.apps import Recorder
from trusts.compile.catalogs import Catalog
from trusts.compile.factory import Compiler
from trusts.errors import TrustsConfigurationError
from trusts.zero.apps import CANONICAL_BACKEND_PATH, zero_config
from trusts.zero.backends import TrustModelBackend
from trusts.zero.models import (
    TrustGroup,
    TrustGroupPermission,
    TrustUserPermission,
)
from trusts.zero.registration import register_zero_content


ZERO_BACKEND = CANONICAL_BACKEND_PATH


class _CallLog(object):
    """Registration-time builder that records its one symbolic call."""

    def __init__(self, impl):
        self.impl = impl
        self.calls = []

    def __call__(self, u, p, o):
        self.calls.append((u, p, o))
        return self.impl(u, p, o)


# Recorded from TestsConfig.ready() before Zero freezes its recorder.
# The catalog build invokes it once. Later has_perm / permitted must not.
category_spy = _CallLog(lambda u, p, o: o.name == 'keep')


def live_config(apps_registry=None):
    """The unique installed ``ZeroConfig``."""
    return zero_config(apps_registry)


def live_catalog():
    """Catalog built for ``TrustModelBackend`` at ready."""
    catalog = TrustModelBackend().get_catalog()
    if catalog is None:
        raise TrustsConfigurationError('Zero backend has no catalog.')
    return catalog


def live_recorder():
    """Recorder for ``TrustModelBackend``'s app config."""
    return TrustModelBackend().recorder


def records_for_root(catalog, root):
    """Records on ``catalog`` whose registration root is ``root``."""
    return tuple(record for record in catalog.records if record.root is root)


def isolated_recorder():
    """A recorder that has not been built into a catalog."""
    return Recorder()


def isolated_compiler(*, path='tests.isolated', user_model=None):
    """A fresh compiler. Register through its public methods, then compile."""
    return Compiler(
        path=path,
        family='relationship',
        user_model=user_model or get_user_model(),
        query_compiler=Compiler.default_query_compiler(),
    )


def catalog_from(compiler):
    """``compiler.compile()``. The compiler freezes here."""
    built = compiler.compile()
    if not isinstance(built, Catalog):
        raise TrustsConfigurationError(
            'Compiler.compile() did not return a Catalog.'
        )
    return built


def catalog_from_recorder(recorder, *, path='tests.isolated', user_model=None):
    """Freeze ``recorder``, replay it, and return the catalog."""
    compiler = isolated_compiler(path=path, user_model=user_model)
    if not recorder.frozen:
        recorder.freeze()
    recorder.play(compiler)
    return compiler.compile()


def isolated_catalog(register=None, *, path='tests.isolated', user_model=None):
    """Build one isolated catalog from public registration calls.

    ``register`` receives the compiler. It uses ``register``,
    ``add_named_filter``, ``set_user_condition``, and
    ``set_user_override``.
    """
    compiler = isolated_compiler(path=path, user_model=user_model)
    if register is not None:
        register(compiler)
    return catalog_from(compiler)


def register_relations(compiler, model, content_via=None):
    """TUP, ``auth.Group``, and role records via ``Compiler.register``.

    Isolated tests that need Zero's relation shape call this. App
    behaviour is ``live_catalog()``.
    """
    def content_path(prefix=''):
        if content_via is not None:
            return content_via(prefix, model)
        rev = model._meta.get_field('trust').remote_field.get_accessor_name()
        return '__'.join(part for part in (prefix, 'trust', rev) if part)

    compiler.register(
        trust=TrustUserPermission,
        user='entity',
        permission='permission',
        content=content_path(),
    )
    compiler.register(
        trust=TrustGroup,
        user='group__user',
        content=content_path(),
        group='group',
        condition=lambda t: t.permissions.contains(t.group.permissions),
    )
    compiler.register(
        trust=TrustGroupPermission,
        user='trustgroup__group__user',
        permission='permission',
        content=content_path('trustgroup'),
        condition=lambda t: t.trustgroup.group.roles.permissions.contains(
            t.permission,
        ),
    )


def root_records(catalog, root, model):
    """Records on ``catalog`` for ``root`` terminating on ``model``."""
    concrete = model._meta.concrete_model
    return tuple(
        record for record in records_for_root(catalog, root)
        if record.content_model is concrete
    )


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


def dependent_content_path(prefix, content_model, *suffixes):
    """Public ``__`` path: Trust reverse onto ``content_model``, then suffixes."""
    rev = content_model._meta.get_field('trust').remote_field.get_accessor_name()
    parts = (prefix, 'trust', rev) + suffixes
    return '__'.join(part for part in parts if part)


def register_installed_terminals(config):
    """Register host terminals on Zero's recorder before the catalog build.

    ``TestsConfig`` is listed before ``ZeroConfig``. A second ``ready()``
    on this app hits the frozen recorder and raises. An isolated Apps
    registry is not the running app, so it returns without recording.
    """
    if config.apps is not django_apps:
        return
    recorder = live_recorder()
    register_zero_content(recorder, Category)
    register_zero_content(recorder, Ticket)
    register_zero_content(
        recorder,
        Group,
        content_via=lambda prefix, model: junction_group_content_path(
            prefix, TestGroupJunction,
        ),
    )
    register_zero_content(
        recorder,
        ReceiptImage,
        content_via=lambda prefix, model: dependent_content_path(
            prefix, Receipt, 'image',
        ),
    )
    register_zero_content(
        recorder,
        ReceiptImageMeta,
        content_via=lambda prefix, model: dependent_content_path(
            prefix, Receipt, 'image', 'image',
        ),
    )
    recorder.add_named_filter(Category, 'spy', category_spy)
    recorder.add_named_filter(Ticket, 'own', ticket_own)
    recorder.add_named_filter(Ticket, 'meta_own', ticket_meta_own)


@contextmanager
def override_apps_ready(ready, apps_registry=None):
    target = django_apps if apps_registry is None else apps_registry
    was = target.ready
    target.ready = ready
    try:
        yield
    finally:
        target.ready = was


def forget_models(*model_classes):
    all_models = django_apps.all_models
    for model in model_classes:
        app_models = all_models.get(model._meta.app_label, {})
        app_models.pop(model._meta.model_name, None)
        for name, existing in list(app_models.items()):
            if existing is model:
                app_models.pop(name, None)
    django_apps.clear_cache()
