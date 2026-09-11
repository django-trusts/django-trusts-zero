from django.db import models
from django.contrib.auth.models import User

from trusts.conditions import condition_refs
from trusts.zero.models import Content

_u, _p, _o = condition_refs()


class Category(Content):
    name = models.CharField(max_length=40, null=False, blank=False)

    class Meta:
        default_permissions = ('add', 'read', 'change', 'delete')


class Ticket(Content):
    title = models.CharField(max_length=40, null=False, blank=False)
    owner = models.ForeignKey(
        User, null=False, blank=False, related_name='zero_tickets',
        on_delete=models.CASCADE,
    )

    class Meta:
        default_permissions = ('add', 'read', 'change', 'delete')
        permission_conditions = (
            ('own', _u == _o.owner),
        )
