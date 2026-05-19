from django.db import migrations


def grant_view_all_to_existing_finance_reviewers(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model("auth", "User")

    content_type, _ = ContentType.objects.get_or_create(
        app_label="inventory",
        model="inspectioncertificate",
    )
    review_finance = Permission.objects.filter(
        content_type=content_type,
        codename="review_finance",
    ).first()
    if review_finance is None:
        return

    view_all, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename="view_all_inspections",
        defaults={"name": "Can view all inspection certificates university-wide"},
    )

    for group in Group.objects.filter(permissions=review_finance):
        group.permissions.add(view_all)

    for user in User.objects.filter(user_permissions=review_finance):
        user.user_permissions.add(view_all)


def revoke_backfilled_view_all(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    content_type = ContentType.objects.filter(
        app_label="inventory",
        model="inspectioncertificate",
    ).first()
    if content_type is None:
        return
    Permission.objects.filter(
        content_type=content_type,
        codename="view_all_inspections",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0054_alter_inspectioncertificate_options"),
    ]

    operations = [
        migrations.RunPython(
            grant_view_all_to_existing_finance_reviewers,
            revoke_backfilled_view_all,
        ),
    ]
