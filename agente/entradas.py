"""Entradas y salidas del CLI con sus controles de seguridad."""

import csv
import os

import validacion

MAX_FILAS_CSV = 200
MAX_BYTES_CSV = 64 * 1024


class EntradaInvalidaError(ValueError):
    """El CSV o la ruta de salida no cumplen las reglas de seguridad."""


def leer_csv_cuits(path: str) -> tuple[list[str], list[str]]:
    """Lee la columna `cuit` de un CSV y devuelve (válidos, inválidos).

    Los CUITs se devuelven normalizados y sin duplicados, en orden de aparición.
    Se rechazan archivos grandes o con demasiadas filas.
    """
    try:
        tamano = os.path.getsize(path)
    except OSError as exc:
        raise EntradaInvalidaError(f"no se pudo leer '{path}': {exc.strerror}") from exc
    if tamano > MAX_BYTES_CSV:
        raise EntradaInvalidaError(f"el CSV supera {MAX_BYTES_CSV // 1024} KB")

    with open(path, newline="", encoding="utf-8-sig") as archivo:
        lector = csv.DictReader(archivo)
        campos = [c.strip().lower() for c in (lector.fieldnames or [])]
        if "cuit" not in campos:
            raise EntradaInvalidaError("el CSV debe tener una columna 'cuit'")
        columna = lector.fieldnames[campos.index("cuit")]

        validos: list[str] = []
        invalidos: list[str] = []
        vistos: set[str] = set()
        for numero, fila in enumerate(lector, start=1):
            if numero > MAX_FILAS_CSV:
                raise EntradaInvalidaError(f"el CSV supera {MAX_FILAS_CSV} filas")
            cuit = validacion.normalizar_cuit(fila.get(columna) or "")
            if not cuit or cuit in vistos:
                continue
            vistos.add(cuit)
            (validos if validacion.validar_cuit(cuit) else invalidos).append(cuit)

    return validos, invalidos


def armar_pedido_verificacion(validos: list[str], invalidos: list[str]) -> str:
    """Arma el pedido para la skill `verificar-proveedores` a partir de un CSV."""
    pedido = "Verificá estos proveedores: " + ", ".join(validos) + "."
    if invalidos:
        pedido += (
            " Estos CUITs ya se descartaron localmente por dígito verificador "
            "incorrecto; no los consultes y reportalos como 'CUIT inválido': "
            + ", ".join(invalidos)
            + "."
        )
    return pedido


def resolver_salida(ruta: str, directorio_informes: str) -> str:
    """Valida que `ruta` caiga dentro de `directorio_informes` y sea un `.md`."""
    base = os.path.realpath(directorio_informes)
    destino = os.path.realpath(os.path.join(base, ruta))
    if os.path.commonpath([base, destino]) != base or destino == base:
        raise EntradaInvalidaError("la salida debe quedar dentro de 'informes/'")
    if not destino.endswith(".md"):
        raise EntradaInvalidaError("la salida debe ser un archivo .md")
    return destino
