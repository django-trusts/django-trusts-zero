# django-trusts-zero

Concrete Django authorization models and compatibility behavior carried
forward from django-trusts 0.x, packaged as an optional implementation of
the django-trusts relational authorization kernel. Unrelated to Zero Trust
network architecture.

## Step IIa status

This tree is `django-trusts-zero==2.0.0.dev2` against merged core Step I
(`django-trusts==1.0.0.dev2`, merge
[`39f1f961`](https://github.com/django-trusts/django-trusts/commit/39f1f9611e214193aec4e97526cf9b54ee689967)).

`ZeroConfig` is the sole implementation owner. Core is a library: do not
list `'trusts'` in `INSTALLED_APPS`. The canonical backend class is
defined in Zero and is not the temporary core historical class.

```python
INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'trusts.zero.apps.ZeroConfig',  # name=trusts.zero, label=trusts
]
AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'trusts.zero.backends.TrustModelBackend',
)
```

Canonical models import:

```python
from trusts.zero.models import Trust, Content, Junction, TrustUserPermission
```

Do not list `'trusts'` or `'trusts.zero'`. Do not keep
`'trusts.backends.TrustModelBackend'` — that path fails at startup.

See `docs/source/index.rst` and `migrates.md`.
