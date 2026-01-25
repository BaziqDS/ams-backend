import os
import django
import sys

# Setup Django
sys.path.append(os.path.join(os.getcwd(), 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ams.settings')
django.setup()

from inventory.models.location_model import Location, LocationType
from django.core.management import call_command

def verify_hierarchy():
    print("--- Starting Hierarchy Verification ---")
    
    # Clean departmental test data, but preserve ID 1 and 2 if they exist
    # as per strict institutional requirements. 
    Location.objects.filter(code__in=['CS-DEPT', 'CS-DEPT-MAIN-STORE', 'HW-LAB-STR']).delete()
    
    # 1. Initialization
    print("Initializing hierarchy via management command...")
    # This command is idempotent and will preserve ID 1/2 if they exist
    call_command('initialize_hierarchy')
    
    # 2. Check Root
    root = Location.objects.order_by('id').first()
    if not root or not root.is_standalone or root.parent_location is not None:
        print(f"FAIL: Root location not found or invalid. Got: {root}")
        return

    central_store = root.auto_created_store
    
    print(f"Root Store found: {central_store} (ID: {central_store.pk if central_store else 'None'})")
    
    assert central_store is not None, "Central Store should exist"
    assert central_store.parent_location == root
    
    print(f"PASS: Root {root.name} (ID: {root.pk}) and {central_store.name} (ID: {central_store.pk}) verified.")
    
    # 3. Create Level 1 Standalone (Department)
    print("\nCreating Level 1 Standalone: Computer Science...")
    cs_dept = Location.objects.create(
        name='Computer Science Department',
        code='CS-DEPT',
        parent_location=root,
        location_type=LocationType.DEPARTMENT,
        is_standalone=True,
        is_active=True
    )
    
    # Refresh to get auto_created_store link
    cs_dept.refresh_from_db()
    cs_store = cs_dept.auto_created_store
    
    if not cs_store:
        print("FAIL: CS Dept Store was not auto-created.")
        return

    print(f"CS Dept Store parent is: {cs_store.parent_location} (ID: {cs_store.parent_location.id if cs_store.parent_location else 'None'})")
    
    assert cs_dept.parent_location == root
    assert cs_store.parent_location_id == cs_dept.id, f"CS Store parent should be CS Dept (ID {cs_dept.id}), but got {cs_store.parent_location_id}"
    
    print(f"PASS: Hierarchy Level 1 verified. {cs_dept.name} parented by {root.name}, {cs_store.name} parented by {cs_dept.name}.")
    
    # 4. Check Paths
    assert cs_store.hierarchy_path.startswith(f"{cs_dept.hierarchy_path}/"), f"Path mismatch: {cs_store.hierarchy_path}"
    print(f"PASS: Store Path verified: {cs_store.hierarchy_path}")

    # 5. Simulate Level 3 Store Creation (As frontend would resolve)
    print("\nSimulating Level 3 Store Creation: Hardware Lab Store (Parented by L2 Store)...")
    lab_store = Location.objects.create(
        name='Hardware Lab Store',
        code='HW-LAB-STR',
        parent_location=cs_store,
        location_type=LocationType.STORE,
        is_store=True,
        is_active=True
    )
    
    assert lab_store.parent_location == cs_store
    assert lab_store.hierarchy_path.startswith(f"{cs_store.hierarchy_path}/")
    print(f"PASS: Level 3 Store 'Hardware Lab Store' parented by {cs_store.name} (L2)")
    print(f"PASS: L3 Path verified: {lab_store.hierarchy_path}")

    # 6. Attempt Level 4 Store Creation (Should FAIL)
    print("\nAttempting Level 4 Store Creation: Micro-parts Cabinet (Should Fail)...")
    from django.core.exceptions import ValidationError
    try:
        cabinet = Location(
            name='Micro-parts Cabinet',
            code='MICRO-CAB',
            parent_location=lab_store,
            location_type=LocationType.STORE,
            is_store=True,
            is_active=True
        )
        cabinet.full_clean()
        cabinet.save()
        print("FAIL: Created Level 4 store, but it should have been blocked.")
        sys.exit(1)
    except ValidationError as e:
        print(f"PASS: Correctly blocked Level 4 creation. Error: {e}")
    
    print("\n--- Hierarchy Verification SUCCESS ---")

if __name__ == "__main__":
    try:
        verify_hierarchy()
    except Exception as e:
        print(f"FAIL: {e}")
        sys.exit(1)
