from django.contrib import admin

from .models import (
    Ingredient,
    Product,
    RecipeItem,
    ProductionBatch,
    SalesRecord,
    AIRecommendation,
)


class RecipeItemInline(admin.TabularInline):
    model = RecipeItem
    extra = 1


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ('name', 'stock', 'unit', 'low_stock_threshold', 'is_low_stock')
    list_filter = ('unit',)
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'unit_price', 'avg_daily_sales', 'shelf_life_days')
    inlines = [RecipeItemInline]
    search_fields = ('name',)


@admin.register(ProductionBatch)
class ProductionBatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'quantity_produced', 'production_date', 'expiration_date', 'status')
    list_filter = ('status', 'product')


@admin.register(SalesRecord)
class SalesRecordAdmin(admin.ModelAdmin):
    list_display = ('product', 'quantity_sold', 'unit_price', 'sale_date', 'recorded_by')
    list_filter = ('product',)


@admin.register(AIRecommendation)
class AIRecommendationAdmin(admin.ModelAdmin):
    list_display = ('product', 'forecast_date', 'recommended_quantity', 'source', 'generated_at')
    list_filter = ('source', 'product')
