"""Zero-only Meta option names. Import this before host models exist."""

from django.db.models import options


ZERO_META_OPTION_NAMES = (
    'roles',
    'content_roles',
    'content_permission_conditions',
    'auto_modeladmin',
)


def register_zero_meta_option_names():
    """Add Zero-only names to ``options.DEFAULT_NAMES`` once.

    ``permission_conditions`` is registered by importing ``trusts.apps``.
    """
    extra = tuple(
        name for name in ZERO_META_OPTION_NAMES
        if name not in options.DEFAULT_NAMES
    )
    if extra:
        options.DEFAULT_NAMES += extra
    return extra
