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

This package **requires** `django-trusts>=1.0.0.dev0` (kernel 1.x train). Unpinned `django-trusts` resolves to PyPI 0.10.x and does **not** satisfy that pin.

```text
pip install django-trusts
pip install django-trusts-zero
```

Until a 1.x kernel is on PyPI, install the companion kernel first (path, git, or local wheel), then this package **with dependency resolution** (do not `--no-deps`). Coordinated companion:

```text
django-trusts PR #46 @ 68bb89c7199539d82868f908e2e8479cda39a85e
```

`requirements.txt` pins that SHA. Published master after [#45](https://github.com/django-trusts/django-trusts/pull/45) (`624daa198d1922a43c775a814a3ff213cf5bd4d7`) is still 1.0.0.dev0 and can satisfy the pin after `scripts/apply-kernel-namespace-overlay.py`, but it is **not** the paired proof.

[#46](https://github.com/django-trusts/django-trusts/pull/46) adds `KernelConfig` + `pkgutil.extend_path`. Do not assume it has merged. This repository is authoritative for `django-trusts-zero` **2.0.0.dev0**; any retained `packaging/django-trusts-zero/` mirror in the kernel repo must match or `scripts/verify-companion-pair.py` fails.

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
export KERNEL_CHECKOUT=/path/to/django-trusts   # PR #46 @ 68bb89c
python -m pip install -e "$KERNEL_CHECKOUT" --config-settings editable_mode=compat
python -m pip install -e . --config-settings editable_mode=compat
python -m tests.runtests
python scripts/verify-companion-pair.py --kernel "$KERNEL_CHECKOUT"
```

Default setuptools editable mode turns `trusts` into a PEP 420 namespace (`trusts.__file__ is None`) and hides kernel `trusts/__init__.py`. Use `editable_mode=compat` as above. Wheel+wheel into the same `site-packages/trusts/` tree does not need the flag.

Editable+editable also needs `pkgutil.extend_path` on the kernel package. `scripts/apply-kernel-namespace-overlay.py` inserts it on `624daa1`. Companion #46 @ `68bb89c` already has `extend_path` and no longer vendors `trusts/zero/**`.

## License

BSD-2-Clause. See `LICENSE`.
