# django-trusts-zero

Concrete Django authorization models and compatibility behavior carried
forward from django-trusts 0.x, packaged as an optional implementation of
the django-trusts relational authorization kernel. Unrelated to Zero Trust
network architecture.

## IIa status

This tree is `django-trusts-zero==2.0.0.dev2` against merged core Step I
`django-trusts==1.0.0.dev2`
([django-trusts#109](https://github.com/django-trusts/django-trusts/pull/109)
merge `39f1f9611e214193aec4e97526cf9b54ee689967`).

`trusts.zero.apps.ZeroConfig` is the implementation owner. Core is a
Python dependency only: do **not** list `'trusts'` in `INSTALLED_APPS`.

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

`Requires-Dist`: `django-trusts>=1.0.0.dev2,<2`.

The old settings path `'trusts.backends.TrustModelBackend'` fails at
startup with `ImproperlyConfigured`. Persisted Django app label, migration
keys, tables, ContentTypes, and permissions stay `trusts`.

See `docs/source/index.rst` and `migrates.md`.
