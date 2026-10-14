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
        """Object and global user permissions are not Django's set.

        ``ModelBackend.get_user_permissions`` treats an active superuser
        as holding every permission. Zero does not. Superuser access
        comes only from Core's registered override.
        """
        return set()

    def with_perm(self, perm, is_active=True, include_superusers=True, obj=None):
        """Django users who hold ``perm``, without a superuser grant.

        ``include_superusers`` is accepted so this matches Django's
        signature, and is not forwarded. An active superuser is included
        only when Core's registered override says so.
        """
        return super().with_perm(
            perm, is_active=is_active, include_superusers=False, obj=obj,
        )
