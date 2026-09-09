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

Until a PyPI release, install from git. This revision is path-installable against the kernel at:

```text
django-trusts @ 624daa198d1922a43c775a814a3ff213cf5bd4d7
```

that SHA is master after [#45](https://github.com/django-trusts/django-trusts/pull/45) (Step 2). The companion kernel Step 3 PR (KernelConfig + `pkgutil.extend_path`, concrete code remaining in-tree until both PRs are reviewed) is documented in `migrates.md`. Update the pin when that PR’s HEAD is known.

```python
INSTALLED_APPS = [
    'trusts.apps.KernelConfig',       # after the kernel Step 3 PR; omit on 624daa1
    'trusts.zero.apps.ZeroConfig',    # required; label='trusts'
]

AUTHENTICATION_BACKENDS = (
    'trusts.zero.backends.TrustModelBackend',
)
```

On kernel `624daa1` the in-tree `trusts.apps.AppConfig` still uses `label='trusts'`. Do **not** install bare `'trusts'` alongside Zero — Django app labels would collide. Install only `trusts.zero.apps.ZeroConfig` until the kernel PR lands. Import kernel APIs (`trusts.context`, `trusts.trustee`, `trusts.path`) as modules either way.

```python
from trusts.zero.models import Trust, Content, Junction, Role
from trusts.zero.backends import TrustModelBackend
from trusts.context import Context
from trusts.trustee import Trustee
```

## Development

```text
export KERNEL_CHECKOUT=/path/to/django-trusts   # 624daa1 or later
python -m pip install -e "$KERNEL_CHECKOUT"
python -m pip install -e .
python -m tests.runtests
python scripts/verify-fresh-install.py
python scripts/verify-legacy-upgrade.py
python scripts/verify-upgrade-current.py
python scripts/verify-install-matrix.py --kernel "$KERNEL_CHECKOUT"
```

Editable+editable installs need `pkgutil.extend_path` on the kernel package. `scripts/apply-kernel-namespace-overlay.py` inserts it when the companion kernel PR has not yet.

## License

BSD-2-Clause. See `LICENSE`.
