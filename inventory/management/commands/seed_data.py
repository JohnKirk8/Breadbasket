from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.utils import timezone

from inventory.models import Ingredient, Product, RecipeItem, ProductionBatch


# Demo accounts for each role — password is the same for all three.
DEMO_USERS = [
    {
        "username": "admin",
        "password": "breadbasket123",
        "role": settings.ROLE_ADMIN,
        "is_staff": True,
        "is_superuser": True,
        "first_name": "Owner",
        "last_name": "Admin",
    },
    {
        "username": "baker",
        "password": "breadbasket123",
        "role": settings.ROLE_BAKER,
        "is_staff": False,
        "is_superuser": False,
        "first_name": "Juan",
        "last_name": "Baker",
    },
    {
        "username": "staff",
        "password": "breadbasket123",
        "role": settings.ROLE_INVENTORY,
        "is_staff": False,
        "is_superuser": False,
        "first_name": "Maria",
        "last_name": "Staff",
    },
]


class Command(BaseCommand):
    help = (
        "Creates Admin/Baker/Inventory Staff groups, demo login users, "
        "and sample bakery inventory data."
    )

    def handle(self, *args, **options):
        groups = {}
        for role in (settings.ROLE_ADMIN, settings.ROLE_BAKER, settings.ROLE_INVENTORY):
            group, created = Group.objects.get_or_create(name=role)
            groups[role] = group
            self.stdout.write(
                self.style.SUCCESS(f"{'Created' if created else 'Found'} group: {role}")
            )

        User = get_user_model()
        self.stdout.write("")
        self.stdout.write(self.style.NOTICE("Demo login accounts (password for all: breadbasket123)"))
        for demo in DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=demo["username"],
                defaults={
                    "first_name": demo["first_name"],
                    "last_name": demo["last_name"],
                    "is_staff": demo["is_staff"],
                    "is_superuser": demo["is_superuser"],
                },
            )
            # Keep password/role in sync on re-runs so demos always work.
            user.set_password(demo["password"])
            user.first_name = demo["first_name"]
            user.last_name = demo["last_name"]
            user.is_staff = demo["is_staff"]
            user.is_superuser = demo["is_superuser"]
            user.save()
            user.groups.set([groups[demo["role"]]])
            status = "Created" if created else "Updated"
            self.stdout.write(
                self.style.SUCCESS(
                    f"  {status} user '{demo['username']}' -> role: {demo['role']}"
                )
            )

        flour, _ = Ingredient.objects.get_or_create(
            name="Flour", defaults={"unit": "kg", "stock": 45, "low_stock_threshold": 20}
        )
        sugar, _ = Ingredient.objects.get_or_create(
            name="Sugar", defaults={"unit": "kg", "stock": 8.5, "low_stock_threshold": 10}
        )
        yeast, _ = Ingredient.objects.get_or_create(
            name="Yeast", defaults={"unit": "g", "stock": 1200, "low_stock_threshold": 300}
        )
        butter, _ = Ingredient.objects.get_or_create(
            name="Butter", defaults={"unit": "kg", "stock": 15, "low_stock_threshold": 5}
        )
        cheese, _ = Ingredient.objects.get_or_create(
            name="Cheese", defaults={"unit": "kg", "stock": 6, "low_stock_threshold": 3}
        )

        catalog = [
            {
                "name": "Pandesal",
                "unit_price": Decimal("5.00"),
                "shelf_life_days": 2,
                "avg_daily_sales": Decimal("150"),
                "recipe": [(flour, "0.05"), (sugar, "0.01"), (yeast, "2")],
            },
            {
                "name": "Spanish Bread",
                "unit_price": Decimal("15.00"),
                "shelf_life_days": 3,
                "avg_daily_sales": Decimal("60"),
                "recipe": [(flour, "0.08"), (sugar, "0.02"), (butter, "0.01")],
            },
            {
                "name": "Cheese Bread",
                "unit_price": Decimal("18.00"),
                "shelf_life_days": 3,
                "avg_daily_sales": Decimal("45"),
                "recipe": [(flour, "0.08"), (sugar, "0.01"), (cheese, "0.02")],
            },
            {
                "name": "Ensaymada",
                "unit_price": Decimal("20.00"),
                "shelf_life_days": 3,
                "avg_daily_sales": Decimal("30"),
                "recipe": [(flour, "0.10"), (sugar, "0.03"), (butter, "0.02")],
            },
        ]

        products = {}
        for item in catalog:
            product, _ = Product.objects.get_or_create(
                name=item["name"],
                defaults={
                    "unit_price": item["unit_price"],
                    "shelf_life_days": item["shelf_life_days"],
                    "avg_daily_sales": item["avg_daily_sales"],
                },
            )
            products[item["name"]] = product
            for ingredient, qty in item["recipe"]:
                RecipeItem.objects.get_or_create(
                    product=product,
                    ingredient=ingredient,
                    defaults={"quantity_per_unit": Decimal(qty)},
                )

        today = timezone.localdate()
        baker_user = User.objects.filter(username="baker").first()
        staff_user = User.objects.filter(username="staff").first()

        # Seed realistic batches if not populated
        if ProductionBatch.objects.count() < 3:
            ProductionBatch.objects.get_or_create(
                product=products["Pandesal"],
                baker=baker_user,
                quantity_produced=150,
                production_date=today - timedelta(days=1),
                expiration_date=today + timedelta(days=1),
                defaults={"status": ProductionBatch.STATUS_ACTIVE},
            )
            ProductionBatch.objects.get_or_create(
                product=products["Spanish Bread"],
                baker=baker_user,
                quantity_produced=60,
                production_date=today - timedelta(days=2),
                expiration_date=today + timedelta(days=1),
                defaults={"status": ProductionBatch.STATUS_ACTIVE},
            )
            ProductionBatch.objects.get_or_create(
                product=products["Ensaymada"],
                baker=baker_user,
                quantity_produced=25,
                production_date=today - timedelta(days=5),
                expiration_date=today - timedelta(days=2),
                defaults={"status": ProductionBatch.STATUS_EXPIRED},
            )
            ProductionBatch.objects.get_or_create(
                product=products["Cheese Bread"],
                baker=baker_user,
                quantity_produced=20,
                production_date=today - timedelta(days=6),
                expiration_date=today - timedelta(days=3),
                defaults={"status": ProductionBatch.STATUS_WASTED},
            )

        # Seed historical sales records across the past 7-10 days
        from inventory.models import SalesRecord
        if not SalesRecord.objects.exists():
            sample_sales = [
                ("Pandesal", 7, 140),
                ("Pandesal", 6, 155),
                ("Pandesal", 5, 148),
                ("Pandesal", 4, 162),
                ("Pandesal", 3, 150),
                ("Pandesal", 2, 165),
                ("Pandesal", 1, 158),
                ("Spanish Bread", 6, 58),
                ("Spanish Bread", 4, 62),
                ("Spanish Bread", 2, 65),
                ("Spanish Bread", 1, 60),
                ("Cheese Bread", 5, 42),
                ("Cheese Bread", 3, 46),
                ("Cheese Bread", 1, 44),
                ("Ensaymada", 6, 28),
                ("Ensaymada", 4, 32),
                ("Ensaymada", 2, 30),
                ("Ensaymada", 1, 35),
            ]
            for prod_name, days_ago, qty in sample_sales:
                prod = products[prod_name]
                SalesRecord.objects.create(
                    product=prod,
                    quantity_sold=qty,
                    unit_price=prod.unit_price,
                    sale_date=today - timedelta(days=days_ago),
                    recorded_by=staff_user,
                )
            self.stdout.write(self.style.SUCCESS(f"Seeded {len(sample_sales)} historical sales records."))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Sample ingredients, products, historical sales, and batches ready."))
        self.stdout.write("Log in at http://127.0.0.1:8000/login/ with:")
        self.stdout.write("  admin / breadbasket123  (Administrator)")
        self.stdout.write("  baker / breadbasket123  (Baker)")
        self.stdout.write("  staff / breadbasket123  (Inventory Staff)")
