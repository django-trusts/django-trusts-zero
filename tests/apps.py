"""Registration and public policy helpers for the Zero suite.

``TestsConfig.ready`` calls ``register_test_terminals`` on its own
recorder. Helpers below read ``policy_document`` or forget dynamic
models. They do not build catalogs.
"""

from django.apps import apps as django_apps
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
from trusts.backends import policy_document
from trusts.zero.registration import register_zero_content


TEST_BACKEND = 'tests.backends.TestsBackend'
ZERO_BACKEND = 'trusts.zero.backends.TrustModelBackend'


class _CallLog(object):
    """Registration-time builder that records its one symbolic call."""

    def __init__(self, impl):
        self.impl = impl
        self.calls = []

    def __call__(self, u, p, o):
        self.calls.append((u, p, o))
        return self.impl(u, p, o)


# Recorded from TestsConfig.ready(). The catalog build invokes it once.
# Later has_perm / permitted must not.
category_spy = _CallLog(lambda u, p, o: o.name == 'keep')


def junction_content_field(junction_model):
    """Return the Junction→content field from the concrete Junction contract."""
    from trusts.errors import TrustsConfigurationError

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


def register_test_terminals(recorder):
    """Category, Ticket, Group, and dependent image terminals on this recorder."""
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


def policy_rows(backend=None):
    """Content rows from ``policy_document``, one backend or the project."""
    document = policy_document(backend=backend)
    rows = []
    for item in document['backends']:
        for row in item['contents']:
            rows.append(row)
    return rows


def content_row(model, backend=None):
    """The policy row for ``model``, or ``None``."""
    label = model if isinstance(model, str) else model._meta.label
    for row in policy_rows(backend):
        if row['model'] == label:
            return row
    return None


def trust_rows(model, root=None, backend=None):
    """Trust rows on ``model``. ``root`` is a model or a label."""
    row = content_row(model, backend=backend) or {}
    trusts = tuple(row.get('trusts', ()))
    if root is None:
        return trusts
    label = root if isinstance(root, str) else root._meta.label
    return tuple(item for item in trusts if item['root'] == label)


def named_filter_ids(model, backend=None):
    """Named-filter ids recorded for ``model``."""
    row = content_row(model, backend=backend) or {}
    return tuple(item['id'] for item in row.get('named_filters', ()))


def forget_models(*model_classes):
    all_models = django_apps.all_models
    for model in model_classes:
        app_models = all_models.get(model._meta.app_label, {})
        app_models.pop(model._meta.model_name, None)
        for name, existing in list(app_models.items()):
            if existing is model:
                app_models.pop(name, None)
    django_apps.clear_cache()
