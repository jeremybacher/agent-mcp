"""La documentación es parte del producto en un repo público: la tabla de tests del
README y sus enlaces tienen que coincidir con lo que realmente hay. Patrón AAA."""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
README = (RAIZ / "README.md").read_text(encoding="utf-8")


def test_la_tabla_de_tests_del_readme_lista_exactamente_los_archivos_de_test_que_existen():
    # Arrange
    nombrados = set(re.findall(r"`(test_[a-z_]+\.py)`", README))
    reales = {ruta.name for ruta in (RAIZ / "tests").glob("test_*.py")}
    # Act / Assert
    assert nombrados - reales == set(), "el README nombra tests que no existen"
    assert reales - nombrados == set(), "hay tests que el README no documenta"


def test_los_enlaces_relativos_del_readme_apuntan_a_archivos_que_existen():
    # Arrange
    destinos = set(re.findall(r"\]\(((?!https?:|#)[^)#\s]+)", README))
    # Act
    inexistentes = sorted(d for d in destinos if not (RAIZ / d).exists())
    # Assert
    assert destinos, "se esperaba al menos un enlace relativo"
    assert inexistentes == []


def test_las_anclas_internas_del_readme_apuntan_a_un_titulo_que_existe():
    # Arrange
    def ancla(titulo: str) -> str:
        return re.sub(r"[^\w\s-]", "", titulo.lower()).strip().replace(" ", "-")

    titulos = {ancla(t) for t in re.findall(r"^#+\s+(.*)$", README, re.MULTILINE)}
    usadas = set(re.findall(r"\]\(#([^)\s]+)\)", README))
    # Act / Assert
    assert usadas - titulos == set()
