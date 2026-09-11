# django-trusts-zero

Concrete Django authorization models and compatibility behavior carried
forward from django-trusts 0.x, packaged as an optional implementation of
the django-trusts relational authorization kernel. Unrelated to Zero Trust
network architecture.

## Z1 status

This tree reconstitutes historical schema under `trusts.zero` on the merged
C1 public APIs (`AuthorizedQuerySet.authorized`, `filter_authorized_scopes`,
`ConditionLookup`, `kernel_config()`, `TrustsRegistry.register`).

**Do not merge Z1 alone against C1.** Both own `label='trusts'`. Installing
`trusts.zero.apps.ZeroConfig` next to C1 `trusts.apps.AppConfig` is
unsupported and must raise `ImproperlyConfigured` (duplicate application
label). Final merge requires paired C2 (`label='trusts_core'` on the kernel).

Canonical models import:

```python
from trusts.zero.models import Trust, Content, Junction, TrustUserPermission
```

Install (after C2; not valid on C1):

```python
INSTALLED_APPS = [
    'trusts',                       # kernel, label=trusts_core after C2
    'trusts.zero.apps.ZeroConfig',  # models, label=trusts
]
AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'trusts.backends.TrustModelBackend',  # unchanged core path
)
```

See `docs/source/index.rst` and `migrates.md`.
