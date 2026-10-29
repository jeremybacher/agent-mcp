"""Integración del CLI completo (`agent.main`): lee el `.agent.md` y la skill
reales, levanta `server.py` real por stdio, corre el runner y escribe el
informe. Solo el modelo es un doble guionado (sin Gemini) y el servidor usa una
base temporal con el CUIT ya guardado, así que nada sale a la red. Patrón AAA."""

import os
import sys
from pathlib import Path

import pytest

import agent
import historia
from agente.config import cargar_agente
from agente.mcp_cliente import ClienteMCP
from agente.modelo import LlamadaHerramienta, Turno

CUIT_GUARDADO = "30000000066"
CUIT_INVALIDO = "20000000029"
INFORME = "# Informe de proveedores\n\n| CUIT | Estado |\n|---|---|\n"


def _llamada_guardado():
    return Turno(llamadas=(LlamadaHerramienta("consultar_cuit", {"cuit": CUIT_GUARDADO}),))


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Base temporal con un CUIT guardado, agente con el Python del test y salida en tmp."""
    ruta_db = str(tmp_path / "historial.db")
    monkeypatch.setattr(historia, "DB_PATH", ruta_db)
    historia.inicializar_db()
    historia.guardar_consulta(
        CUIT_GUARDADO, {"persona": {"razonSocial": "ACME SA", "estadoClave": "ACTIVO"}}
    )

    # El servidor corre en un subproceso: necesita la base temporal por entorno.
    env = {"ARCA_HISTORIAL_DB": ruta_db, "PATH": os.environ.get("PATH", "")}
    monkeypatch.setattr(agent, "ClienteMCP", lambda *a, **k: ClienteMCP(*a, env=env, **k))

    informes = tmp_path / "informes"
    monkeypatch.setattr(agent, "DIRECTORIO_INFORMES", str(informes))

    # Mismo agente que el real, pero con el Python que corre los tests: no depende de venv/.
    original = Path(agent.AGENTE_POR_DEFECTO).read_text(encoding="utf-8")
    ajustado = original.replace("command: venv/bin/python3", f"command: {sys.executable}")
    assert ajustado != original, "el .agent.md ya no usa 'command: venv/bin/python3'"
    ruta_agente = tmp_path / "agente.agent.md"
    ruta_agente.write_text(ajustado, encoding="utf-8")

    csv = tmp_path / "proveedores.csv"
    csv.write_text(f"cuit\n{CUIT_GUARDADO}\n{CUIT_INVALIDO}\n", encoding="utf-8")

    return {"agente": str(ruta_agente), "csv": str(csv), "informes": informes}


@pytest.fixture
def modelo_falso(monkeypatch):
    """Reemplaza `ModeloGemini` por un doble que sigue un guion y registra todo."""
    instancias = []

    class ModeloGuionado:
        guion = (_llamada_guardado(), Turno(texto=INFORME))

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.recibido = []
            self._turnos = list(type(self).guion)
            instancias.append(self)

        def enviar(self, entrada):
            self.recibido.append(entrada)
            return self._turnos.pop(0) if len(self._turnos) > 1 else self._turnos[0]

    monkeypatch.setattr(agent, "ModeloGemini", ModeloGuionado)
    return ModeloGuionado, instancias


def _ejecutar(entorno, *extra):
    return agent.main(["--agente", entorno["agente"], *extra])


def test_flujo_completo_desde_csv_escribe_el_informe(entorno, modelo_falso, capsys):
    # Arrange
    _, instancias = modelo_falso
    # Act
    codigo = _ejecutar(
        entorno, "--skill", "verificar-proveedores",
        "--csv", entorno["csv"], "--salida", "hoy.md",
    )
    # Assert
    salida = capsys.readouterr()
    assert codigo == 0
    assert INFORME in salida.out
    assert (entorno["informes"] / "hoy.md").read_text(encoding="utf-8") == INFORME + "\n"
    assert "consultar_cuit" in salida.err  # traza de la herramienta invocada
    assert len(instancias) == 1


def test_el_modelo_recibe_la_configuracion_declarada_en_el_agent_md(entorno, modelo_falso):
    # Arrange
    _, instancias = modelo_falso
    esperado = cargar_agente(entorno["agente"], agent.DIRECTORIO_SKILLS)
    # Act
    _ejecutar(entorno, "--skill", "verificar-proveedores", "--csv", entorno["csv"])
    # Assert
    kwargs = instancias[0].kwargs
    assert kwargs["modelo"] == esperado.modelo
    assert kwargs["temperature"] == esperado.temperature
    assert kwargs["max_output_tokens"] == esperado.max_output_tokens
    assert "Skill activa: verificar-proveedores" in kwargs["system_prompt"]


def test_solo_se_exponen_al_modelo_las_herramientas_de_la_skill(entorno, modelo_falso):
    # Arrange
    _, instancias = modelo_falso
    # Act
    _ejecutar(entorno, "--skill", "verificar-proveedores", "--csv", entorno["csv"])
    # Assert: el servidor publica 3 herramientas, la skill declara solo una.
    assert [h.nombre for h in instancias[0].kwargs["herramientas"]] == ["consultar_cuit"]


def test_el_csv_descarta_localmente_el_cuit_invalido_y_consulta_el_valido(
    entorno, modelo_falso
):
    # Arrange
    _, instancias = modelo_falso
    # Act
    _ejecutar(entorno, "--skill", "verificar-proveedores", "--csv", entorno["csv"])
    # Assert
    modelo = instancias[0]
    pedido, resultados = modelo.recibido[0], modelo.recibido[1]
    assert CUIT_GUARDADO in pedido
    assert f"no los consultes y reportalos como 'CUIT inválido': {CUIT_INVALIDO}" in pedido
    (resultado,) = resultados
    assert resultado.resultado["_origen"] == "historial"  # vino del historial, sin ARCA
    assert resultado.resultado["persona"]["razonSocial"] == "ACME SA"


def test_skill_no_habilitada_falla_antes_de_llamar_al_modelo(entorno, modelo_falso, capsys):
    # Arrange
    _, instancias = modelo_falso
    # Act
    codigo = _ejecutar(entorno, "--skill", "inexistente", "hola")
    # Assert
    assert codigo == 2
    assert "no está habilitada" in capsys.readouterr().err
    assert instancias == []


def test_salida_fuera_de_informes_se_rechaza_antes_de_arrancar(entorno, modelo_falso, capsys):
    # Arrange
    _, instancias = modelo_falso
    # Act
    codigo = _ejecutar(
        entorno, "--skill", "verificar-proveedores", "hola", "--salida", "../afuera.md"
    )
    # Assert
    assert codigo == 2
    assert "dentro de 'informes/'" in capsys.readouterr().err
    assert instancias == []
    assert not (entorno["informes"].parent / "afuera.md").exists()


def test_un_modelo_que_nunca_termina_corta_por_max_tool_iterations(
    entorno, modelo_falso, capsys
):
    # Arrange: el guion pide la herramienta indefinidamente.
    clase, instancias = modelo_falso
    clase.guion = (_llamada_guardado(),)
    maximo = cargar_agente(entorno["agente"], agent.DIRECTORIO_SKILLS).max_tool_iterations
    # Act
    codigo = _ejecutar(entorno, "--skill", "verificar-proveedores", "hola")
    # Assert
    assert codigo == 2
    assert f"máximo de {maximo} iteraciones" in capsys.readouterr().err
    assert len(instancias[0].recibido) == maximo
    assert not list(entorno["informes"].glob("*"))  # no se escribió un informe a medias
