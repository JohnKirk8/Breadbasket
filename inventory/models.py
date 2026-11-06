from django.conf import settings
from django.db import models
from django.utils import timezone


class Ingredient(models.Model):
    """A raw material used in bread production (flour, sugar, yeast, ...)."""

    name = models.CharField(max_length=120, unique=True)
    unit = models.CharField(max_length=20, help_text="e.g. kg, g, L, pcs")
    stock = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    low_stock_threshold = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    supplier = models.CharField(max_length=150, blank=True)
    last_restocked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def is_low_stock(self):
        return self.stock <= self.low_stock_threshold


class Product(models.Model):
    """A bread type Bread Basket Bakeshop sells (Pandesal, Ensaymada, ...)."""

    name = models.CharField(max_length=120, unique=True)
    category = models.CharField(max_length=80, blank=True)
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    shelf_life_days = models.PositiveIntegerField(default=3)
    # Simple rolling average of daily sales, used as a fallback forecast
    # when the AI call isn't available (no internet / no API key yet).
    avg_daily_sales = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    ingredients = models.ManyToManyField(Ingredient, through='RecipeItem', related_name='products')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class RecipeItem(models.Model):
    """How much of one ingredient is needed to make one unit of a product."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='recipe_items')
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE)
    quantity_per_unit = models.DecimalField(max_digits=10, decimal_places=4)

    class Meta:
        unique_together = ('product', 'ingredient')

    def __str__(self):
        return f"{self.product.name} needs {self.quantity_per_unit} {self.ingredient.unit} of {self.ingredient.name}"


class ProductionBatch(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_EXPIRED = 'expired'
    STATUS_WASTED = 'wasted'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_WASTED, 'Wasted'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='batches')
    baker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    quantity_produced = models.PositiveIntegerField()
    original_quantity = models.PositiveIntegerField(default=0)
    sold_quantity = models.PositiveIntegerField(default=0)
    remaining_quantity = models.PositiveIntegerField(default=0)
    waste_quantity = models.PositiveIntegerField(default=0)
    production_date = models.DateField(default=timezone.localdate)
    expiration_date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-production_date', '-id']

    def __str__(self):
        return f"Batch {self.pk} - {self.product.name} x{self.quantity_produced}"

    @property
    def is_expired(self):
        return timezone.localdate() > self.expiration_date

    def save(self, *args, **kwargs):
        produced = int(self.quantity_produced or 0)
        if not self.original_quantity:
            self.original_quantity = produced
        if self._state.adding and not self.remaining_quantity:
            self.remaining_quantity = produced
        super().save(*args, **kwargs)

    def apply_sale(self, quantity):
        """Deduct sold units from this batch's remaining quantity."""
        qty = int(quantity)
        if qty < 1:
            raise ValueError("Sold quantity must be at least 1.")
        if self.status != self.STATUS_ACTIVE:
            raise ValueError("Sales can only be recorded on an active batch.")
        remaining = int(self.remaining_quantity or 0)
        if remaining <= 0:
            remaining = max(0, int(self.quantity_produced) - int(self.sold_quantity or 0))
        if qty > remaining:
            raise ValueError(f"Only {remaining} unit(s) remaining in this batch.")
        self.sold_quantity = int(self.sold_quantity or 0) + qty
        self.remaining_quantity = remaining - qty
        self.save(update_fields=['sold_quantity', 'remaining_quantity'])
        return qty

    def reverse_sale(self, quantity):
        qty = int(quantity)
        self.sold_quantity = max(0, int(self.sold_quantity or 0) - qty)
        if self.status == self.STATUS_ACTIVE:
            self.remaining_quantity = int(self.remaining_quantity or 0) + qty
        else:
            self.waste_quantity = max(0, int(self.waste_quantity or 0) - qty)
        self.save(update_fields=['sold_quantity', 'remaining_quantity', 'waste_quantity'])

    def mark_expired(self):
        """Unsold leftover becomes waste. Sold units are not wasted."""
        leftover = int(self.remaining_quantity or 0)
        if leftover <= 0 and int(self.waste_quantity or 0) == 0:
            leftover = max(0, int(self.quantity_produced or 0) - int(self.sold_quantity or 0))
        self.waste_quantity = leftover
        self.remaining_quantity = 0
        self.status = self.STATUS_WASTED if leftover > 0 else self.STATUS_EXPIRED
        self.save(update_fields=['waste_quantity', 'remaining_quantity', 'status'])
        return leftover


def apply_expired_batches(today=None):
    """Flip past-due batches and record leftover unsold units as waste."""
    today = today or timezone.localdate()
    expired = ProductionBatch.objects.filter(
        status=ProductionBatch.STATUS_ACTIVE,
        expiration_date__lt=today,
    )
    wasted_units = 0
    for batch in expired:
        wasted_units += batch.mark_expired()
    return wasted_units


class SalesRecord(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='sales')
    batch = models.ForeignKey(
        ProductionBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales_records',
    )
    quantity_sold = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    sale_date = models.DateField(default=timezone.localdate)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sale_date', '-created_at']

    @property
    def total_amount(self):
        return self.unit_price * self.quantity_sold

    def __str__(self):
        return f"{self.sale_date} - {self.product.name} x{self.quantity_sold}"


def sell_from_product_batches(product, quantity, user, sale_date, unit_price):
    """Record a product sale against specific leftover batch stock (oldest expiry first)."""
    from django.db import transaction

    remaining_to_sell = int(quantity)
    records = []
    with transaction.atomic():
        batches = list(
            ProductionBatch.objects.select_for_update().filter(
                product=product,
                status=ProductionBatch.STATUS_ACTIVE,
                remaining_quantity__gt=0,
            ).order_by('expiration_date', 'id')
        )
        available = sum(int(b.remaining_quantity) for b in batches)
        if batches and remaining_to_sell > available:
            raise ValueError(f"Only {available} unsold unit(s) remain in active batches.")
        if not batches:
            records.append(SalesRecord.objects.create(
                product=product,
                quantity_sold=remaining_to_sell,
                unit_price=unit_price,
                sale_date=sale_date,
                recorded_by=user,
            ))
            return records
        for batch in batches:
            if remaining_to_sell <= 0:
                break
            take = min(int(batch.remaining_quantity), remaining_to_sell)
            batch.apply_sale(take)
            records.append(SalesRecord.objects.create(
                product=product,
                batch=batch,
                quantity_sold=take,
                unit_price=unit_price,
                sale_date=sale_date,
                recorded_by=user,
            ))
            remaining_to_sell -= take
    return records


class AIRecommendation(models.Model):
    """A saved forecast, either from the Gemini API or the fallback average."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='recommendations')
    forecast_date = models.DateField(default=timezone.localdate)
    recommended_quantity = models.PositiveIntegerField()
    reason = models.TextField(blank=True)
    basis_period = models.CharField(max_length=80, blank=True, help_text="e.g. 'last 14 days of sales'")
    source = models.CharField(
        max_length=20,
        choices=[('gemini', 'Gemini API'), ('fallback', 'Moving Average Fallback')],
        default='fallback',
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-generated_at']

    def __str__(self):
        return f"{self.product.name} -> {self.recommended_quantity} ({self.forecast_date})"
