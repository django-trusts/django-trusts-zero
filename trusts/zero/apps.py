from django.apps import AppConfig as DjangoAppConfig


class ZeroConfig(DjangoAppConfig):
    """Historical concrete Trusts app.

    ``name`` is the Python package. ``label`` stays ``trusts`` so migration
    identity, table names, and content-type/permission natural keys remain
    ``('trusts', '0001_initial')`` / ``('trusts', '0002_trustgroup')``.

    Install with the explicit class path ``trusts.zero.apps.ZeroConfig``.
    Bare ``'trusts'`` selects the kernel config. Bare ``'trusts.zero'`` is
    forbidden by the 2.0 ``migrates.md`` checklist even when ``default``
    is true.

    Z1 must not be installed next to C1: both own ``label='trusts'``.
    Django raises ``ImproperlyConfigured`` before ``ready()``. Final
    merge requires paired C2 (kernel ``label='trusts_core'``).
    """

    name = 'trusts.zero'
    label = 'trusts'
    verbose_name = "Django Trusts Zero"
    default = True
    # Preserve the historical AutoField primary keys from 0001_initial.
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        from django.apps import apps as django_apps

        if django_apps.is_installed('django.contrib.admin'):
            from trusts.zero.admin import register_auto_modeladmins
            register_auto_modeladmins()

        # Package TUP + TGP registration and ConditionLookup bind live
        # on the kernel store (C1 ``kernel_config()``). Missing kernel
        # is an incomplete install; schema/migrate still start.
        try:
            from trusts.apps import kernel_config
            config = kernel_config()
        except LookupError:
            return

        from trusts.zero.models import ContentConditionLookup, register_zero_relations

        for handle in config.configured_handles():
            register_zero_relations(handle.registry)
            handle.registry.set_condition_lookup(ContentConditionLookup())
