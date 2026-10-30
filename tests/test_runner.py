"""Tests de integración de `agente.runner`: el bucle del agente con un modelo
y un cliente MCP simulados (sin red, sin Gemini, sin ARCA). Patrón AAA."""

import asyncio

import pytest

from agente import runner
from agente.config import Agente, Skill
from agente.modelo import LlamadaHerramienta, ResultadoHerramienta, Turno


class ModeloGuionado:
    """Responde con una lista fija de turnos y guarda lo que recibe."""

    def __init__(self, turnos):
        self._turnos = list(turnos)
        self.recibido = []

    def enviar(self, entrada):
        self.recibido.append(entrada)
        return self._turnos.pop(0)


class HerramientasFalsas:
    """Registra las llamadas y responde según `respuestas` (o lanza si es Exception)."""

    def __init__(self, respuestas=None):
        self.respuestas = respuestas or {}
        self.llamadas = []

    async def llamar(self, nombre, argumentos):
        self.llamadas.append((nombre, argumentos))
        respuesta = self.respuestas.get(nombre, {"ok": True})
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta


@pytest.fixture
def agente():
    return Agente(
        nombre="analista",
        descripcion="d",
        provider="gemini",
        modelo="m",
        temperature=0.0,
        max_output_tokens=100,
        max_tool_iterations=3,
        system_prompt="Sos un analista.",
        mcp_command="python3",
        mcp_args=("server.py",),
    )


@pytest.fixture
def skill():
    return Skill(
        nombre="verificar",
        descripcion="d",
        herramientas=("consultar_cuit",),
        instrucciones="Consultá cada CUIT.",
    )


def _correr(agente, skill, modelo, herramientas, pedido="Verificá"):
    trazas = []
    texto = asyncio.run(
        runner.ejecutar(agente, skill, pedido, modelo, herramientas, trazas.append)
    )
    return texto, trazas


def test_sin_llamadas_devuelve_el_texto_del_modelo(agente, skill):
    # Arrange
    modelo = ModeloGuionado([Turno(texto="Listo")])
    herramientas = HerramientasFalsas()
    # Act
    texto, _ = _correr(agente, skill, modelo, herramientas)
    # Assert
    assert texto == "Listo"
    assert herramientas.llamadas == []
    assert modelo.recibido == ["Verificá"]


def test_ejecuta_la_herramienta_pedida_y_devuelve_el_resultado_al_modelo(agente, skill):
    # Arrange
    pedido_herramienta = Turno(
        llamadas=(LlamadaHerramienta("consultar_cuit", {"cuit": "30000000066"}),)
    )
    modelo = ModeloGuionado([pedido_herramienta, Turno(texto="Informe")])
    herramientas = HerramientasFalsas(
        {"consultar_cuit": {"persona": {"razonSocial": "ACME SA"}}}
    )
    # Act
    texto, trazas = _correr(agente, skill, modelo, herramientas)
    # Assert
    assert texto == "Informe"
    assert herramientas.llamadas == [("consultar_cuit", {"cuit": "30000000066"})]
    assert modelo.recibido[1] == [
        ResultadoHerramienta("consultar_cuit", {"persona": {"razonSocial": "ACME SA"}})
    ]
    assert any("consultar_cuit" in t for t in trazas)


def test_varias_llamadas_en_un_turno_se_ejecutan_en_orden(agente, skill):
    # Arrange
    turno = Turno(
        llamadas=(
            LlamadaHerramienta("consultar_cuit", {"cuit": "A"}),
            LlamadaHerramienta("consultar_cuit", {"cuit": "B"}),
        )
    )
    modelo = ModeloGuionado([turno, Turno(texto="fin")])
    herramientas = HerramientasFalsas()
    # Act
    _correr(agente, skill, modelo, herramientas)
    # Assert
    assert [a["cuit"] for _, a in herramientas.llamadas] == ["A", "B"]
    assert len(modelo.recibido[1]) == 2


