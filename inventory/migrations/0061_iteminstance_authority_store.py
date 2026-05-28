from django.db import migrations, models
import django.db.models.deletion


def backfill_authority_store(apps, schema_editor):
    ItemInstance = apps.get_model('inventory', 'ItemInstance')
    Location = apps.get_model('inventory', 'Location')

    locations = {
        location.id: location
        for location in Location.objects.only('id', 'parent_location_id', 'is_store')
    }

    def nearest_store(location_id):
        seen = set()
        current = locations.get(location_id)
        while current and current.id not in seen:
            seen.add(current.id)
            if current.is_store:
                return current.id
            current = locations.get(current.parent_location_id)
        return None

    for item_instance in ItemInstance.objects.only('id', 'current_location_id').iterator():
        authority_store_id = nearest_store(item_instance.current_location_id)
        if authority_store_id:
            ItemInstance.objects.filter(id=item_instance.id).update(authority_store_id=authority_store_id)


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0060_locationtag_location_tags'),
    ]

    operations = [
        migrations.AddField(
            model_name='iteminstance',
            name='authority_store',
            field=models.ForeignKey(
                blank=True,
                help_text='Store that currently owns this instance. Allocations keep this store while current location may move.',
                limit_choices_to={'is_store': True},
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='owned_instances',
                to='inventory.location',
            ),
        ),
        migrations.RunPython(backfill_authority_store, migrations.RunPython.noop),
    ]
