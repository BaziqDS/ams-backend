from django.contrib.auth.models import User, Group
from django.contrib.auth import get_user_model

User = get_user_model()
try:
    # Try to find a user in the group
    group = Group.objects.get(name='Central Store Manager')
    users = group.user_set.all()
    if users:
        user = users[0]
        print(f"Checking permissions for user: {user.username}")
        perms = user.get_all_permissions()
        print("Permissions:")
        for p in sorted(perms):
            print(f" - {p}")
        
        print("\nGroup permissions:")
        for gp in group.permissions.all():
            print(f" - {gp.content_type.app_label}.{gp.codename}")
    else:
        print("No users found in Central Store Manager group.")
except Group.DoesNotExist:
    print("Central Store Manager group not found.")
except Exception as e:
    print(f"Error: {e}")
