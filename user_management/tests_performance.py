from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from user_management.serializers import GroupSerializer


class GroupSerializerPrefetchPerformanceTests(TestCase):
    def test_group_permission_fields_use_prefetched_permissions_without_extra_queries(self):
        permissions = list(
            Permission.objects.select_related("content_type")
            .filter(content_type__app_label__in=["inventory", "user_management"])
            .order_by("id")[:5]
        )
        group = Group.objects.create(name="Prefetched Role")
        group.permissions.set(permissions)
        group.prefetched_permissions = permissions

        serializer = GroupSerializer(context={})
        with self.assertNumQueries(0):
            details = serializer.get_permissions_details(group)
            module_selections = serializer.get_module_selections(group)
            inspection_stages = serializer.get_inspection_stages(group)

        self.assertEqual([row["id"] for row in details], [perm.id for perm in permissions])
        self.assertIsInstance(module_selections, dict)
        self.assertIsInstance(inspection_stages, list)
