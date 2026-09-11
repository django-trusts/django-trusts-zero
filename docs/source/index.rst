django-trusts-zero Z1
=====================

Concrete 0.x Trusts models reconstituted under ``trusts.zero`` on the
merged django-trusts C1 public APIs. Unrelated to Zero Trust network
architecture.

This is the **Z1 half** of the accepted
`#54 metadata-registration-r9 <https://github.com/django-trusts/django-trusts/issues/54#issuecomment-5631618250>`_
cutover. It must **not** merge alone against C1.

C1 public APIs consumed
-----------------------

* ``trusts.query.AuthorizedQuerySet.authorized(user, permission, extra_q=None)``
* ``trusts.core.filter_authorized_scopes``
* ``trusts.core.ConditionLookup`` / ``TrustsRegistry.set_condition_lookup``
* ``trusts.core.Ref`` / ``TrustsRegistry.register``
* ``trusts.apps.kernel_config()``
* ``trusts.backends.TrustModelBackend`` (unchanged dotted path)

Zero-owned surfaces
-------------------

* Concrete models at ``trusts.zero.models`` with ``ZeroConfig.label = 'trusts'``
* ``ContentQuerySet.permitted(perm, user)`` — one-line codec over ``.authorized``
* ``Model.objects.get_permission(...)``
* ``Trust.objects.get_or_create_settlor_default`` / ``get_root`` /
  ``filter_by_user_perm`` / ``filter_by_user_content_perm``
* ``Content.register_permission_condition`` and ``:condition`` overlay via
  ``ContentConditionLookup`` bound from ``ZeroConfig.ready()``
* Historical migrations ``trusts.0001_initial`` / ``trusts.0002_trustgroup``

Installation (paired C2+Z1 only)
--------------------------------

::

   INSTALLED_APPS = [
       'trusts',                       # kernel, label=trusts_core after C2
       'trusts.zero.apps.ZeroConfig',  # models, label=trusts
   ]
   AUTHENTICATION_BACKENDS = (
       'django.contrib.auth.backends.ModelBackend',  # optional global
       'trusts.backends.TrustModelBackend',          # unchanged path
   )

Bare ``'trusts.zero'`` is forbidden. Bare ``'trusts'`` after C2 is the
kernel and no longer carries 0.x models.

Negative duplicate-label gate
-----------------------------

C1 still owns ``label='trusts'``. Installing Z1 with C1 is
``ImproperlyConfigured`` before ``ready()``. That combination is
unsupported, not a “fix later”.

Authorized list filtering
-------------------------

::

   from trusts.zero.models import Trust

   Trust.objects.permitted('change', request.user)
   Trust.objects.get_permission('change')
   Trust.objects.filter_by_user_content_perm(request.user, Receipt, 'add')

``.permitted`` does not sequence grant plans. It resolves the Django
permission codec (active principal, optional ``:condition``,
``get_permission``) and delegates to ``.authorized``.

TUP + TGP registration
----------------------

``ZeroConfig.ready()`` registers Trust-as-content TUP records on
``kernel_config().configured_handles()`` using C1 ``Ref`` /
``register()``. TGP membership/ceiling records are attempted on the same
public API. Merged C1 user paths are still one direct hop, so TGP
``user_set`` registration is rejected until a later core grammar
widening; group list/object grants on C1 continue through
``HistoricalGroupQueryCompiler``. Zero does not copy that compiler.

Host Content subclasses still contribute their own TUP ``register()``
lines from their ``AppConfig.ready()``, using ``kernel_config()``.
