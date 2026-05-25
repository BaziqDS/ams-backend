from django.db import models

class Person(models.Model):
    perse_number = models.CharField(max_length=50, unique=True, null=True)
    name = models.CharField(max_length=255)
    designation = models.CharField(max_length=255, blank=True, null=True)
    department = models.CharField(max_length=255, blank=True, null=True)
    standalone_locations = models.ManyToManyField('inventory.Location', related_name='persons', blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Employee"
        verbose_name_plural = "Employees"
        permissions = [
            ("view_employees", "Can view employees module"),
            ("create_employees", "Can create employees module records"),
            ("edit_employees", "Can edit employees module records"),
            ("delete_employees", "Can delete employees module records"),
            ("can_issue_to_any_person", "Can issue stock to any person university-wide"),
        ]

    def __str__(self):
        parts = [self.name]
        if self.designation:
            parts.append(f"- {self.designation}")
        return " ".join(parts)
