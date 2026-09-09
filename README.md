# django-trusts-zero

Concrete Django authorization models and compatibility behavior carried forward from django-trusts 0.x, packaged as an optional implementation of the django-trusts relational authorization kernel. Unrelated to Zero Trust network architecture.

## What this package is

| | Kernel | This add-on |
| --- | --- | --- |
| Distribution | `django-trusts` | `django-trusts-zero` |
| Import | `trusts` | `trusts.zero` |
| Django app | `trusts.apps.KernelConfig` (`name='trusts'`, `label='trusts_kernel'`, no migrations) | `trusts.zero.apps.ZeroConfig` (`name='trusts.zero'`, **`label='trusts'`**, owns `0001_initial` / `0002_trustgroup`) |

Zero contributes **only** `trusts/zero/**`. It does not ship `trusts/__init__.py` or any other kernel-owned path. Historical Django identity (app label `trusts`, table names, content-type/permission natural keys) is preserved so existing databases do not copy or recreate authorization rows.

This is Step 3 of [django-trusts#43](https://github.com/django-trusts/django-trusts/issues/43) (`noun-independent-kernel-r3`). Do not close #43 from this PR.

## Install

```text
pip install django-trusts
pip install django-trusts-zero
```

Until a PyPI release, install from git. This revision is path-installable against:

```text
django-trusts master @ 624daa198d1922a43c775a814a3ff213cf5bd4d7   # after #45
companion kernel PR #46 @ 60ec3c6499de1c67e27e461de8b80f1d91368c0b
```

[#46](https://github.com/django-trusts/django-trusts/pull/46) adds `KernelConfig` + `pkgutil.extend_path` and keeps in-tree `trusts/zero/**` until both Drafts are reviewed. Do not assume it has merged. `requirements.txt` pins master `624daa1` so an unpinned `django-trusts` extra cannot resolve to PyPI 0.10.x.

```python
INSTALLED_APPS = [
    'trusts.apps.KernelConfig',       # after kernel PR #46; omit on 624daa1
    'trusts.zero.apps.ZeroConfig',    # required; label='trusts'
]

AUTHENTICATION_BACKENDS = (
    'trusts.zero.backends.TrustModelBackend',
)
```

On kernel `624daa1` the in-tree `trusts.apps.AppConfig` still uses `label='trusts'`. Do **not** install bare `'trusts'` alongside Zero — Django app labels would collide. Install only `trusts.zero.apps.ZeroConfig` until #46 lands. Import kernel APIs (`trusts.context`, `trusts.trustee`, `trusts.path`) as modules either way.

```python
from trusts.zero.models import Trust, Content, Junction, Role
from trusts.zero.backends import TrustModelBackend
from trusts.context import Context
from trusts.trustee import Trustee
```

## Development

```text
export KERNEL_CHECKOUT=/path/to/django-trusts   # 624daa1 or PR #46 @ 60ec3c6
python -m pip install -e "$KERNEL_CHECKOUT" --config-settings editable_mode=compat
python -m pip install -e . --no-deps --config-settings editable_mode=compat
python -m tests.runtests
python scripts/verify-fresh-install.py
python scripts/verify-legacy-upgrade.py
python scripts/verify-upgrade-current.py
python scripts/verify-install-matrix.py --kernel "$KERNEL_CHECKOUT"
```

Default setuptools editable mode turns `trusts` into a PEP 420 namespace (`trusts.__file__ is None`) and hides kernel `trusts/__init__.py`. Use `editable_mode=compat` as above. Wheel+wheel into the same `site-packages/trusts/` tree does not need the flag.

Editable+editable also needs `pkgutil.extend_path` on the kernel package. `scripts/apply-kernel-namespace-overlay.py` inserts it on `624daa1`. On #46 it is already present; pass `--strip-in-tree-zero` so the kernel checkout’s remaining `trusts/zero/**` does not shadow this package.

## License

BSD-2-Clause. See `LICENSE`.
