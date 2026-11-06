from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    # Auth
    path('login/', auth_views.LoginView.as_view(template_name='inventory/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    # Tab 1: AI Production Planner
    path('', views.ai_production, name='ai_production'),
    path('ai/refresh/', views.recalculate_ai_forecast, name='recalculate_ai_forecast'),
    path('ai/log-batch/', views.log_batch, name='log_batch'),
    path('ai/batches/<int:batch_id>/sell/', views.record_batch_sale, name='record_batch_sale'),

    # Tab 2: Bread Catalog & Recipes
    path('catalog/', views.catalog, name='catalog'),
    path('catalog/add/', views.add_product, name='add_product'),
    path('catalog/<int:product_id>/delete/', views.delete_product, name='delete_product'),

    # Tab 3: Raw Ingredients (Full CRUD)
    path('ingredients/', views.ingredients_view, name='ingredients'),
    path('ingredients/add/', views.add_ingredient, name='add_ingredient'),
    path('ingredients/<int:ingredient_id>/update/', views.update_ingredient, name='update_ingredient'),
    path('ingredients/<int:ingredient_id>/delete/', views.delete_ingredient, name='delete_ingredient'),
    path('ingredients/restock/', views.restock_ingredient, name='restock_ingredient'),
    path('ingredients/update-stock/', views.update_ingredient_stock, name='update_ingredient_stock'),

    # Tab 4: Sales Transactions & Historical Sales
    path('sales/', views.sales_view, name='sales'),
    path('sales/record/', views.record_sale, name='record_sale'),
    path('sales/<int:sale_id>/delete/', views.delete_sale, name='delete_sale'),

    # Tab 5: Reports & Analytics
    path('reports/', views.reports_view, name='reports'),
    path('reports/<int:batch_id>/waste/', views.log_waste, name='log_waste'),
]