def test_herramienta_fuera_de_la_skill_no_se_ejecuta(agente, skill):
    # Arrange: el modelo intenta usar una herramienta que la skill no declara.
    turno = Turno(llamadas=(LlamadaHerramienta("historial_consultas", {}),))
    modelo = ModeloGuionado([turno, Turno(texto="fin")])
    herramientas = HerramientasFalsas()
    # Act
    _correr(agente, skill, modelo, herramientas)
    # Assert
    assert herramientas.llamadas == []
    (resultado,) = modelo.recibido[1]
    assert "no está habilitada" in resultado.resultado["error"]


def test_error_de_la_herramienta_vuelve_al_modelo_sin_cortar_el_bucle(agente, skill):
    # Arrange
    turno = Turno(llamadas=(LlamadaHerramienta("consultar_cuit", {"cuit": "X"}),))
    modelo = ModeloGuionado([turno, Turno(texto="Reporté el fallo")])
    herramientas = HerramientasFalsas({"consultar_cuit": ConnectionError("sin red")})
    # Act
    texto, trazas = _correr(agente, skill, modelo, herramientas)
    # Assert
    assert texto == "Reporté el fallo"
    (resultado,) = modelo.recibido[1]
    assert "sin red" in resultado.resultado["error"]
    assert any("fallo en consultar_cuit" in t for t in trazas)


def test_corta_al_superar_max_tool_iterations(agente, skill):
    # Arrange: el modelo pide herramientas indefinidamente.
    turno = Turno(llamadas=(LlamadaHerramienta("consultar_cuit", {"cuit": "X"}),))
    modelo = ModeloGuionado([turno] * 10)
    herramientas = HerramientasFalsas()
    # Act / Assert
    with pytest.raises(runner.LimiteDeIteracionesError, match="3"):
        _correr(agente, skill, modelo, herramientas)
    assert len(herramientas.llamadas) == agente.max_tool_iterations


def test_respuesta_vacia_del_modelo_es_un_error(agente, skill):
    # Arrange
    modelo = ModeloGuionado([Turno(texto="   ")])
    # Act / Assert
    with pytest.raises(RuntimeError, match="ninguna respuesta"):
        _correr(agente, skill, modelo, HerramientasFalsas())


def test_respuesta_truncada_se_devuelve_con_advertencia(agente, skill):
    # Arrange
    modelo = ModeloGuionado([Turno(texto="| CUIT |", truncado=True)])
    # Act
    texto, trazas = _correr(agente, skill, modelo, HerramientasFalsas())
    # Assert
    assert texto == "| CUIT |"
    assert any("max_output_tokens" in t for t in trazas)


def test_respuesta_completa_no_emite_advertencia(agente, skill):
    # Arrange
    modelo = ModeloGuionado([Turno(texto="Listo")])
    # Act
    _, trazas = _correr(agente, skill, modelo, HerramientasFalsas())
    # Assert
    assert trazas == []


def test_armar_system_prompt_combina_agente_y_skill(agente, skill):
    # Arrange / Act
    prompt = runner.armar_system_prompt(agente, skill)
    # Assert
    assert prompt.startswith("Sos un analista.")
    assert "Skill activa: verificar" in prompt
    assert "Consultá cada CUIT." in prompt


# ---------- eventos y streaming ----------


class ModeloConStreaming(ModeloGuionado):
    """Como `ModeloGuionado`, pero entrega el texto en pedazos si se lo piden."""

    def __init__(self, turnos):
        super().__init__(turnos)
        self.al_texto_recibido = []

    def enviar(self, entrada, al_texto=None):
        self.al_texto_recibido.append(al_texto)
        turno = super().enviar(entrada)
        if al_texto and turno.texto:
            for trozo in (turno.texto[:4], turno.texto[4:]):
                al_texto(trozo)
        return turno


def _correr_con_eventos(agente, skill, modelo, herramientas):
    eventos = []
    texto = asyncio.run(
        runner.ejecutar(agente, skill, "Verificá", modelo, herramientas, lambda _l: None, eventos.append)
    )
    return texto, eventos


