from django.db.models.signals import post_save, m2m_changed
from django.dispatch import receiver
from django.contrib.auth.models import User, Permission
from django.db import transaction
from .models import UserProfile

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()

@receiver(m2m_changed, sender=User.user_permissions.through)
def enforce_permission_dependencies_signal(sender, instance, action, pk_set, **kwargs):
    """
    Universal Rule Signal: whenever an action permission is added, 
    automatically add the view permission. Works in custom UI and Django Admin.
    """
    if action == "post_add" and pk_set:
        with transaction.atomic():
            permissions = Permission.objects.filter(pk__in=pk_set)
            view_perms_to_add = []
            
            for perm in permissions:
                if perm.codename.startswith(('add_', 'change_', 'delete_')):
                    model_name = perm.codename.split('_', 1)[1]
                    view_codename = f"view_{model_name}"
                    
                    # Check if user already has the view permission (either in pk_set or DB)
                    if not instance.user_permissions.filter(codename=view_codename).exists():
                        try:
                            view_perm = Permission.objects.get(
                                codename=view_codename,
                                content_type=perm.content_type
                            )
                            view_perms_to_add.append(view_perm.id)
                        except Permission.DoesNotExist:
                            pass
            
            if view_perms_to_add:
                # We use post_add to avoid recursion or conflicts, but we must be careful.
                # Adding to the same relationship triggers the signal again.
                # Using instance.user_permissions.add() with IDs will trigger "pre_add" and "post_add" again.
                # However, we check ".exists()" above, which prevents infinite loops for the same permission.
                instance.user_permissions.add(*view_perms_to_add)
