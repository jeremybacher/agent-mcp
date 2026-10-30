"""El repo es público: ningún CUIT de ejemplo puede coincidir con un contribuyente
real. Los CUITs de ejemplo y de prueba deben tener un cuerpo ficticio
(`0000000N`), que no corresponde a ningún DNI ni empresa. Patrón AAA."""

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
EXCLUIDOS = {"venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", "certs", "informes"}
EXTENSIONES = {".py", ".md", ".js", ".html", ".css", ".csv", ".txt", ".example", ".json", ".ini"}
# Prefijos de CUIT reales; el 99 de los tests es un prefijo inexistente a propósito.
CUIT = re.compile(r"(?<!\d)(20|23|24|27|30|33|34)(-?)(\d{8})\2(\d)(?!\d)")
CUERPO_FICTICIO = re.compile(r"^0000000\d$")


def _archivos():
    for ruta in RAIZ.rglob("*"):
        if not ruta.is_file() or EXCLUIDOS & set(ruta.relative_to(RAIZ).parts):
            continue
        if ruta.suffix in EXTENSIONES or ruta.name == ".env.example":
            yield ruta


@pytest.mark.parametrize("ruta", sorted(_archivos()), ids=lambda r: str(r.relative_to(RAIZ)))
def test_los_cuits_de_ejemplo_tienen_cuerpo_ficticio(ruta):
    # Arrange
    texto = ruta.read_text(encoding="utf-8", errors="ignore")
    # Act
    reales = [m.group(0) for m in CUIT.finditer(texto) if not CUERPO_FICTICIO.match(m.group(3))]
    # Assert
    assert reales == [], f"CUITs con forma de contribuyente real en {ruta.name}: {reales}"


def test_el_escaner_detecta_un_cuit_con_forma_real():
    # Arrange: verifica que la regla no sea vacía. Las muestras se arman por partes
    # para que este archivo no contenga ningún CUIT con forma real.
    con_guiones = "30-" + "71234567" + "-1"
    sin_guiones = "20" + "30405060" + "9"
    texto = f"proveedor {con_guiones} y {sin_guiones}"
    # Act
    reales = [m.group(0) for m in CUIT.finditer(texto) if not CUERPO_FICTICIO.match(m.group(3))]
    # Assert
    assert reales == [con_guiones, sin_guiones]
