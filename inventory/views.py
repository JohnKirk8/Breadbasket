from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum, F, Avg, Count
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone

from . import ai_forecast
from .decorators import role_required
from .forms import (
    ProductForm,
    RestockForm,
    UpdateStockForm,
    ProductionBatchForm,
    SalesRecordForm,
    BatchSaleForm,
    IngredientForm,
)
from .models import (
    Ingredient,
    Product,
    RecipeItem,
    ProductionBatch,
    SalesRecord,
    AIRecommendation,
    apply_expired_batches,
    sell_from_product_batches,
)

ADMIN = settings.ROLE_ADMIN
BAKER = settings.ROLE_BAKER
INVENTORY = settings.ROLE_INVENTORY


# ---------------------------------------------------------------------------
# Tab 1: AI Production Planner & Batch Creation
# ---------------------------------------------------------------------------
@role_required(ADMIN, BAKER, INVENTORY)
def ai_production(request):
    apply_expired_batches()
    products = Product.objects.all().order_by('name')

    latest_by_product = {}
    for product in products:
        latest = product.recommendations.first()  # ordered by -generated_at
        latest_by_product[product.id] = latest

    total_target = sum(
        (rec.recommended_quantity if rec else 0)
        for rec in latest_by_product.values()
    )

    rows = [
        {'product': product, 'recommendation': latest_by_product[product.id]}
        for product in products
    ]

    batches = ProductionBatch.objects.select_related('product', 'baker').exclude(status=ProductionBatch.STATUS_WASTED).order_by('-id')[:40]

    context = {
        'active_tab': 'ai_production',
        'rows': rows,
        'total_target': total_target,
        'active_bread_count': products.count(),
        'batch_form': ProductionBatchForm(),
        'products': products,
        'batches': batches,
        'batch_sale_form': BatchSaleForm(),
        'latest_generated_at': next(
            (rec.generated_at for rec in latest_by_product.values() if rec),
            None,
        ),
    }
    return render(request, 'inventory/ai_production.html', context)


@role_required(ADMIN, BAKER)
def recalculate_ai_forecast(request):
    if request.method != 'POST':
        return redirect('ai_production')

    apply_expired_batches()

    gemini_count = 0
    fallback_count = 0
    for product in Product.objects.all():
        result = ai_forecast.generate_recommendation(product)
        AIRecommendation.objects.create(
            product=product,
            forecast_date=timezone.localdate(),
            recommended_quantity=result['recommended_quantity'],
            reason=result['reason'],
            source=result['source'],
            basis_period=result['basis_period'],
        )
        if result['source'] == 'gemini':
            gemini_count += 1
        else:
            fallback_count += 1

    if gemini_count and not fallback_count:
        messages.success(
            request,
            f"Daily suggestions updated now for {gemini_count} bread type(s) using current sales, batches, and stock.",
        )
    elif gemini_count and fallback_count:
        messages.warning(
            request,
            f"Updated now: {gemini_count} from Gemini, {fallback_count} from live sales/stock fallback.",
        )
    else:
        messages.success(
            request,
            "Daily suggestions updated now from the latest sales, leftover batches, and ingredient stock.",
        )
    return redirect('ai_production')


