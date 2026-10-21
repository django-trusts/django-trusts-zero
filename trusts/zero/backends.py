"""Canonical Zero authentication backend (Step IIa).

Defined here as a distinct class object. Do not alias or re-export
``trusts.backends.TrustModelBackend``; that temporary core historical
class is a different identity.

The catalog belongs to ``ZeroConfig``. ``TrustModelBackendMixin``
loads it from the app config that contains this module
(``apps.get_containing_app_config``). This class does not store a
query compiler; Core compiles the catalog with the app config's
compiler, defaulting to the plan compiler.
"""

from django.contrib.auth.backends import ModelBackend

from trusts.backends import TrustModelBackendMixin


class TrustModelBackend(TrustModelBackendMixin, ModelBackend):
    """Durable Zero backend. Inquiry reads ``ZeroConfig``'s catalog.

    Explicit ``group=`` ceilings share one ``Group.permissions`` join
    in Core. This backend does not keep a second compiler and does not
    infer a group from a membership-shaped path.
    """

    def get_user_permissions(self, user_obj, obj=None):
        """Direct ``user_permissions``, without the active-superuser shortcut.

        An ordinary user keeps the permissions assigned on
        ``user_permissions``. An active superuser does not receive every
        permission. Inactive, anonymous, and object checks stay empty.
        """
        if not user_obj.is_active or user_obj.is_anonymous or obj is not None:
            return set()
        if user_obj.is_superuser:
            perms = self._get_user_permissions(user_obj)
            return {
                '%s.%s' % (app_label, codename)
                for app_label, codename in perms.values_list(
                    'content_type__app_label', 'codename',
                ).order_by()
            }
        return super().get_user_permissions(user_obj, obj)

    def with_perm(self, perm, is_active=True, include_superusers=True, obj=None):
        """Django direct and group permissions only, with no superuser shortcut.

        ``include_superusers`` is accepted so this matches Django's
        signature. It is not forwarded. This method does not read Core's
        catalog. Trusts grants and overrides come from Core's
        ``get_permitted_users``.
        """
        return super().with_perm(
            perm, is_active=is_active, include_superusers=False, obj=obj,
        )
