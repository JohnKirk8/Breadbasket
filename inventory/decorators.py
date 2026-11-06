"""
Simple role-based access control on top of Django's built-in auth Groups.

Instead of writing your own login/permission system, we assign every user
to one of three Groups from the Django admin: "Admin", "Baker",
"Inventory Staff" (see settings.ROLE_ADMIN / ROLE_BAKER / ROLE_INVENTORY).
Superusers (created with createsuperuser) automatically pass every check.
"""

from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def user_in_roles(user, *roles):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=roles).exists()


def role_required(*roles):
    """Usage: @role_required(settings.ROLE_ADMIN, settings.ROLE_INVENTORY)"""

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            if not user_in_roles(request.user, *roles):
                raise PermissionDenied(
                    "403 Unauthorized: your current role does not have "
                    "permission to view or use this page."
                )
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
