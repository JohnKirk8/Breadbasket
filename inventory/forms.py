from django import forms
from django.utils import timezone

from .models import Ingredient, Product, ProductionBatch, SalesRecord


class IngredientForm(forms.ModelForm):
    """Form for creating and editing raw ingredients with duplicate name protection."""

    class Meta:
        model = Ingredient
        fields = ['name', 'unit', 'stock', 'low_stock_threshold', 'supplier']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Flour'}),
            'unit': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. kg, g, L, pcs'}),
            'stock': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'min': '0'}),
            'low_stock_threshold': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'min': '0'}),
            'supplier': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Main Bakery Supply'}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError("Ingredient name cannot be empty.")

        # Case-insensitive duplicate check
        qs = Ingredient.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError(f"An ingredient named '{name}' already exists.")
        return name


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'category', 'unit_price', 'shelf_life_days', 'avg_daily_sales']
        widgets = {
            'avg_daily_sales': forms.NumberInput(attrs={'placeholder': 'Estimated starting daily demand'}),
        }


class RestockForm(forms.Form):
    ingredient = forms.ModelChoiceField(queryset=Ingredient.objects.all())
    add_quantity = forms.DecimalField(max_digits=10, decimal_places=3, min_value=0.001)


class UpdateStockForm(forms.Form):
    """Allows Inventory Staff to directly update ingredient stock quantity and threshold."""
    ingredient_id = forms.IntegerField()
    stock = forms.DecimalField(max_digits=10, decimal_places=3, min_value=0)
    low_stock_threshold = forms.DecimalField(max_digits=10, decimal_places=3, min_value=0, required=False)


class ProductionBatchForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.all().order_by('name'),
        empty_label="-- Select Bread Product --",
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'batch_product_select'})
    )
    quantity_produced = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 50', 'min': '1'})
    )
    production_date = forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    shelf_life_days = forms.IntegerField(
        min_value=1,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Leave empty for product default', 'min': '1'})
    )


class BatchSaleForm(forms.Form):
    quantity_sold = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'style': 'width:90px; margin:0;'})
    )


class SalesRecordForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.all().order_by('name'),
        empty_label="-- Select Bread Product --",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    sale_date = forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    quantity_sold = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 30', 'min': '1'})
    )