"""Adaptador de Gemini (google-genai) con function calling manual."""

import os
from collections.abc import Callable

from google import genai
from google.genai import types

from agente.mcp_cliente import HerramientaMCP
from agente.modelo import LlamadaHerramienta, ResultadoHerramienta, Turno


def _opciones_http() -> types.HttpOptions:
    """Reintenta con espera exponencial ante picos de demanda y límites de cuota."""
    return types.HttpOptions(
        retry_options=types.HttpRetryOptions(
            attempts=4,
            initial_delay=2.0,
            max_delay=20.0,
            http_status_codes=[429, 500, 503, 504],
        )
    )


def _a_declaracion(herramienta: HerramientaMCP) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=herramienta.nombre,
        description=herramienta.descripcion,
        parameters_json_schema=herramienta.esquema,
    )


class ModeloGemini:
    """Conversación con Gemini. La temperatura y el tope de tokens vienen del `.agent.md`."""

    def __init__(
        self,
        modelo: str,
        system_prompt: str,
        herramientas: list[HerramientaMCP],
        temperature: float,
        max_output_tokens: int,
        cliente: genai.Client | None = None,
    ):
        clave = os.environ.get("GEMINI_API_KEY")
        if cliente is None and not clave:
            raise RuntimeError("Falta GEMINI_API_KEY en el entorno o en .env")

        self._cliente = cliente or genai.Client(
            api_key=clave, http_options=_opciones_http()
        )
        self._modelo = modelo
        self._contenidos: list[types.Content] = []
        self._config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            tools=[
                types.Tool(function_declarations=[_a_declaracion(h) for h in herramientas])
            ],
            # El runner ejecuta las herramientas: así cada llamada queda registrada.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def enviar(
        self,
        entrada: str | list[ResultadoHerramienta],
        al_texto: Callable[[str], None] | None = None,
    ) -> Turno:
        """Agrega el mensaje al historial y devuelve la respuesta del modelo.

        Con `al_texto` la respuesta se transmite: cada fragmento de texto se
        entrega apenas llega, sin esperar a que termine.
        """
        if isinstance(entrada, str):
            partes = [types.Part.from_text(text=entrada)]
        else:
            partes = [
                types.Part.from_function_response(name=r.nombre, response=r.resultado)
                for r in entrada
            ]
        self._contenidos.append(types.Content(role="user", parts=partes))

        if al_texto is None:
            partes_modelo, motivo = self._generar()
        else:
            partes_modelo, motivo = self._transmitir(al_texto)

        if partes_modelo is None:
            # Sin respuesta: se saca el mensaje enviado para no dejar dos
            # turnos "user" seguidos en el historial.
            self._contenidos.pop()
            return Turno(texto="")

        # Se guardan las partes tal como las devolvió el modelo (incluidas las
        # firmas de razonamiento): hay modelos que las exigen en el function calling.
        self._contenidos.append(types.Content(role="model", parts=partes_modelo))

        llamadas = tuple(
            LlamadaHerramienta(p.function_call.name, dict(p.function_call.args or {}))
            for p in partes_modelo
            if p.function_call
        )
        texto = "".join(p.text for p in partes_modelo if p.text and not p.thought)
        truncado = motivo == types.FinishReason.MAX_TOKENS
        return Turno(texto=texto, llamadas=llamadas, truncado=truncado)

    def _generar(self):
        """Respuesta completa de una vez: (partes, motivo de fin), o (None, None) si no hubo."""
        respuesta = self._cliente.models.generate_content(
            model=self._modelo, contents=self._contenidos, config=self._config
        )
        if not respuesta.candidates or respuesta.candidates[0].content is None:
            return None, None
        candidato = respuesta.candidates[0]
        return list(candidato.content.parts or []), candidato.finish_reason

    def _transmitir(self, al_texto: Callable[[str], None]):
        """Respuesta en streaming: entrega cada fragmento de texto a `al_texto`."""
        partes: list[types.Part] = []
        motivo = None
        hubo_contenido = False
        for fragmento in self._cliente.models.generate_content_stream(
            model=self._modelo, contents=self._contenidos, config=self._config
        ):
            if not fragmento.candidates:
                continue
            candidato = fragmento.candidates[0]
            if candidato.finish_reason:
                motivo = candidato.finish_reason
            if candidato.content is None:
                continue
            hubo_contenido = True
            for parte in candidato.content.parts or []:
                partes.append(parte)
                if parte.text and not parte.thought:
                    al_texto(parte.text)
        return (partes if hubo_contenido else None), motivo
