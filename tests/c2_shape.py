"""Emulate the future C2 kernel topology against merged C1.

C1 ``AppConfig.label`` is still ``trusts``. Z1 ``ZeroConfig.label`` is
also ``trusts``. Django rejects that pair before ``ready()``. C2 will
flip the kernel to ``label='trusts_core'``, replace ``trusts.models``
with a PEP 562 shim, leave Trust-as-content donation, and retarget
backend/check registry lookups to ``kernel_config()``.

Until a C2 branch exists, tests and verify scripts apply this shape so
Z1 can populate beside C1 public APIs. A real C2 head
(``AppConfig.label == 'trusts_core'``) is detected and left alone.

``apply()`` must run before ``django.setup()`` and must not import
``trusts.models`` / ``trusts.backends`` / ``trusts.checks``.
``patch_runtime()`` runs after ``django.setup()``.
"""

from __future__ import annotations

import os
import sys
import types


def kernel_is_c2():
    from trusts.apps import AppConfig
    return getattr(AppConfig, 'label', None) == 'trusts_core'


def apply():
    """Patch C1 label/donation and install a lazy models shim. No-op on C2."""
    if os.environ.get('TRUSTS_ZERO_SKIP_C2_SHAPE') == '1':
        return False
    from trusts.apps import AppConfig
    if getattr(AppConfig, 'label', None) == 'trusts_core' and os.environ.get(
        'TRUSTS_ZERO_C2_SHAPE_APPLIED'
    ) != '1':
        # Product C2 already has the final label.
        return False

    AppConfig.label = 'trusts_core'
    AppConfig._donate_package_trust_as_content = lambda self, path: None
    os.environ['TRUSTS_ZERO_C2_SHAPE_APPLIED'] = '1'

    import importlib.machinery

    shim = types.ModuleType('trusts.models')
    spec = importlib.machinery.ModuleSpec(
        'trusts.models', loader=None, origin='tests.c2_shape.shim',
    )
    spec.has_location = False
    shim.__spec__ = spec
    shim.__file__ = 'tests.c2_shape.shim'
    shim.__loader__ = None
    shim.__package__ = 'trusts'
    shim.__doc__ = (
        'C2-shape compatibility shim used by Z1 tests against C1. '
        'Not a Django model module.'
    )
    shim.__all__ = (
        'Content', 'Junction', 'Trust', 'TrustUserPermission', 'TrustGroup',
        'TrustGroupPermission', 'Role', 'RolePermission', 'ReadonlyFieldsMixin',
        'PermissionConditionNotQueryable',
    )
    shim._ZERO_MODELS = None

    def _zero_models():
        if shim._ZERO_MODELS is None:
            from trusts.zero import models as zero_models
            shim._ZERO_MODELS = zero_models
        return shim._ZERO_MODELS

    def __getattr__(name):
        return getattr(_zero_models(), name)

    def __dir__():
        names = set(shim.__all__)
        try:
            names.update(dir(_zero_models()))
        except Exception:
            pass
        return sorted(names)

    shim.__getattr__ = __getattr__
    shim.__dir__ = __dir__
    sys.modules['trusts.models'] = shim
    import trusts
    trusts.models = shim
    return True


def patch_runtime():
    """Retarget C1 backend/checks registry lookups to ``kernel_config()``."""
    if os.environ.get('TRUSTS_ZERO_SKIP_C2_SHAPE') == '1':
        return False
    if os.environ.get('TRUSTS_ZERO_C2_SHAPE_APPLIED') != '1':
        return False

    from trusts.apps import kernel_config
    from trusts.backends import TrustModelBackendMixin

    def _trusts_config(self):
        return kernel_config()

    TrustModelBackendMixin._trusts_config = _trusts_config

    import trusts.checks as checks_mod

    orig_covered = checks_mod._covered_content_models
    orig_along = getattr(checks_mod, '_live_along_records', None)

    def _covered_content_models(config):
        return orig_covered(kernel_config())

    checks_mod._covered_content_models = _covered_content_models
    if orig_along is not None:
        def _live_along_records(config):
            return orig_along(kernel_config())
        checks_mod._live_along_records = _live_along_records
    return True
