from django.db import migrations, models


def rename_batch_tracking(apps, schema_editor):
    Category = apps.get_model('inventory', 'Category')
    Category.objects.filter(tracking_type='BATCH').update(tracking_type='QUANTITY')


def restore_batch_tracking(apps, schema_editor):
    Category = apps.get_model('inventory', 'Category')
    Category.objects.filter(tracking_type='QUANTITY').update(tracking_type='BATCH')


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0043_item_low_stock_threshold'),
    ]

    operations = [
        migrations.RunPython(rename_batch_tracking, restore_batch_tracking),
        migrations.AlterField(
            model_name='category',
            name='tracking_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('INDIVIDUAL', 'Individual Tracking (Serial/QR)'),
                    ('QUANTITY', 'Quantity Based Tracking'),
                ],
                help_text='Operational nature. Assigned at subcategory level.',
                max_length=20,
                null=True,
            ),
        ),
        migrations.RemoveField(
            model_name='iteminstance',
            name='batch',
        ),
    ]
