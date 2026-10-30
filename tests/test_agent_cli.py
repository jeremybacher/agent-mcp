"""Tests unitarios de las utilidades del CLI (`agent.py`). Patrón AAA."""

import agent


def test_el_servidor_hereda_la_base_de_historial_elegida(monkeypatch):
    # Arrange
    monkeypatch.setenv("ARCA_HISTORIAL_DB", "/ruta/historial_alterno.db")
    # Act
    entorno = agent.entorno_del_servidor()
    # Assert
    assert entorno == {"ARCA_HISTORIAL_DB": "/ruta/historial_alterno.db"}


def test_sin_variables_para_heredar_no_se_pasa_entorno(monkeypatch):
    # Arrange
    monkeypatch.delenv("ARCA_HISTORIAL_DB", raising=False)
    # Act
    entorno = agent.entorno_del_servidor()
    # Assert
    assert entorno is None


def test_el_servidor_mcp_no_recibe_la_api_key_de_gemini(monkeypatch):
    # Arrange: el servidor no habla con Gemini, así que no necesita esa clave.
    monkeypatch.setenv("GEMINI_API_KEY", "clave-secreta")
    monkeypatch.setenv("ARCA_HISTORIAL_DB", "/ruta/db")
    # Act
    entorno = agent.entorno_del_servidor()
    # Assert
    assert "GEMINI_API_KEY" not in entorno
    assert "clave-secreta" not in entorno.values()
