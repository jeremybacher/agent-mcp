"""Tests de `agente.entradas`: lectura acotada de CSV y confinamiento de la
ruta de salida (AppSec). Patrón AAA."""

import pytest

from agente import entradas
from agente.entradas import EntradaInvalidaError

VALIDO = "20000000028"
OTRO_VALIDO = "30000000066"
INVALIDO = "20000000029"


def _csv(tmp_path, contenido, nombre="p.csv"):
    ruta = tmp_path / nombre
    ruta.write_text(contenido, encoding="utf-8")
    return str(ruta)


def test_leer_csv_separa_validos_e_invalidos(tmp_path):
    # Arrange
    ruta = _csv(tmp_path, f"cuit\n{VALIDO}\n{INVALIDO}\n20-00000002-8\n{OTRO_VALIDO}\n")
    # Act
    validos, invalidos = entradas.leer_csv_cuits(ruta)
    # Assert
    assert validos == [VALIDO, OTRO_VALIDO]  # el duplicado con guiones se descarta
    assert invalidos == [INVALIDO]


def test_leer_csv_tolera_bom_y_encabezado_en_mayusculas(tmp_path):
    # Arrange
    ruta = tmp_path / "p.csv"
    ruta.write_bytes(b"\xef\xbb\xbfCUIT,nombre\n" + VALIDO.encode() + b",ACME\n")
    # Act
    validos, _ = entradas.leer_csv_cuits(str(ruta))
    # Assert
    assert validos == [VALIDO]


def test_leer_csv_ignora_filas_vacias(tmp_path):
    # Arrange
    ruta = _csv(tmp_path, f"cuit\n\n{VALIDO}\n\n")
    # Act
    validos, invalidos = entradas.leer_csv_cuits(ruta)
    # Assert
    assert (validos, invalidos) == ([VALIDO], [])


def test_leer_csv_sin_columna_cuit_falla(tmp_path):
    # Arrange
    ruta = _csv(tmp_path, "nombre\nACME\n")
    # Act / Assert
    with pytest.raises(EntradaInvalidaError, match="columna 'cuit'"):
        entradas.leer_csv_cuits(ruta)


def test_leer_csv_inexistente_falla(tmp_path):
    # Arrange
    ruta = str(tmp_path / "no_existe.csv")
    # Act / Assert
    with pytest.raises(EntradaInvalidaError, match="no se pudo leer"):
        entradas.leer_csv_cuits(ruta)


def test_leer_csv_con_demasiadas_filas_falla(tmp_path, monkeypatch):
    # Arrange
    monkeypatch.setattr(entradas, "MAX_FILAS_CSV", 2)
    ruta = _csv(tmp_path, "cuit\n20000000028\n30000000066\n27000000030\n")
    # Act / Assert
    with pytest.raises(EntradaInvalidaError, match="filas"):
        entradas.leer_csv_cuits(ruta)


def test_leer_csv_demasiado_grande_falla(tmp_path, monkeypatch):
    # Arrange
    monkeypatch.setattr(entradas, "MAX_BYTES_CSV", 10)
    ruta = _csv(tmp_path, "cuit\n" + VALIDO + "\n")
    # Act / Assert
    with pytest.raises(EntradaInvalidaError, match="KB"):
        entradas.leer_csv_cuits(ruta)


def test_extraer_cuits_de_texto_libre_separa_validos_e_invalidos():
    # Arrange
    texto = f"{VALIDO}\n{INVALIDO}, {OTRO_VALIDO};20-00000002-8"
    # Act
    validos, invalidos = entradas.extraer_cuits(texto)
    # Assert
    assert validos == [VALIDO, OTRO_VALIDO]  # el último repite VALIDO con guiones
    assert invalidos == [INVALIDO]


def test_extraer_cuits_acepta_un_csv_pegado_e_ignora_encabezados_y_notas():
    # Arrange
    texto = f"cuit,nota\n{VALIDO},proveedor de ejemplo (ficticio)\n{OTRO_VALIDO},SA\n"
    # Act
    validos, invalidos = entradas.extraer_cuits(texto)
    # Assert
    assert (validos, invalidos) == ([VALIDO, OTRO_VALIDO], [])


@pytest.mark.parametrize("texto", ["", "   \n ", "hola mundo", "cuit,nota", "q1-2024x"])
def test_extraer_cuits_sin_numeros_devuelve_vacio(texto):
    # Arrange / Act
    resultado = entradas.extraer_cuits(texto)
    # Assert
    assert resultado == ([], [])


def test_extraer_cuits_con_demasiados_falla(monkeypatch):
    # Arrange
    monkeypatch.setattr(entradas, "MAX_FILAS_CSV", 2)
    texto = f"{VALIDO} {OTRO_VALIDO} 20000000037"
    # Act / Assert
    with pytest.raises(EntradaInvalidaError, match="más de 2"):
        entradas.extraer_cuits(texto)


def test_extraer_cuits_rechaza_un_numero_gigante_en_lugar_de_pasarlo_al_prompt():
    # Arrange
    texto = "9" * 5000
    # Act / Assert
    with pytest.raises(EntradaInvalidaError, match="demasiado largo"):
        entradas.extraer_cuits(texto)


def test_armar_pedido_incluye_los_invalidos_como_descartados():
    # Arrange
    validos, invalidos = [VALIDO], [INVALIDO]
    # Act
    pedido = entradas.armar_pedido_verificacion(validos, invalidos)
    # Assert
    assert VALIDO in pedido
    assert f"no los consultes y reportalos como 'CUIT inválido': {INVALIDO}" in pedido


def test_armar_pedido_sin_invalidos_no_menciona_descartes():
    # Arrange / Act
    pedido = entradas.armar_pedido_verificacion([VALIDO], [])
    # Assert
    assert "descartaron" not in pedido


def test_resolver_salida_dentro_de_informes(tmp_path):
    # Arrange
    base = tmp_path / "informes"
    base.mkdir()
    # Act
    destino = entradas.resolver_salida("hoy.md", str(base))
    # Assert
    assert destino == str((base / "hoy.md").resolve())


@pytest.mark.parametrize(
    "ruta",
    [
        "../afuera.md",
        "../../etc/passwd.md",
        "/tmp/absoluta.md",
        "sub/../../afuera.md",
        ".",
        "",
    ],
)
def test_resolver_salida_rechaza_path_traversal(tmp_path, ruta):
    # Arrange
    base = tmp_path / "informes"
    base.mkdir()
    # Act / Assert
    with pytest.raises(EntradaInvalidaError, match="dentro de 'informes/'"):
        entradas.resolver_salida(ruta, str(base))


def test_resolver_salida_rechaza_extension_que_no_es_md(tmp_path):
    # Arrange
    base = tmp_path / "informes"
    base.mkdir()
    # Act / Assert
    with pytest.raises(EntradaInvalidaError, match=".md"):
        entradas.resolver_salida("informe.sh", str(base))


def test_resolver_salida_rechaza_symlink_que_escapa(tmp_path):
    # Arrange: un symlink dentro de informes/ que apunta afuera.
    base = tmp_path / "informes"
    base.mkdir()
    afuera = tmp_path / "afuera"
    afuera.mkdir()
    (base / "enlace").symlink_to(afuera)
    # Act / Assert
    with pytest.raises(EntradaInvalidaError, match="dentro de 'informes/'"):
        entradas.resolver_salida("enlace/x.md", str(base))
