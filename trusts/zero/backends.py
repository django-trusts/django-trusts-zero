"""Canonical Zero authentication backend (Step IIa).

Defined here as a distinct class object. Do not alias or re-export
``trusts.backends.TrustModelBackend``; that temporary core historical
class is a different identity and is not listed in
``ZeroConfig.trusts_backend_paths``.
"""

from django.contrib.auth.backends import ModelBackend

from trusts.backends import TrustModelBackendMixin
from trusts.core import PlanQueryCompiler


class TrustModelBackend(TrustModelBackendMixin, ModelBackend):
    """Durable Zero backend. Registry identity is this class object.

    Uses Core ``PlanQueryCompiler``. Explicit ``group=`` ceilings share
    one ``Group.permissions`` join in Core. This backend does not keep a
    second compiler and does not infer a group from a membership-shaped
    path.
    """

    query_compiler = PlanQueryCompiler()

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
        registry. Trusts grants and overrides come from Core's
        ``get_permitted_users``.
        """
        return super().with_perm(
            perm, is_active=is_active, include_superusers=False, obj=obj,
        )
