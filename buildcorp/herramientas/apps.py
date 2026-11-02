from django.apps import AppConfig
from django.db.models.signals import post_migrate


class HerramientasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "herramientas"
    verbose_name = "Pañol de herramientas"

    def ready(self):
        from .roles import sincronizar_roles

        post_migrate.connect(sincronizar_roles, sender=self)
