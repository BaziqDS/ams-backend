import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ams.settings')
django.setup()

from inventory.models import Location
from user_management.models import UserProfile
from django.contrib.auth.models import User

try:
    # Let's find Central Store
    central_store = Location.objects.filter(name__icontains='Central').first()
    if not central_store:
        central_store = Location.objects.filter(is_store=True, hierarchy_level=1).first()

    print(f"Central Store: {central_store}")

    # Let's find Room 1
    room_1 = Location.objects.filter(name__icontains='Room 1').first()
    print(f"Room 1: {room_1}")
    if room_1:
        print(f"Room 1 hierarchy path: {room_1.hierarchy_path}")

    # Let's get the standalone for Central Store
    if central_store:
        standalone = central_store.get_parent_standalone()
        print(f"Central Store Standalone: {standalone}")
        if standalone:
            print(f"Standalone hierarchy path: {standalone.hierarchy_path}")

            # Let's see the child standalones
            child_standalones = Location.objects.filter(
                is_standalone=True,
                hierarchy_path__startswith=f"{standalone.hierarchy_path}/"
            )
            print(f"Child standalones: {[loc.name for loc in child_standalones]}")

            # Let's test the exclusion logic directly
            from django.db.models import Q
            q_exclude = Q()
            for child in child_standalones:
                q_exclude |= Q(hierarchy_path__startswith=child.hierarchy_path)

            dept_locations = Location.objects.filter(
                hierarchy_path__startswith=standalone.hierarchy_path,
                is_store=False,
                is_active=True
            )

            excluded_locations = dept_locations.filter(q_exclude)
            print(f"\nThese locations SHOULD be excluded: {[loc.name for loc in excluded_locations]}")

            final_locations = dept_locations.exclude(q_exclude)
            print(f"\nFinal locations: {[loc.name for loc in final_locations]}")

    # Let's see what the function actually returns
    # We need an admin user
    admin_user = User.objects.filter(is_superuser=True).first()
    if not admin_user:
        print("No superuser found")
    else:
        profile = admin_user.profile
        if central_store:
            targets = profile.get_allocatable_targets(central_store)
            print(f"\nTargets returned by get_allocatable_targets:")
            print([(loc.id, loc.name) for loc in targets['locations']])
except Exception as e:
    import traceback
    traceback.print_exc()
