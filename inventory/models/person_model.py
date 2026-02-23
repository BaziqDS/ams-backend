from django.db import models

class Person(models.Model):
    name = models.CharField(max_length=255)
    designation = models.CharField(max_length=255, blank=True, null=True)
    department = models.CharField(max_length=255, blank=True, null=True)
    standalone_locations = models.ManyToManyField('inventory.Location', related_name='persons', blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        permissions = [
            ("can_issue_to_any_person", "Can issue stock to any person university-wide"),
        ]

    def __str__(self):
        if self.designation:
            parts.append(f"- {self.designation}")
        return " ".join(parts)
