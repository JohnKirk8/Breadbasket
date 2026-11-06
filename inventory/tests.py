from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from .models import Ingredient, Product, RecipeItem, ProductionBatch, SalesRecord, AIRecommendation
from . import ai_forecast

User = get_user_model()


class BreadBasketCoreTests(TestCase):
    def setUp(self):
        # Create groups
        self.admin_group = Group.objects.create(name='Admin')
        self.baker_group = Group.objects.create(name='Baker')
        self.staff_group = Group.objects.create(name='Inventory Staff')

        # Create demo users
        self.admin_user = User.objects.create_user(username='admin', password='breadbasket123', is_staff=True, is_superuser=True)
        self.admin_user.groups.add(self.admin_group)

        self.baker_user = User.objects.create_user(username='baker', password='breadbasket123')
        self.baker_user.groups.add(self.baker_group)

        self.staff_user = User.objects.create_user(username='staff', password='breadbasket123')
        self.staff_user.groups.add(self.staff_group)

        # Create ingredients
        self.flour = Ingredient.objects.create(name='Flour', unit='kg', stock=Decimal('50.000'), low_stock_threshold=Decimal('20.000'))
        self.sugar = Ingredient.objects.create(name='Sugar', unit='kg', stock=Decimal('8.500'), low_stock_threshold=Decimal('10.000'))
        self.yeast = Ingredient.objects.create(name='Yeast', unit='g', stock=Decimal('500.000'), low_stock_threshold=Decimal('100.000'))

        # Create product and recipe
        self.pandesal = Product.objects.create(
            name='Pandesal',
            unit_price=Decimal('5.00'),
            shelf_life_days=2,
            avg_daily_sales=Decimal('100.00'),
        )
        RecipeItem.objects.create(product=self.pandesal, ingredient=self.flour, quantity_per_unit=Decimal('0.05'))
        RecipeItem.objects.create(product=self.pandesal, ingredient=self.sugar, quantity_per_unit=Decimal('0.01'))

    def test_1_login_validation_and_auth(self):
        client = Client()
        # Invalid credentials
        res = client.post(reverse('login'), {'username': 'admin', 'password': 'wrongpassword'})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Invalid")

        # Valid credentials
        res = client.post(reverse('login'), {'username': 'admin', 'password': 'breadbasket123'}, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.context['user'].is_authenticated)

    def test_2_low_stock_notification(self):
        client = Client()
        client.login(username='staff', password='breadbasket123')
        res = client.get(reverse('ingredients'))
        self.assertEqual(res.status_code, 200)
        # Sugar stock (8.5) is <= threshold (10.0)
        self.assertEqual(res.context['low_stock_count'], 1)
        self.assertContains(res, "Low-stock alert: Sugar is running low")

    def test_3_inventory_update_persists(self):
        client = Client()
        client.login(username='staff', password='breadbasket123')
        
        # Update flour stock to 35.5 kg
        res = client.post(reverse('update_ingredient_stock'), {
            'ingredient_id': self.flour.id,
            'stock': '35.500',
        }, follow=True)
        self.assertEqual(res.status_code, 200)
        
        self.flour.refresh_from_db()
        self.assertEqual(self.flour.stock, Decimal('35.500'))

    def test_4_create_batch_success_and_deduction(self):
        client = Client()
        client.login(username='baker', password='breadbasket123')

        initial_flour = self.flour.stock
        initial_sugar = self.sugar.stock

        today = timezone.localdate()
        res = client.post(reverse('log_batch'), {
            'product': self.pandesal.id,
            'quantity_produced': 50,
            'production_date': str(today),
        }, follow=True)
        self.assertEqual(res.status_code, 200)

        # Batch created
        batch = ProductionBatch.objects.latest('id')
        self.assertEqual(batch.product, self.pandesal)
        self.assertEqual(batch.quantity_produced, 50)
        self.assertEqual(batch.production_date, today)
        self.assertEqual(batch.expiration_date, today + timedelta(days=2))

        # Ingredients deducted: 50 * 0.05 = 2.5 flour, 50 * 0.01 = 0.5 sugar
        self.flour.refresh_from_db()
        self.sugar.refresh_from_db()
        self.assertEqual(self.flour.stock, initial_flour - Decimal('2.500'))
        self.assertEqual(self.sugar.stock, initial_sugar - Decimal('0.500'))

    def test_5_create_batch_prevented_on_insufficient_stock(self):
        client = Client()
        client.login(username='baker', password='breadbasket123')

        # Try producing 10,000 units (requires 500 kg flour, only 50 kg available)
        today = timezone.localdate()
        batch_count_before = ProductionBatch.objects.count()
        flour_before = self.flour.stock

        res = client.post(reverse('log_batch'), {
            'product': self.pandesal.id,
            'quantity_produced': 10000,
            'production_date': str(today),
        }, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Production Prevented: Insufficient inventory")

        # Verify no batch created and no flour deducted
        self.assertEqual(ProductionBatch.objects.count(), batch_count_before)
        self.flour.refresh_from_db()
        self.assertEqual(self.flour.stock, flour_before)

    def test_6_historical_sales_entry(self):
        client = Client()
        client.login(username='staff', password='breadbasket123')

        past_date = timezone.localdate() - timedelta(days=5)
        res = client.post(reverse('record_sale'), {
            'product': self.pandesal.id,
            'sale_date': str(past_date),
            'quantity_sold': 75,
        }, follow=True)
        self.assertEqual(res.status_code, 200)

        sale = SalesRecord.objects.latest('id')
        self.assertEqual(sale.product, self.pandesal)
        self.assertEqual(sale.quantity_sold, 75)
        self.assertEqual(sale.sale_date, past_date)
        self.assertEqual(sale.total_amount, Decimal('375.00'))

    def test_7_admin_reports_all_types(self):
        client = Client()
        client.login(username='admin', password='breadbasket123')

        for report_type in ['inventory', 'expiration', 'waste', 'production', 'sales']:
            res = client.get(reverse('reports') + f'?type={report_type}')
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.context['report_type'], report_type)
