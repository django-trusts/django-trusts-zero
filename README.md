# django-trusts-zero

[![Coverage](https://coveralls.io/repos/github/django-trusts/django-trusts-zero/badge.svg?branch=dev)](https://coveralls.io/github/django-trusts/django-trusts-zero?branch=dev)

`django-trusts-zero` is the concrete continuation of django-trusts 0.x.
Use it when you want the historical Trust/Content models, stored
identities, and migration path from that line.

The package name refers to this 0.x continuation. It is unrelated to
Zero Trust networking.

## Install

```bash
pip install django-trusts-zero
```

`django-trusts` arrives automatically as a dependency. Do **not** add `'trusts'` to `INSTALLED_APPS`. Core is a Python library, not a Django app.

## Configure

These imports and settings match the project's verified test
configuration:

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

`ZeroConfig` keeps the historical Django app label `trusts`. Existing
databases keep migration keys `0001_initial` and `0002_trustgroup`,
plus the same tables, content types, and permissions.

## Models

- `Trust` — organization/scope tree, including the self-referential root
- `Content` — abstract mixin for rows protected by a Trust
- `Junction` — optional through-model when content is not itself a Trust
- `TrustUserPermission`, `TrustGroup`, `TrustGroupPermission`, `Role` —
  stored grants

Object checks use Django's `user.has_perm(...)`. List filtering uses
the historical codec:

```python
from trusts.zero.models import Trust

Trust.objects.permitted('change', request.user)
```

That call is exercised by the project's smoke and codec tests.

## Supported versions

- Python 3.12, 3.13, and 3.14
- Django 6.1
- django-trusts 1.x, installed as a dependency

## Known limitations

- Callable permission conditions stay object-only. Queryset APIs
  (`permitted`, `filter_by_user_content_perm`) refuse them so they
  cannot silently over-grant.
- `TRUSTS_GROUP_MODEL` and `TRUSTS_PERMISSION_MODEL` no longer swap
  field targets.
- Convenience writers such as `Content.grant` and
  `Trust.associate_group` are gone. Create or delete
  `TrustUserPermission` / `TrustGroupPermission` rows (and
  `Trust.groups`) directly.
- This is a development release of the 0.x continuation, not a
  declared stable 1.0.

## Migration and API

- [migrates.md](migrates.md) — 0.x to `django-trusts-zero` checklist
- [docs/source/index.rst](docs/source/index.rst) — API notes
- [django-trusts](https://github.com/django-trusts/django-trusts) — core library
- [Issues](https://github.com/django-trusts/django-trusts-zero/issues)

Contributor and build history lives in [DEV.md](DEV.md).

Licensed under the BSD 2-Clause License. Copyright BeeDesk, Inc.
