from django.apps import AppConfig as DjangoAppConfig


class ZeroConfig(DjangoAppConfig):
    """Historical concrete Trusts app.

    ``name`` is the Python package. ``label`` stays ``trusts`` so migration
    identity, table names, and content-type/permission natural keys remain
    ``('trusts', '0001_initial')`` / ``('trusts', '0002_trustgroup')``.

    Install with the explicit class path ``trusts.zero.apps.ZeroConfig``.
    Bare ``'trusts'`` selects the kernel config; bare ``'trusts.zero'`` is
    forbidden by the 2.0 ``migrates.md`` checklist even when ``default``
    is true.
    """

    name = 'trusts.zero'
    label = 'trusts'
    verbose_name = "Django Trusts Zero"
    default = True
    # Preserve the historical AutoField primary keys from 0001_initial.
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        # admin.py registers core ModelAdmins at import. Only load it when
        # django.contrib.admin is installed so a wheel import without admin
        # still starts.
        from django.apps import apps as django_apps
        if django_apps.is_installed('django.contrib.admin'):
            from trusts.zero.admin import register_auto_modeladmins
            register_auto_modeladmins()
        # Register system checks. Do not validate conditions here: raising
        # from ready() would block shell, migrations, and recovery.
        # Context and Trustee freeze wait until the first authorization
        # query or manage.py check so every INSTALLED_APPS model can
        # register during application loading (ZeroConfig.ready() runs
        # before later apps).
        from trusts.zero import checks as _trusts_zero_checks  # noqa: F401