@role_required(ADMIN, BAKER)
def log_batch(request):
    if request.method != 'POST':
        return redirect('ai_production')

    form = ProductionBatchForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please check the batch form for invalid or missing inputs.")
        return redirect('ai_production')

    product = form.cleaned_data['product']
    quantity = form.cleaned_data['quantity_produced']
    production_date = form.cleaned_data['production_date'] or timezone.localdate()
    shelf_life_days = form.cleaned_data['shelf_life_days'] or product.shelf_life_days

    # Recipe & inventory stock check
    recipe_items = RecipeItem.objects.filter(product=product).select_related('ingredient')
    
    insufficient = []
    for item in recipe_items:
        required_qty = item.quantity_per_unit * Decimal(quantity)
        if item.ingredient.stock < required_qty:
            shortfall = required_qty - item.ingredient.stock
            insufficient.append(
                f"{item.ingredient.name} (Need: {required_qty:.2f} {item.ingredient.unit}, Stock: {item.ingredient.stock:.2f} {item.ingredient.unit}, Short: {shortfall:.2f} {item.ingredient.unit})"
            )

    if insufficient:
        messages.error(
            request,
            f"Production Prevented: Insufficient inventory to bake {quantity} units of {product.name}. Short on: {'; '.join(insufficient)}. Please replenish ingredients before creating this batch."
        )
        return redirect('ai_production')

    expiration_date = production_date + timezone.timedelta(days=shelf_life_days)

    # Perform atomic deduction and batch creation
    with transaction.atomic():
        for item in recipe_items:
            deduct_qty = item.quantity_per_unit * Decimal(quantity)
            Ingredient.objects.filter(pk=item.ingredient_id).update(
                stock=F('stock') - deduct_qty
            )

        batch = ProductionBatch.objects.create(
            product=product,
            baker=request.user,
            quantity_produced=quantity,
            original_quantity=quantity,
            sold_quantity=0,
            remaining_quantity=quantity,
            waste_quantity=0,
            production_date=production_date,
            expiration_date=expiration_date,
            status=ProductionBatch.STATUS_ACTIVE,
        )

    messages.success(
        request,
        f"Batch #{batch.id} created: {quantity} units of {product.name}. Remaining: {quantity}.",
    )
    return redirect('ai_production')


@role_required(ADMIN, BAKER)
def record_batch_sale(request, batch_id):
    if request.method != 'POST':
        return redirect('ai_production')

    batch = get_object_or_404(ProductionBatch, pk=batch_id)
    form = BatchSaleForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Enter a valid sold quantity.")
        return redirect('ai_production')

    quantity = form.cleaned_data['quantity_sold']
    try:
        with transaction.atomic():
            locked = ProductionBatch.objects.select_for_update().get(pk=batch.id)
            locked.apply_sale(quantity)
            SalesRecord.objects.create(
                product=locked.product,
                batch=locked,
                quantity_sold=quantity,
                unit_price=locked.product.unit_price,
                sale_date=timezone.localdate(),
                recorded_by=request.user,
            )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('ai_production')

    locked.refresh_from_db()
    messages.success(
        request,
        f"Recorded {quantity} sold from batch #{locked.id}. Remaining: {locked.remaining_quantity}.",
    )
    return redirect('ai_production')


# ---------------------------------------------------------------------------
# Tab 2: Bread Catalog & Recipes
# ---------------------------------------------------------------------------
@role_required(ADMIN, BAKER, INVENTORY)
def catalog(request):
    products = Product.objects.all().prefetch_related('recipe_items__ingredient')
    context = {
        'active_tab': 'catalog',
        'products': products,
        'product_form': ProductForm(),
        'ingredients': Ingredient.objects.all(),
    }
    return render(request, 'inventory/catalog.html', context)


@role_required(ADMIN)
def add_product(request):
    if request.method != 'POST':
        return redirect('catalog')

    form = ProductForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please check the new product form for errors.")
        return redirect('catalog')

    product = form.save()

    ingredient_ids = request.POST.getlist('ingredient_id')
    quantities = request.POST.getlist('qty_per_unit')
    for ing_id, qty in zip(ingredient_ids, quantities):
        if not ing_id or not qty:
            continue
        try:
            qty_value = Decimal(qty)
        except Exception:
            continue
        if qty_value <= 0:
            continue
        RecipeItem.objects.update_or_create(
            product=product,
            ingredient_id=ing_id,
            defaults={'quantity_per_unit': qty_value},
        )

    messages.success(request, f"Added {product.name} to the catalog.")
    return redirect('catalog')


@role_required(ADMIN)
def delete_product(request, product_id):
    if request.method != 'POST':
        return redirect('catalog')
    product = get_object_or_404(Product, pk=product_id)
    product.delete()
    messages.success(request, f"Deleted {product.name} from the catalog.")
    return redirect('catalog')


# ---------------------------------------------------------------------------
# Tab 3: Raw Ingredients (Full CRUD for Admin and Inventory Staff)
# ---------------------------------------------------------------------------
@role_required(ADMIN, INVENTORY, BAKER)
def ingredients_view(request):
    ingredients = Ingredient.objects.all().order_by('name')
    context = {
        'active_tab': 'ingredients',
        'ingredients': ingredients,
        'low_stock_count': sum(1 for i in ingredients if i.is_low_stock),
        'ingredient_form': IngredientForm(),
        'restock_form': RestockForm(),
        'update_stock_form': UpdateStockForm(),
    }
    return render(request, 'inventory/ingredients.html', context)


