from django.conf import settings


def role_context(request):
    """
    Makes these available in every template automatically:
      - user_groups: list of the current user's group names, e.g. ["Baker"]
      - is_admin / is_baker / is_inventory: booleans for quick {% if %} checks

    Admin (or superuser) gets all three flags True so one account can use
    every panel. Baker and Inventory Staff only get their own flag.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {
            'user_groups': [],
            'is_admin': False,
            'is_baker': False,
            'is_inventory': False,
        }

    group_names = list(user.groups.values_list('name', flat=True))
    is_admin = user.is_superuser or settings.ROLE_ADMIN in group_names

    from django.db.models import F
    from .models import Ingredient

    low_stock_items = list(
        Ingredient.objects.filter(stock__lte=F('low_stock_threshold')).order_by('name')
    )

    return {
        'user_groups': group_names,
        'is_admin': is_admin,
        'is_baker': is_admin or settings.ROLE_BAKER in group_names,
        'is_inventory': is_admin or settings.ROLE_INVENTORY in group_names,
        'low_stock_items': low_stock_items,
        'low_stock_count': len(low_stock_items),
    }
