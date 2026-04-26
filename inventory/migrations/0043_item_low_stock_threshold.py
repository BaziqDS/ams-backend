from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0042_stockregister_reopened_at_stockregister_reopened_by_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='low_stock_threshold',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Raise a low-stock warning when total quantity falls to or below this threshold.',
            ),
        ),
    ]
