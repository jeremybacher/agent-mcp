"""Entradas y salidas del CLI y de la UI, con sus controles de seguridad."""

import csv
import os
import re

import validacion

MAX_FILAS_CSV = 200
MAX_BYTES_CSV = 64 * 1024
MAX_LARGO_TOKEN = 20
_SEPARADORES = re.compile(r"[\s,;]+")
_SOLO_NUMERICO = re.compile(r"^[\d-]*\d[\d-]*$")


class EntradaInvalidaError(ValueError):
    """El CSV, el texto o la ruta de salida no cumplen las reglas de seguridad."""


def extraer_cuits(texto: str) -> tuple[list[str], list[str]]:
    """Extrae los CUITs de un texto pegado (uno por línea, coma o CSV).

    Solo se consideran los tokens formados por dígitos y guiones; el resto
    (encabezados, nombres, notas) se ignora. Devuelve (válidos, inválidos),
    normalizados, sin duplicados y en orden de aparición.
    """
    validos: list[str] = []
    invalidos: list[str] = []
    vistos: set[str] = set()
    for token in _SEPARADORES.split(texto):
        if not _SOLO_NUMERICO.match(token):
            continue
        cuit = validacion.normalizar_cuit(token)
        if len(cuit) > MAX_LARGO_TOKEN:
            raise EntradaInvalidaError("hay un número demasiado largo para ser un CUIT")
        if cuit in vistos:
            continue
        vistos.add(cuit)
        if len(vistos) > MAX_FILAS_CSV:
            raise EntradaInvalidaError(f"hay más de {MAX_FILAS_CSV} CUITs")
        (validos if validacion.validar_cuit(cuit) else invalidos).append(cuit)
    return validos, invalidos


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
