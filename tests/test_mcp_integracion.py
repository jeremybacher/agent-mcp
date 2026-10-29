"""Integración real: `ClienteMCP` levanta `server.py` por stdio y se comunica con
él mediante el protocolo MCP. Solo se usan caminos que no salen a la red (CUIT
inválido y resultados ya guardados en el historial), y el servidor apunta a una
base SQLite temporal vía `ARCA_HISTORIAL_DB`. Patrón AAA."""

import asyncio
import os
import sys

import pytest

import historia
from agente.mcp_cliente import ClienteMCP

DIRECTORIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUIT_GUARDADO = "30000000066"


@pytest.fixture
def entorno_servidor(tmp_path, monkeypatch):
    """Base temporal con una consulta ya guardada y el entorno para el subproceso."""
    ruta_db = str(tmp_path / "historial_integracion.db")
    monkeypatch.setattr(historia, "DB_PATH", ruta_db)
    historia.inicializar_db()
    historia.guardar_consulta(
        CUIT_GUARDADO,
        {"persona": {"razonSocial": "ACME SA", "estadoClave": "ACTIVO"}},
    )
    return {"ARCA_HISTORIAL_DB": ruta_db, "PATH": os.environ.get("PATH", "")}


def _con_servidor(entorno, corrutina):
    async def _correr():
        async with ClienteMCP(sys.executable, ("server.py",), DIRECTORIO, entorno) as cliente:
            return await corrutina(cliente)

    return asyncio.run(asyncio.wait_for(_correr(), timeout=30))


def test_si_el_servidor_no_arranca_falla_sin_colgarse(entorno_servidor):
    # Arrange: un script que termina enseguida, sin hablar MCP.
    async def intentar():
        async with ClienteMCP(sys.executable, ("-c", "pass"), DIRECTORIO, entorno_servidor):
            pass
    # Act / Assert
    with pytest.raises(BaseException):  # noqa: B017 - el tipo depende del transporte
        asyncio.run(asyncio.wait_for(intentar(), timeout=20))


def test_el_servidor_publica_las_tres_herramientas(entorno_servidor):
    # Arrange
    async def accion(cliente):
        return await cliente.listar_herramientas()
    # Act
    herramientas = _con_servidor(entorno_servidor, accion)
    # Assert
    assert {h.nombre for h in herramientas} == {
        "consultar_cuit",
        "historial_consultas",
        "buscar_en_historial",
    }
    consultar = next(h for h in herramientas if h.nombre == "consultar_cuit")
    assert "cuit" in consultar.esquema["properties"]


def test_cuit_con_verificador_incorrecto_se_rechaza_sin_llamar_a_arca(entorno_servidor):
    # Arrange
    async def accion(cliente):
        return await cliente.llamar("consultar_cuit", {"cuit": "20000000029"})
    # Act
    resultado = _con_servidor(entorno_servidor, accion)
    # Assert
    assert "no es un CUIT válido" in resultado["error"]


def test_consulta_de_cuit_guardado_se_resuelve_desde_el_historial(entorno_servidor):
    # Arrange
    async def accion(cliente):
        return await cliente.llamar("consultar_cuit", {"cuit": "30-00000006-6"})
    # Act
    resultado = _con_servidor(entorno_servidor, accion)
    # Assert
    assert resultado["_origen"] == "historial"
    assert resultado["persona"]["razonSocial"] == "ACME SA"


def test_historial_consultas_acota_el_limite(entorno_servidor):
    # Arrange: un límite absurdo no debe romper ni devolver más de lo permitido.
    async def accion(cliente):
        return await cliente.llamar("historial_consultas", {"limite": 10_000_000})
    # Act
    resultado = _con_servidor(entorno_servidor, accion)
    # Assert
    assert len(resultado["consultas"]) == 1
    assert resultado["consultas"][0]["cuit"] == CUIT_GUARDADO


def test_buscar_en_historial_distingue_encontrado_de_no_encontrado(entorno_servidor):
    # Arrange
    async def accion(cliente):
        hay = await cliente.llamar("buscar_en_historial", {"cuit": CUIT_GUARDADO})
        no_hay = await cliente.llamar("buscar_en_historial", {"cuit": "20000000028"})
        return hay, no_hay
    # Act
    hay, no_hay = _con_servidor(entorno_servidor, accion)
    # Assert
    assert hay["encontrado"] is True
    assert no_hay == {"encontrado": False, "cuit": "20000000028"}
