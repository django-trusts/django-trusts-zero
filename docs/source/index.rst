django-trusts-zero IIa
======================

Concrete 0.x Trusts models under ``trusts.zero``, owned by
``trusts.zero.apps.ZeroConfig`` on the merged django-trusts Step I
public owner API. Unrelated to Zero Trust network architecture.

This is **Step IIa** of the approved
`#102 r3–r5 staircase <https://github.com/django-trusts/django-trusts/issues/102#issuecomment-5639018377>`_.
Package version is exactly ``2.0.0.dev2``. Core floor is
``django-trusts>=1.0.0.dev2,<2`` (merged
`#109 <https://github.com/django-trusts/django-trusts/pull/109>`_ at
``39f1f9611e214193aec4e97526cf9b54ee689967``).

Step I public APIs consumed
---------------------------

* ``trusts.apps.TrustsImplementationConfig``
* ``trusts.apps.implementation_configs`` /
  ``implementation_for_path`` / ``implementation_for_class``
* ``trusts.backends.TrustModelBackendMixin``
* ``trusts.query.AuthorizedQuerySet`` / ``historical_group_grant_exists`` /
  ``trust_grant_q``
* ``trusts.core.Ref`` / ``TrustsRegistry.register`` / ``granted`` /
  ``filter_authorized_scopes`` / ``ConditionLookup``

Supported IIa execution does **not** call ``trusts.apps.kernel_config()``
and does **not** install a core ``AppConfig``.

Zero-owned surfaces
-------------------

* Concrete models at ``trusts.zero.models`` with ``ZeroConfig.label = 'trusts'``
* Canonical backend ``trusts.zero.backends.TrustModelBackend`` (a distinct
  class, not an alias of the temporary core historical class)
* ``ContentQuerySet.permitted(perm, user)`` — Django-permission codec over
  Zero-owned ``.authorized``
* ``Model.objects.get_permission(...)``
* ``Trust.objects.get_or_create_settlor_default`` / ``get_root`` /
  ``filter_by_user_perm`` / ``filter_by_user_content_perm``
* ``Content.register_permission_condition`` and ``:condition`` overlay via
  ``ContentConditionLookup`` bound from ``ZeroConfig.ready()``
* Historical migrations ``trusts.0001_initial`` / ``trusts.0002_trustgroup``

Installation (IIa)
------------------

::

   INSTALLED_APPS = [
       'django.contrib.contenttypes',
       'django.contrib.auth',
       'trusts.zero.apps.ZeroConfig',  # models + owner, label=trusts
   ]
   AUTHENTICATION_BACKENDS = (
       'django.contrib.auth.backends.ModelBackend',  # optional global
       'trusts.zero.backends.TrustModelBackend',     # canonical Zero path
   )

Forbidden
---------

* ``'trusts'`` in ``INSTALLED_APPS`` (core is a library, not an app)
* ``AUTHENTICATION_BACKENDS = ['trusts.backends.TrustModelBackend']``
  (temporary core historical class; IIa startup ``ImproperlyConfigured``)
* Bare ``'trusts.zero'`` as a substitute for ``trusts.zero.apps.ZeroConfig``
* ``from trusts.backends import TrustModelBackend`` as Zero's identity
* Transparent forwarding from the old core backend path onto Zero's registry

Old / new startup
-----------------

* **Old (Z1 / ``2.0.0.dev0``):** ``INSTALLED_APPS`` listed ``'trusts'`` then
  ``ZeroConfig``; ``AUTHENTICATION_BACKENDS`` listed
  ``trusts.backends.TrustModelBackend``; ``ZeroConfig.ready()`` swallowed
  ``kernel_config()`` ``LookupError``.
* **New (IIa / ``2.0.0.dev2``):** ``INSTALLED_APPS`` lists only
  ``trusts.zero.apps.ZeroConfig``; ``AUTHENTICATION_BACKENDS`` lists
  ``trusts.zero.backends.TrustModelBackend``; missing canonical path,
  leftover core path, or core below ``1.0.0.dev2`` raise
  ``ImproperlyConfigured`` naming the floor / canonical path.

Persisted Django identity is unchanged: ``label='trusts'``, loader keys
``trusts.0001_initial`` / ``trusts.0002_trustgroup``, tables
``trusts_*``, ContentTypes ``trusts | trust`` (and siblings), permission
codenames.

Authorized list filtering
-------------------------

::

   from trusts.zero.models import Trust

   Trust.objects.permitted('change', request.user)
   Trust.objects.get_permission('change')
   Trust.objects.filter_by_user_content_perm(request.user, Receipt, 'add')

``.permitted`` does not sequence grant plans itself. It resolves the
Django permission codec (active principal, optional ``:condition``,
``get_permission``) and delegates to ``.authorized`` on Zero-owned
handles.

TUP + TGP registration
----------------------

``ZeroConfig.ready()`` registers Trust-as-content TUP records on
``implementation_for_path('trusts.zero.backends.TrustModelBackend').configured_backend(...).registry``
using ``Ref`` / ``register()``. TGP membership/ceiling records are
attempted on the same public API. Host Content subclasses donate from
their ``AppConfig.ready()`` through the same owner path, never
``kernel_config()``.

Group list/object grants continue through Zero's
``HistoricalGroupQueryCompiler``.

Direct ORM writes (r7 deletion map)
-----------------------------------

Write conveniences are gone in 2.0: ``Content.grant`` / ``revoke``,
``Trust.associate_group`` / ``grant_group_permission`` /
``revoke_group_permission`` / ``set_group_permissions``, and
``TrustGroup.grant_permission`` / ``revoke_permission`` /
``set_permissions``. Ceiling integrity stays on
``TrustGroupPermission.clean`` / ``save`` / ``bulk_create``.

::

   from django.contrib.auth.models import Group
   from trusts.zero.models import (
       TrustGroup, TrustGroupPermission, TrustUserPermission,
   )

   perm = Receipt.objects.get_permission('read')

   # trustee grant / revoke
   TrustUserPermission.objects.get_or_create(
       trust=receipt.trust, entity=trustee, permission=perm)
   TrustUserPermission.objects.filter(
       trust=receipt.trust, entity=trustee, permission=perm).delete()
   TrustUserPermission.objects.filter(
       trust=receipt.trust, entity=trustee).delete()  # former perm=None

   # associate / disassociate
   trust.groups.add(accountants)
   trust.groups.remove(accountants)

   # local group grant / revoke / set
   tg, _created = TrustGroup.objects.get_or_create(
       trust=trust, group=accountants)
   TrustGroupPermission.objects.get_or_create(
       trustgroup=tg, permission=perm)
   TrustGroupPermission.objects.filter(
       trustgroup=tg, permission=perm).delete()

   # membership / ceiling
   accountants.user_set.add(user)
   accountants.permissions.add(perm)

Create-under-Trust (``filter_by_user_content_perm``) resolves the
permission on the **requested content model** (``add_category``, not
``add_trust``).
