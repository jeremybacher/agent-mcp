"""Tests unitarios de `validacion`: CUIT con dígito verificador (módulo 11),
normalización de entrada y acotado de límites. Patrón AAA en cada test."""

import pytest

import validacion


@pytest.mark.parametrize(
    "cuit",
    [
        "20000000028",  # persona física, sin separadores
        "20-00000002-8",  # formato habitual con guiones
        "  20000000028  ",  # espacios en los extremos
        "20 00000002 8",  # espacios internos
        "27000000030",  # prefijo 27
        "30000000058",  # prefijo 30 (persona jurídica)
        "30000000066",  # verificador calculado a mano
    ],
)
def test_cuit_valido(cuit):
    # Arrange: el CUIT viene de la parametrización.
    # Act
    resultado = validacion.validar_cuit(cuit)
    # Assert
    assert resultado is True


@pytest.mark.parametrize(
    "cuit, motivo",
    [
        ("", "vacío"),
        ("123", "muy corto"),
        ("2000000002", "10 dígitos"),
        ("200000000290", "12 dígitos"),
        ("2000000002a", "contiene una letra"),
        ("abcdefghijk", "solo letras"),
        ("20000000029", "verificador incorrecto"),
        ("20000000027", "verificador incorrecto (off by one)"),
        ("99000000028", "prefijo inexistente"),
        ("00000000000", "todo ceros"),
        ("２００００００００２８", "dígitos unicode no ASCII"),
        ("20000000028; DROP TABLE consultas", "intento de inyección"),
    ],
)
def test_cuit_invalido(cuit, motivo):
    # Arrange: el CUIT y el motivo vienen de la parametrización.
    # Act
    resultado = validacion.validar_cuit(cuit)
    # Assert
    assert resultado is False, motivo


def test_normalizar_cuit_quita_guiones_y_espacios():
    # Arrange
    crudo = " 20-00000002-8 "
    # Act
    resultado = validacion.normalizar_cuit(crudo)
    # Assert
    assert resultado == "20000000028"


def test_digito_verificador_devuelve_none_cuando_da_diez():
    # Arrange: base elegida para que 11 - (suma % 11) == 10.
    base = "2000000001"
    # Act
    resultado = validacion.digito_verificador(base)
    # Assert
    assert resultado is None


def test_digito_verificador_devuelve_cero_cuando_el_resto_es_cero():
    # Arrange: suma = 0, entonces resto = 0.
    base = "0000000000"
    # Act
    resultado = validacion.digito_verificador(base)
    # Assert
    assert resultado == 0


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        (20, 20),  # dentro del rango
        (0, 1),  # por debajo del mínimo
        (-5, 1),  # negativo
        (100, 100),  # justo en el máximo
        (10_000, 100),  # por encima del máximo
        ("7", 7),  # string numérico
    ],
)
def test_acotar_limite(entrada, esperado):
    # Arrange: entrada y esperado vienen de la parametrización.
    # Act
    resultado = validacion.acotar_limite(entrada)
    # Assert
    assert resultado == esperado


def test_acotar_limite_rechaza_valores_no_numericos():
    # Arrange
    entrada = "muchos"
    # Act / Assert
    with pytest.raises(ValueError):
        validacion.acotar_limite(entrada)
