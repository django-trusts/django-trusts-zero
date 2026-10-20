from contextlib import contextmanager

from django.apps import AppConfig

from trusts.errors import TrustsConfigurationError
from trusts.zero.apps import CANONICAL_BACKEND_PATH


ZERO_BACKEND = CANONICAL_BACKEND_PATH


def live_config(apps_registry=None):
    """The unique installed ``ZeroConfig``."""
    from trusts.zero.apps import zero_config

    return zero_config(apps_registry)


def live_catalog():
    """Catalog built for ``TrustModelBackend`` at ready."""
    from trusts.zero.backends import TrustModelBackend

    catalog = TrustModelBackend().get_catalog()
    if catalog is None:
        raise TrustsConfigurationError('Zero backend has no catalog.')
    return catalog


def live_recorder():
    """Open or frozen recorder for ``TrustModelBackend``."""
    from trusts.zero.backends import TrustModelBackend

    return TrustModelBackend().get_registry()


def records_for_root(catalog, root):
    """Records on ``catalog`` whose registration root is ``root``."""
    return tuple(record for record in catalog.records if record.root is root)


def isolated_recorder():
    """A recorder that has not been built into a catalog."""
    from trusts.backends import Recorder

    return Recorder()


def build_catalog(contribute=None, *, recorder=None, user_model=None,
                  path='tests.isolated'):
    """Build ``Catalog(factory.build())`` from one recorder.

    ``contribute`` is called with the recorder before the build. The
    returned catalog does not share the factory.
    """
    from django.contrib.auth import get_user_model

    from trusts.compile.catalogs import Catalog
    from trusts.compile.factory import compile_recorder
    from trusts.plan.relations import PlanQueryCompiler

    target = isolated_recorder() if recorder is None else recorder
    if contribute is not None:
        contribute(target)
    shape = compile_recorder(
        target,
        path=path,
        family='relationship',
        compiler=PlanQueryCompiler(),
        user_model=user_model or get_user_model(),
    )
    return Catalog(shape)


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


class TestsConfig(AppConfig):
    name = 'tests'
    label = 'trusts_zero_tests'
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        # Register test terminals on Zero's recorder before ZeroConfig
        # builds the catalog. An isolated Apps instance, or a recorder
        # the sweep already froze, must not record again.
        if getattr(self, 'apps', None) is None:
            return
        from django.apps import apps as django_apps

        if self.apps is not django_apps:
            return
        recorder = live_recorder()
        if recorder.frozen:
            return
        try:
            from django.contrib.auth.models import Group
            from tests.models import Category, TestGroupJunction, Ticket
            from trusts.zero.registration import register_zero_content
        except ImportError:
            return

        if not getattr(self, '_trusts_tup_category_done', False):
            register_zero_content(recorder, Category)
            self._trusts_tup_category_done = True
        if not getattr(self, '_trusts_tup_ticket_done', False):
            register_zero_content(recorder, Ticket)
            self._trusts_tup_ticket_done = True
        if not getattr(self, '_trusts_tup_group_done', False):
            register_zero_content(
                recorder,
                Group,
                content_via=lambda prefix, model: junction_group_content_path(
                    prefix, TestGroupJunction,
                ),
            )
            self._trusts_tup_group_done = True


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
