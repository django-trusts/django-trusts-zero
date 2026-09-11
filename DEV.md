# DEV.md — internal / transitional record

This file is an internal development record. It may describe
unsupported or superseded states. The user-facing package introduction
is [README.md](README.md). `pyproject.toml` long-description metadata
points at `README.md`, not this file.

## Current pairing

This tree is `django-trusts-zero==1.0.0.dev0` against the final core
library cut `django-trusts==1.0.0.dev3`
([django-trusts#112](https://github.com/django-trusts/django-trusts/pull/112)
merge `11058641b533e0f8489598e0b1f5cbe5d42a81db`).

Earlier unpublished Zero snapshots used `2.0.0.dev0` / `dev1` / `dev2`.
Those values are not a public compatibility line.

`trusts.zero.apps.ZeroConfig` is the implementation owner. Core is a
Python dependency only: do **not** list `'trusts'` in `INSTALLED_APPS`.
Final core ships no Django `AppConfig`, no `kernel_config()`, and no
`trusts.backends.TrustModelBackend`. The mixin stays at
`trusts.backends.TrustModelBackendMixin`. The historical backend class
lives only at `trusts.zero.backends.TrustModelBackend`.

Canonical imports and settings:

```python
from trusts.zero.models import Trust, Content, Junction, TrustUserPermission
from trusts.zero.backends import TrustModelBackend

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'trusts.zero.apps.ZeroConfig',
]
AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'trusts.zero.backends.TrustModelBackend',
)
```

`Requires-Dist`: `django-trusts>=1.0.0.dev3,<2`.

The old settings path `'trusts.backends.TrustModelBackend'` fails at
startup with `ImproperlyConfigured`. Persisted Django app label,
migration keys, tables, ContentTypes, and permissions stay `trusts`.

See `docs/source/index.rst` and `migrates.md`.

## Verification

Pair CI pins exact core merge `11058641b533e0f8489598e0b1f5cbe5d42a81db`.
The Zero suite, fresh-install, old-path fail-closed, wheel RECORD, and
uninstall-isolation scripts must run against that revision without
skipping modules that formerly imported `kernel_config()` or a core
`AppConfig`.

## License

BSD-2-Clause. Copyright holder is exactly BeeDesk, Inc. Notice years
are 2015-2026.
