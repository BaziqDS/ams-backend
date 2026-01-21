# Permission Rules & Security Model

This document outlines the universal rules and constraints applied to the system's permission model. These rules ensure consistency across all modules and maintain the integrity of user access controls.

## Universal Rules

### 1. View Dependency (Check-On-Action)
For any module (e.g., Locations, Categories, Assets), if a user is granted an "Action" permission, they must implicitly have the "View" permission for that module.

**Rule:**
Whenever an `add`, `change`, or `delete` permission is assigned to a user, the corresponding `view` permission for that same model must also be automatically assigned.

**Logic:**
- `add_<model>` -> implies `view_<model>`
- `change_<model>` -> implies `view_<model>`
- `delete_<model>` -> implies `view_<model>`

### 2. Module Consistency
These rules apply to all existing and future modules added to the system. The frontend and backend should enforce these dependencies to prevent states where a user can "add" an item but cannot "view" the list to confirm it.

## Implementation Details

### Backend (Global Enforcement)
- Located in `signals.py`.
- Uses Django's `m2m_changed` signal on the `User.user_permissions.through` model.
- Automatically captures ANY permission assignment, whether through the custom AMS UI, common APIs, or the standard **Django Admin panel**.
- When an `add`, `change`, or `delete` permission ID is added to a user, the signal automatically fetches and adds the corresponding `view` permission ID for that model.

### Frontend (User Experience)
- Located in `UserModal.tsx`.
- The `togglePermission` function provides immediate visual feedback by automatically checking the `view_` equivalent when a non-view permission is checked.
