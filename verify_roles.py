import os
import django

def verify_roles():
    from django.contrib.auth.models import Group
    roles = ['Stock In-charge', 'Location Head', 'Central Store Manager', 'AD Finance', 'System Admin']
    for role_name in roles:
        try:
            group = Group.objects.get(name=role_name)
            perms = sorted([p.codename for p in group.permissions.all()])
            print(f"Role: {role_name}")
            print(f"Permissions: {', '.join(perms)}")
            print("-" * 30)
        except Group.DoesNotExist:
            print(f"Role: {role_name} NOT FOUND")
            print("-" * 30)

if __name__ == "__main__":
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ams.settings')
    django.setup()
    verify_roles()
