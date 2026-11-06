from django.db import migrations


def backfill_batch_quantities(apps, schema_editor):
    ProductionBatch = apps.get_model('inventory', 'ProductionBatch')
    for batch in ProductionBatch.objects.all():
        produced = int(batch.quantity_produced or 0)
        sold = int(batch.sold_quantity or 0)
        original = int(batch.original_quantity or 0) or produced
        remaining = int(batch.remaining_quantity or 0)
        waste = int(batch.waste_quantity or 0)

        if remaining == 0 and waste == 0 and sold == 0:
            remaining = produced

        if batch.status in ('expired', 'wasted') and waste == 0:
            leftover = max(0, original - sold) if remaining == 0 else remaining
            waste = leftover
            remaining = 0
            if leftover > 0:
                batch.status = 'wasted'

        batch.original_quantity = original
        batch.sold_quantity = sold
        batch.remaining_quantity = remaining
        batch.waste_quantity = waste
        batch.save()


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0002_alter_productionbatch_options_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_batch_quantities, migrations.RunPython.noop),
    ]