@role_required(ADMIN, INVENTORY)
def add_ingredient(request):
    if request.method != 'POST':
        return redirect('ingredients')

    form = IngredientForm(request.POST)
    if not form.is_valid():
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{error}")
        return redirect('ingredients')

    ingredient = form.save(commit=False)
    ingredient.last_restocked_at = timezone.now()
    ingredient.save()
    messages.success(request, f"Ingredient '{ingredient.name}' created successfully.")
    return redirect('ingredients')


@role_required(ADMIN, INVENTORY)
def update_ingredient(request, ingredient_id):
    if request.method != 'POST':
        return redirect('ingredients')

    ingredient = get_object_or_404(Ingredient, pk=ingredient_id)
    form = IngredientForm(request.POST, instance=ingredient)
    if not form.is_valid():
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{error}")
        return redirect('ingredients')

    ingredient = form.save(commit=False)
    ingredient.last_restocked_at = timezone.now()
    ingredient.save()
    messages.success(request, f"Ingredient '{ingredient.name}' updated successfully.")
    return redirect('ingredients')


@role_required(ADMIN, INVENTORY)
def delete_ingredient(request, ingredient_id):
    if request.method != 'POST':
        return redirect('ingredients')

    ingredient = get_object_or_404(Ingredient, pk=ingredient_id)
    name = ingredient.name
    ingredient.delete()
    messages.success(request, f"Ingredient '{name}' deleted successfully.")
    return redirect('ingredients')


@role_required(ADMIN, INVENTORY)
def update_ingredient_stock(request):
    """Allows Inventory Staff to directly edit and set ingredient stock quantity."""
    if request.method != 'POST':
        return redirect('ingredients')

    ingredient_id = request.POST.get('ingredient_id')
    ingredient = get_object_or_404(Ingredient, pk=ingredient_id)
    
    new_stock_val = request.POST.get('stock')
    threshold_val = request.POST.get('low_stock_threshold')

    if new_stock_val is None or new_stock_val.strip() == '':
        messages.error(request, "Stock quantity cannot be empty.")
        return redirect('ingredients')

    try:
        new_stock = Decimal(new_stock_val)
        if new_stock < 0:
            messages.error(request, "Stock quantity cannot be negative.")
            return redirect('ingredients')
    except Exception:
        messages.error(request, "Invalid stock quantity format.")
        return redirect('ingredients')

    ingredient.stock = new_stock
    ingredient.last_restocked_at = timezone.now()

    if threshold_val and threshold_val.strip() != '':
        try:
            new_threshold = Decimal(threshold_val)
            if new_threshold >= 0:
                ingredient.low_stock_threshold = new_threshold
        except Exception:
            pass

    ingredient.save()
    messages.success(
        request,
        f"Inventory updated: {ingredient.name} stock is now {ingredient.stock} {ingredient.unit}. Saved to database."
    )
    return redirect('ingredients')


@role_required(ADMIN, INVENTORY)
def restock_ingredient(request):
    if request.method != 'POST':
        return redirect('ingredients')

    form = RestockForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please enter a valid restock quantity.")
        return redirect('ingredients')

    ingredient = form.cleaned_data['ingredient']
    add_qty = form.cleaned_data['add_quantity']
    ingredient.stock = F('stock') + add_qty
    ingredient.last_restocked_at = timezone.now()
    ingredient.save(update_fields=['stock', 'last_restocked_at'])
    messages.success(request, f"Restocked {ingredient.name} (+{add_qty} {ingredient.unit}). Saved to database.")
    return redirect('ingredients')


# ---------------------------------------------------------------------------
# Tab 4: Sales Transactions & Historical Sales Entry
# ---------------------------------------------------------------------------
@role_required(ADMIN, INVENTORY)
def sales_view(request):
    sales_records = SalesRecord.objects.select_related('product', 'recorded_by').all().order_by('-sale_date', '-created_at')[:100]
    total_revenue = sum(s.total_amount for s in sales_records)
    total_units_sold = sum(s.quantity_sold for s in sales_records)

    context = {
        'active_tab': 'sales',
        'products': Product.objects.all().order_by('name'),
        'sales_records': sales_records,
        'total_revenue': total_revenue,
        'total_units_sold': total_units_sold,
        'sales_form': SalesRecordForm(),
    }
    return render(request, 'inventory/sales.html', context)


