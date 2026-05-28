from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user_management', '0007_rolemetadata'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='avatar',
            field=models.ImageField(blank=True, null=True, upload_to='user_avatars/'),
        ),
    ]