def test_con_eventos_emite_la_herramienta_y_el_texto_transmitido(agente, skill):
    # Arrange
    pide = Turno(llamadas=(LlamadaHerramienta("consultar_cuit", {"cuit": "30000000066"}),))
    modelo = ModeloConStreaming([pide, Turno(texto="Informe listo")])
    # Act
    texto, eventos = _correr_con_eventos(agente, skill, modelo, HerramientasFalsas())
    # Assert
    assert texto == "Informe listo"
    tipos = [e["tipo"] for e in eventos]
    assert tipos == ["herramienta", "herramienta_fin", "texto", "texto"]
    assert eventos[0] == {
        "tipo": "herramienta", "id": 1, "nombre": "consultar_cuit",
        "argumentos": {"cuit": "30000000066"},
    }
    assert eventos[1]["id"] == 1 and eventos[1]["ok"] is True and eventos[1]["error"] is None
    assert eventos[1]["ms"] >= 0
    assert "".join(e["delta"] for e in eventos if e["tipo"] == "texto") == "Informe listo"


def test_los_ids_de_herramientas_siguen_entre_turnos(agente, skill):
    # Arrange
    dos = Turno(llamadas=(
        LlamadaHerramienta("consultar_cuit", {"cuit": "A"}),
        LlamadaHerramienta("consultar_cuit", {"cuit": "B"}),
    ))
    una = Turno(llamadas=(LlamadaHerramienta("consultar_cuit", {"cuit": "C"}),))
    modelo = ModeloConStreaming([dos, una, Turno(texto="fin")])
    # Act
    _, eventos = _correr_con_eventos(agente, skill, modelo, HerramientasFalsas())
    # Assert
    ids = [e["id"] for e in eventos if e["tipo"] == "herramienta"]
    assert ids == [1, 2, 3]


def test_una_herramienta_fuera_de_la_skill_se_informa_como_fallida(agente, skill):
    # Arrange
    turno = Turno(llamadas=(LlamadaHerramienta("historial_consultas", {}),))
    modelo = ModeloConStreaming([turno, Turno(texto="fin")])
    herramientas = HerramientasFalsas()
    # Act
    _, eventos = _correr_con_eventos(agente, skill, modelo, herramientas)
    # Assert
    fin = next(e for e in eventos if e["tipo"] == "herramienta_fin")
    assert fin["ok"] is False
    assert "no está habilitada" in fin["error"]
    assert herramientas.llamadas == []


def test_una_excepcion_de_la_herramienta_se_informa_como_fallida(agente, skill):
    # Arrange
    turno = Turno(llamadas=(LlamadaHerramienta("consultar_cuit", {"cuit": "X"}),))
    modelo = ModeloConStreaming([turno, Turno(texto="fin")])
    herramientas = HerramientasFalsas({"consultar_cuit": ConnectionError("sin red")})
    # Act
    _, eventos = _correr_con_eventos(agente, skill, modelo, herramientas)
    # Assert
    fin = next(e for e in eventos if e["tipo"] == "herramienta_fin")
    assert fin["ok"] is False
    assert "sin red" in fin["error"]


def test_un_resultado_con_error_cuenta_como_fallido_aunque_no_lance(agente, skill):
    # Arrange
    turno = Turno(llamadas=(LlamadaHerramienta("consultar_cuit", {"cuit": "X"}),))
    modelo = ModeloConStreaming([turno, Turno(texto="fin")])
    herramientas = HerramientasFalsas({"consultar_cuit": {"error": "CUIT inválido"}})
    # Act
    _, eventos = _correr_con_eventos(agente, skill, modelo, herramientas)
    # Assert
    fin = next(e for e in eventos if e["tipo"] == "herramienta_fin")
    assert (fin["ok"], fin["error"]) == (False, "CUIT inválido")


def test_sin_eventos_no_se_pide_streaming_al_modelo(agente, skill):
    # Arrange
    modelo = ModeloConStreaming([Turno(texto="Listo")])
    # Act
    _correr(agente, skill, modelo, HerramientasFalsas())
    # Assert: el modelo no recibió ningún callback de texto.
    assert modelo.al_texto_recibido == [None]


def test_con_eventos_el_modelo_recibe_un_callback_de_texto(agente, skill):
    # Arrange
    modelo = ModeloConStreaming([Turno(texto="Listo")])
    # Act
    _correr_con_eventos(agente, skill, modelo, HerramientasFalsas())
    # Assert
    assert callable(modelo.al_texto_recibido[0])