@role_required(ADMIN, INVENTORY)
def record_sale(request):
    if request.method != 'POST':
        return redirect('sales')

    form = SalesRecordForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please provide a valid bread product, date, and sold quantity.")
        return redirect('sales')

    product = form.cleaned_data['product']
    quantity = form.cleaned_data['quantity_sold']
    sale_date = form.cleaned_data['sale_date'] or timezone.localdate()

    try:
        sell_from_product_batches(
            product=product,
            quantity=quantity,
            user=request.user,
            sale_date=sale_date,
            unit_price=product.unit_price,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('sales')

    # Recalculate rolling average daily sales for this product
    daily_avgs = (
        SalesRecord.objects.filter(product=product)
        .values('sale_date')
        .annotate(day_total=Sum('quantity_sold'))
        .aggregate(avg_sales=Avg('day_total'))
    )
    if daily_avgs['avg_sales']:
        product.avg_daily_sales = round(Decimal(daily_avgs['avg_sales']), 2)
        product.save(update_fields=['avg_daily_sales'])

    messages.success(
        request,
        f"Recorded sale: {quantity} unit(s) of {product.name} on {sale_date}. Saved to database."
    )
    return redirect('sales')


@role_required(ADMIN, INVENTORY)
def delete_sale(request, sale_id):
    if request.method != 'POST':
        return redirect('sales')
    sale = get_object_or_404(SalesRecord, pk=sale_id)
    product = sale.product
    batch = sale.batch
    qty = sale.quantity_sold
    sale.delete()
    if batch:
        batch.reverse_sale(qty)
    messages.success(request, f"Deleted sales entry for {product.name}.")
    return redirect('sales')


# ---------------------------------------------------------------------------
# Tab 5: Admin Reports (Inventory, Expiration, Waste, Production, Sales)
# ---------------------------------------------------------------------------
@role_required(ADMIN)
def reports_view(request):
    today = timezone.localdate()
    apply_expired_batches(today)

    report_type = request.GET.get('type', 'inventory').lower().strip()
    valid_types = ['inventory', 'expiration', 'waste', 'production', 'sales']
    if report_type not in valid_types:
        report_type = 'inventory'

    period = request.GET.get('period', 'all').lower().strip()
    valid_periods = ['today', 'week', 'month', 'year', 'all']
    if period not in valid_periods:
        period = 'all'

    if period == 'today':
        date_from = today
    elif period == 'week':
        date_from = today - timezone.timedelta(days=6)
    elif period == 'month':
        date_from = today - timezone.timedelta(days=29)
    elif period == 'year':
        date_from = today - timezone.timedelta(days=364)
    else:
        date_from = None

    context = {
        'active_tab': 'reports',
        'report_type': report_type,
        'period': period,
        'today': today,
        'generated_at': timezone.now(),
    }

    if report_type == 'inventory':
        ingredients = Ingredient.objects.all().order_by('name')
        low_count = sum(1 for i in ingredients if i.is_low_stock)
        out_of_stock_count = sum(1 for i in ingredients if i.stock <= 0)
        total_items = ingredients.count()
        context.update({
            'ingredients': ingredients,
            'low_count': low_count,
            'out_of_stock_count': out_of_stock_count,
            'total_items': total_items,
        })

    elif report_type == 'expiration':
        batches_qs = ProductionBatch.objects.select_related('product', 'baker').all().order_by('expiration_date')
        if date_from:
            batches_qs = batches_qs.filter(production_date__gte=date_from)
        batches = list(batches_qs)

        for b in batches:
            b.days_remaining = (b.expiration_date - today).days
            b.abs_days = abs(b.days_remaining)
            if b.status == ProductionBatch.STATUS_WASTED:
                b.status_label = 'Wasted'
                b.status_pill = 'pill-red'
            elif b.status == ProductionBatch.STATUS_EXPIRED or b.expiration_date < today:
                b.status_label = 'Expired'
                b.status_pill = 'pill-red'
            elif b.days_remaining <= 1:
                b.status_label = 'Expiring Soon'
                b.status_pill = 'pill-amber'
            else:
                b.status_label = 'Fresh'
                b.status_pill = 'pill-green'

        active_count = sum(1 for b in batches if b.status == ProductionBatch.STATUS_ACTIVE and b.days_remaining >= 0)
        expiring_soon_count = sum(
            1 for b in batches
            if b.status == ProductionBatch.STATUS_ACTIVE and 0 <= b.days_remaining <= 1
        )
        expired_count = sum(
            1 for b in batches
            if b.status in (ProductionBatch.STATUS_EXPIRED, ProductionBatch.STATUS_WASTED) or b.expiration_date < today
        )

        context.update({
            'batches': batches,
            'active_count': active_count,
            'expiring_soon_count': expiring_soon_count,
            'expired_count': expired_count,
            'total_batches': len(batches),
        })

    elif report_type == 'waste':
        wasted_batches = ProductionBatch.objects.filter(
            waste_quantity__gt=0
        ).select_related('product', 'baker').order_by('-expiration_date')

        for b in wasted_batches:
            b.estimated_loss = round(Decimal(b.waste_quantity) * b.product.unit_price, 2)

        total_waste_loss = sum(b.estimated_loss for b in wasted_batches)
        total_waste_units = sum(b.waste_quantity for b in wasted_batches)

        context.update({
            'wasted_batches': wasted_batches,
            'total_waste_loss': total_waste_loss,
            'total_waste_units': total_waste_units,
            'waste_count': wasted_batches.count(),
        })

    elif report_type == 'production':
        batches = ProductionBatch.objects.select_related('product', 'baker').all().order_by('-production_date', '-id')
        if date_from:
            batches = batches.filter(production_date__gte=date_from)
        total_produced = sum(b.quantity_produced for b in batches)
        total_remaining = sum(b.remaining_quantity for b in batches)
        total_sold = sum(b.sold_quantity for b in batches)
        total_batches = batches.count()

        prod_qs = ProductionBatch.objects.all()
        if date_from:
            prod_qs = prod_qs.filter(production_date__gte=date_from)
        production_by_product = (
            prod_qs.values('product__name')
            .annotate(
                total_qty=Sum('quantity_produced'),
                batch_count=Count('id'),
                total_sold=Sum('sold_quantity'),
                total_remaining=Sum('remaining_quantity'),
                total_waste=Sum('waste_quantity'),
            )
            .order_by('-total_qty')
        )

        context.update({
            'batches': batches,
            'total_produced': total_produced,
            'total_remaining': total_remaining,
            'total_sold': total_sold,
            'total_batches': total_batches,
            'production_by_product': production_by_product,
        })

    elif report_type == 'sales':
        sales = SalesRecord.objects.select_related('product', 'recorded_by', 'batch').all().order_by('-sale_date', '-id')
        if date_from:
            sales = sales.filter(sale_date__gte=date_from)
        sales_list = list(sales)
        total_revenue = sum(s.total_amount for s in sales_list)
        total_units = sum(s.quantity_sold for s in sales_list)
        avg_transaction = (total_revenue / len(sales_list)) if sales_list else Decimal('0.00')

        sales_qs = SalesRecord.objects.all()
        if date_from:
            sales_qs = sales_qs.filter(sale_date__gte=date_from)
        sales_by_product = (
            sales_qs.values('product__name')
            .annotate(
                total_units=Sum('quantity_sold'),
                total_sales=Sum(F('quantity_sold') * F('unit_price'))
            )
            .order_by('-total_sales')
        )

        context.update({
            'sales': sales,
            'total_revenue': total_revenue,
            'total_units': total_units,
            'avg_transaction': round(avg_transaction, 2),
            'sales_by_product': sales_by_product,
        })

    return render(request, 'inventory/reports.html', context)


@role_required(ADMIN)
def log_waste(request, batch_id):
    if request.method != 'POST':
        return redirect('reports')
    batch = get_object_or_404(ProductionBatch, pk=batch_id)
    leftover = batch.mark_expired()
    messages.success(
        request,
        f"Batch #{batch.id}: {leftover} unsold unit(s) recorded as waste.",
    )
    return redirect(f"{reverse('reports')}?type=waste")