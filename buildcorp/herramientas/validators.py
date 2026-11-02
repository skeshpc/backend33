import re

from django.core.exceptions import ValidationError


def normalizar_rut(valor):
    """Convierte '12.345.678-5' en '12345678-5'."""
    limpio = re.sub(r"[^0-9kK]", "", valor or "").upper()
    if len(limpio) < 2:
        return limpio
    return f"{limpio[:-1]}-{limpio[-1]}"


def digito_verificador(cuerpo):
    """Calcula el dígito verificador del RUT chileno con el algoritmo módulo 11."""
    suma = 0
    multiplicador = 2
    for digito in reversed(str(cuerpo)):
        suma += int(digito) * multiplicador
        multiplicador = 2 if multiplicador == 7 else multiplicador + 1
    resto = 11 - (suma % 11)
    return {11: "0", 10: "K"}.get(resto, str(resto))


def validar_rut(valor):
    rut = normalizar_rut(valor)
    if not re.fullmatch(r"\d{7,8}-[\dK]", rut):
        raise ValidationError("Escribe el RUT con este formato: 12.345.678-5.")
    cuerpo, digito = rut.split("-")
    if digito_verificador(cuerpo) != digito:
        raise ValidationError("El dígito verificador del RUT no es correcto.")
