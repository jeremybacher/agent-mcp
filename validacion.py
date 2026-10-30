"""Validación de entradas compartida por el servidor MCP y el agente."""

PREFIJOS_VALIDOS = ("20", "23", "24", "27", "30", "33", "34")
_PONDERADORES = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def normalizar_cuit(cuit: str) -> str:
    """Quita espacios y guiones de un CUIT."""
    return str(cuit).strip().replace("-", "").replace(" ", "")


def formatear_cuit(cuit: str) -> str:
    """Devuelve el CUIT como XX-XXXXXXXX-X; si no tiene 11 dígitos, lo deja igual."""
    normalizado = normalizar_cuit(cuit)
    if len(normalizado) != 11 or not normalizado.isascii() or not normalizado.isdigit():
        return str(cuit)
    return f"{normalizado[:2]}-{normalizado[2:10]}-{normalizado[10]}"


def digito_verificador(base: str) -> int | None:
    """Calcula el dígito verificador (módulo 11) de los primeros 10 dígitos.

    Devuelve None cuando el resultado es 10, caso en que AFIP/ARCA no emite
    el CUIT.
    """
    suma = sum(int(d) * p for d, p in zip(base, _PONDERADORES))
    resto = suma % 11
    if resto == 0:
        return 0
    verificador = 11 - resto
    return None if verificador == 10 else verificador


def validar_cuit(cuit: str) -> bool:
    """Indica si un CUIT es válido: 11 dígitos, prefijo conocido y verificador correcto."""
    cuit = normalizar_cuit(cuit)
    if len(cuit) != 11 or not cuit.isascii() or not cuit.isdigit():
        return False
    if cuit[:2] not in PREFIJOS_VALIDOS:
        return False
    return digito_verificador(cuit[:10]) == int(cuit[10])


def acotar_limite(limite: int, minimo: int = 1, maximo: int = 100) -> int:
    """Fuerza `limite` a quedar dentro de [minimo, maximo]."""
    return max(minimo, min(int(limite), maximo))
