import os
import django
import sys

# Setup Django
sys.path.append(os.path.join(os.getcwd(), 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ams.settings')
django.setup()

from inventory.models.location_model import Location, LocationType

def reproduce():
    root = Location.objects.order_by('id').first()
    cs = Location.objects.filter(is_standalone=True).exclude(id=root.id).first()
    
    if not cs:
        print("Creating a temporary department for testing...")
        cs = Location.objects.create(
            name='Test Dept',
            code='TEST-DEPT',
            parent_location=root,
            is_standalone=True,
            location_type=LocationType.DEPARTMENT
        )
    
    cs_store = cs.auto_created_store
    
    print(f"Parent unit: {cs.name} (ID: {cs.id})")
    print(f"Parent store: {cs_store.name} (ID: {cs_store.id})")
    
    try:
        # Replicating common data sent from frontend
        loc = Location(
            name='Manual Lab Store', 
            parent_location=cs_store, 
            location_type=LocationType.ROOM, # Common mismatch if user just toggles IS STORE
            is_store=True,
            is_standalone=False
        )
        loc.full_clean()
        loc.save()
        print('SUCCESS: Created successfully')
    except Exception as e:
        print(f'ERROR: {e}')

if __name__ == "__main__":
    reproduce()
