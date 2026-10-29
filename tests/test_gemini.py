"""Tests unitarios de `agente.gemini.ModeloGemini` con un cliente de Gemini
falso: se verifica la configuración que se envía y la traducción de respuestas.
Patrón AAA."""

from types import SimpleNamespace

import pytest
from google.genai import types

from agente import gemini
from agente.gemini import ModeloGemini
from agente.mcp_cliente import HerramientaMCP
from agente.modelo import LlamadaHerramienta, ResultadoHerramienta

HERRAMIENTA = HerramientaMCP(
    "consultar_cuit",
    "Consulta un CUIT",
    {"type": "object", "properties": {"cuit": {"type": "string"}}, "required": ["cuit"]},
)


class ClienteFalso:
    """Imita `genai.Client`: devuelve respuestas guionadas y guarda las llamadas."""

    def __init__(self, partes_por_respuesta):
        self._respuestas = list(partes_por_respuesta)
        self.llamadas = []
        self.models = SimpleNamespace(generate_content=self._generar)

    def _generar(self, *, model, contents, config):
        # Copia: el modelo sigue agregando al mismo historial después de la llamada.
        self.llamadas.append({"model": model, "contents": list(contents), "config": config})
        partes = self._respuestas.pop(0)
        if partes is None:
            return SimpleNamespace(candidates=[])
        contenido = types.Content(role="model", parts=partes)
        candidato = SimpleNamespace(content=contenido, finish_reason=None)
        return SimpleNamespace(candidates=[candidato])


def _modelo(cliente, **kwargs):
    return ModeloGemini(
        modelo="gemini-test",
        system_prompt="Sistema",
        herramientas=[HERRAMIENTA],
        temperature=kwargs.get("temperature", 0.0),
        max_output_tokens=kwargs.get("max_output_tokens", 256),
        cliente=cliente,
    )


def test_envia_temperatura_y_tope_de_tokens_del_agente():
    # Arrange
    cliente = ClienteFalso([[types.Part.from_text(text="hola")]])
    modelo = _modelo(cliente, temperature=0.3, max_output_tokens=321)
    # Act
    modelo.enviar("Verificá")
    # Assert
    config = cliente.llamadas[0]["config"]
    assert cliente.llamadas[0]["model"] == "gemini-test"
    assert config.temperature == pytest.approx(0.3)
    assert config.max_output_tokens == 321
    assert config.system_instruction == "Sistema"
    assert config.automatic_function_calling.disable is True


def test_declara_las_herramientas_mcp_como_funciones():
    # Arrange
    cliente = ClienteFalso([[types.Part.from_text(text="ok")]])
    modelo = _modelo(cliente)
    # Act
    modelo.enviar("x")
    # Assert
    (declaracion,) = cliente.llamadas[0]["config"].tools[0].function_declarations
    assert declaracion.name == "consultar_cuit"
    assert declaracion.parameters_json_schema["required"] == ["cuit"]


def test_respuesta_de_texto_no_trae_llamadas():
    # Arrange
    cliente = ClienteFalso([[types.Part.from_text(text="Informe listo")]])
    # Act
    turno = _modelo(cliente).enviar("Verificá")
    # Assert
    assert turno.texto == "Informe listo"
    assert turno.llamadas == ()


def test_function_call_se_traduce_a_llamada_neutral():
    # Arrange
    parte = types.Part.from_function_call(name="consultar_cuit", args={"cuit": "30000000066"})
    cliente = ClienteFalso([[parte]])
    # Act
    turno = _modelo(cliente).enviar("Verificá")
    # Assert
    assert turno.llamadas == (LlamadaHerramienta("consultar_cuit", {"cuit": "30000000066"}),)


def test_los_resultados_de_herramientas_vuelven_como_function_response():
    # Arrange
    llamada = types.Part.from_function_call(name="consultar_cuit", args={"cuit": "1"})
    cliente = ClienteFalso([[llamada], [types.Part.from_text(text="fin")]])
    modelo = _modelo(cliente)
    modelo.enviar("Verificá")
    # Act
    turno = modelo.enviar([ResultadoHerramienta("consultar_cuit", {"persona": {}})])
    # Assert
    historial = cliente.llamadas[1]["contents"]
    assert [c.role for c in historial] == ["user", "model", "user"]
    respuesta = historial[2].parts[0].function_response
    assert respuesta.name == "consultar_cuit"
    assert respuesta.response == {"persona": {}}
    assert turno.texto == "fin"


def test_respuesta_sin_candidatos_devuelve_turno_vacio_y_no_ensucia_el_historial():
    # Arrange
    cliente = ClienteFalso([None, [types.Part.from_text(text="ok")]])
    modelo = _modelo(cliente)
    # Act
    vacio = modelo.enviar("Verificá")
    modelo.enviar("Reintento")
    # Assert
    assert vacio.texto == ""
    assert vacio.llamadas == ()
    # El segundo envío no arrastra el mensaje que no obtuvo respuesta.
    assert [c.role for c in cliente.llamadas[1]["contents"]] == ["user"]


@pytest.mark.parametrize(
    "motivo, esperado",
    [
        (types.FinishReason.MAX_TOKENS, True),
        (types.FinishReason.STOP, False),
        (None, False),
    ],
)
def test_marca_la_respuesta_como_truncada_solo_si_corto_por_tokens(motivo, esperado):
    # Arrange
    contenido = types.Content(role="model", parts=[types.Part.from_text(text="respuesta cortada")])
    candidato = SimpleNamespace(content=contenido, finish_reason=motivo)
    cliente = ClienteFalso([])
    cliente.models = SimpleNamespace(
        generate_content=lambda **_: SimpleNamespace(candidates=[candidato])
    )
    # Act
    turno = _modelo(cliente).enviar("Verificá")
    # Assert
    assert turno.truncado is esperado


def test_el_cliente_reintenta_ante_picos_de_demanda_y_cuota():
    # Arrange / Act
    reintentos = gemini._opciones_http().retry_options
    # Assert
    assert reintentos.attempts > 1
    assert {429, 503} <= set(reintentos.http_status_codes)
    assert reintentos.max_delay >= reintentos.initial_delay


def test_sin_api_key_ni_cliente_falla_con_mensaje_claro(monkeypatch):
    # Arrange
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # Act / Assert
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        ModeloGemini("m", "s", [HERRAMIENTA], 0.0, 10)
