from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from .models import (
    Categoria, Contratista, Herramienta, Obra, OrdenMantenimiento, PlanMantenimiento, Prestamo,
)
from .validators import normalizar_rut, validar_rut


class FechaInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ["nombre", "descripcion"]


class ObraForm(forms.ModelForm):
    class Meta:
        model = Obra
        fields = ["nombre", "direccion", "comuna", "activa"]


class ContratistaForm(forms.ModelForm):
    class Meta:
        model = Contratista
        fields = ["razon_social", "rut", "contacto", "telefono", "email", "activo"]
        widgets = {"rut": forms.TextInput(attrs={"placeholder": "76.123.456-7"})}

    def clean_rut(self):
        return normalizar_rut(self.cleaned_data["rut"])


class HerramientaForm(forms.ModelForm):
    class Meta:
        model = Herramienta
        fields = [
            "codigo", "nombre", "categoria", "marca", "modelo", "numero_serie", "ubicacion",
            "tarifa_diaria", "valor_reposicion", "horas_uso", "fecha_adquisicion", "observaciones",
        ]
        widgets = {
            "fecha_adquisicion": FechaInput(),
            "observaciones": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_codigo(self):
        return self.cleaned_data["codigo"].strip().upper()


class CambioEstadoForm(forms.Form):
    estado = forms.ChoiceField(label="Nuevo estado")
    motivo = forms.CharField(label="Motivo", max_length=250)

    def __init__(self, *args, opciones=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["estado"].choices = [(e.value, e.label) for e in opciones]


class EntregaForm(forms.Form):
    herramienta = forms.ModelChoiceField(
        queryset=Herramienta.objects.filter(estado=Herramienta.Estado.DISPONIBLE),
        empty_label="Elige una herramienta disponible",
    )
    contratista = forms.ModelChoiceField(
        queryset=Contratista.objects.filter(activo=True), empty_label="Elige un contratista"
    )
    obra = forms.ModelChoiceField(queryset=Obra.objects.filter(activa=True), empty_label="Elige una obra")
    responsable_nombre = forms.CharField(label="Nombre del responsable de obra", max_length=120)
    responsable_rut = forms.CharField(
        label="RUT del responsable", max_length=12, validators=[validar_rut],
        widget=forms.TextInput(attrs={"placeholder": "12.345.678-5"}),
    )
    fecha_limite = forms.DateField(label="Fecha límite de devolución", widget=FechaInput())
    condicion = forms.ChoiceField(
        label="Condición de la herramienta",
        choices=[(c.value, c.label) for c in (Prestamo.Condicion.BUENA, Prestamo.Condicion.DESGASTE)],
    )
    observaciones = forms.CharField(label="Observaciones", max_length=250, required=False)
    firma = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields["fecha_limite"].initial = timezone.localdate() + timedelta(days=7)
        self.fields["fecha_limite"].widget.attrs["min"] = timezone.localdate().isoformat()


class DevolucionForm(forms.Form):
    condicion = forms.ChoiceField(label="Condición al devolver", choices=Prestamo.Condicion.choices)
    horas_uso = forms.DecimalField(
        label="Horas de uso durante el préstamo", min_value=0, max_digits=8, decimal_places=1, initial=0
    )
    cargo_danos = forms.IntegerField(
        label="Cargo por daño o extravío (CLP)", min_value=0, required=False,
        help_text="Si la herramienta se extravió y lo dejas vacío, se cobra su valor de reposición.",
    )
    observaciones = forms.CharField(
        label="Observaciones", max_length=250, required=False, widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Obligatorias si la herramienta vuelve dañada o se extravió.",
    )
    responsable_nombre = forms.CharField(label="Quién firma la devolución", max_length=120)
    responsable_rut = forms.CharField(label="RUT de quien firma", max_length=12, validators=[validar_rut])
    firma = forms.CharField(widget=forms.HiddenInput, required=False)


class PlanForm(forms.ModelForm):
    class Meta:
        model = PlanMantenimiento
        fields = [
            "herramienta", "nombre", "instrucciones", "intervalo_dias", "intervalo_horas",
            "ultima_fecha", "ultimas_horas", "activo",
        ]
        widgets = {"ultima_fecha": FechaInput(), "instrucciones": forms.Textarea(attrs={"rows": 3})}
        help_texts = {
            "ultimas_horas": "Horas que marcaba la herramienta en su última mantención. El próximo vencimiento se cuenta desde aquí.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["herramienta"].queryset = Herramienta.objects.exclude(estado=Herramienta.Estado.BAJA)

    def clean(self):
        datos = super().clean()
        if not datos.get("intervalo_dias") and not datos.get("intervalo_horas"):
            raise forms.ValidationError("Define un intervalo en días, en horas de uso o en ambos.")
        return datos


def _tecnicos():
    return get_user_model().objects.filter(
        Q(groups__name="Técnico") | Q(groups__name="Administrador") | Q(is_superuser=True), is_active=True
    ).distinct()


class OrdenForm(forms.ModelForm):
    class Meta:
        model = OrdenMantenimiento
        fields = ["herramienta", "tipo", "descripcion", "fecha_programada", "tecnico"]
        widgets = {"fecha_programada": FechaInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["herramienta"].queryset = Herramienta.objects.exclude(estado=Herramienta.Estado.BAJA)
        self.fields["tecnico"].queryset = _tecnicos()
        self.fields["tecnico"].label_from_instance = lambda u: u.get_full_name() or u.username


class CompletarOrdenForm(forms.Form):
    trabajo_realizado = forms.CharField(label="Trabajo realizado", widget=forms.Textarea(attrs={"rows": 3}))
    costo = forms.IntegerField(label="Costo (CLP)", min_value=0, initial=0)


class BloqueoForm(forms.Form):
    motivo = forms.CharField(label="Motivo del bloqueo", max_length=200)
