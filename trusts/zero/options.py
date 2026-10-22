"""Zero-only Meta option names. Import this before host models exist."""

from django.db.models import options


ZERO_META_OPTION_NAMES = (
    'roles',
    'content_roles',
    'auto_modeladmin',
)


def register_zero_meta_option_names():
    """Add Zero-only names to ``options.DEFAULT_NAMES`` once.

    Named filters are ``get_registry().add_named_filter``.
    ``permission_conditions`` and ``content_permission_conditions`` are
    not Meta options.
    """
    extra = tuple(
        name for name in ZERO_META_OPTION_NAMES
        if name not in options.DEFAULT_NAMES
    )
    if extra:
        options.DEFAULT_NAMES += extra
    return extra
