from django.core.management.base import BaseCommand

from herramientas.services import procesar_alertas


class Command(BaseCommand):
    help = "Revisa morosidad y mantenciones: crea alertas, bloquea contratistas y programa órdenes."

    def handle(self, *args, **options):
        resumen = procesar_alertas()
        self.stdout.write(self.style.SUCCESS(str(resumen)))
