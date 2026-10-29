"""Bucle del agente: modelo -> herramienta MCP -> modelo, hasta tener respuesta final."""

import asyncio
import sys
from collections.abc import Callable

from agente.config import Agente, Skill
from agente.modelo import Modelo, ResultadoHerramienta


class LimiteDeIteracionesError(RuntimeError):
    """El modelo siguió pidiendo herramientas más allá de `max_tool_iterations`."""


def log(mensaje: str) -> None:
    """Escribe un mensaje de traza en stderr."""
    print(mensaje, file=sys.stderr, flush=True)


def armar_system_prompt(agente: Agente, skill: Skill) -> str:
    """Combina el prompt del agente con las instrucciones de la skill activa."""
    return (
        f"{agente.system_prompt}\n\n"
        f"# Skill activa: {skill.nombre}\n\n{skill.instrucciones}"
    )


async def ejecutar(
    agente: Agente,
    skill: Skill,
    pedido: str,
    modelo: Modelo,
    herramientas,
    registrar: Callable[[str], None] = log,
) -> str:
    """Corre el agente con una skill y devuelve el texto final del modelo.

    `herramientas` es un objeto con `llamar(nombre, argumentos) -> dict`
    (normalmente `ClienteMCP`). Solo se ejecutan las herramientas que declara
    la skill; cualquier otra se le devuelve al modelo como error.
    """
    permitidas = set(skill.herramientas)
    entrada: str | list[ResultadoHerramienta] = pedido

    for iteracion in range(1, agente.max_tool_iterations + 1):
        turno = await asyncio.to_thread(modelo.enviar, entrada)

        if not turno.llamadas:
            if not turno.texto.strip():
                raise RuntimeError("El modelo no devolvió ninguna respuesta.")
            if turno.truncado:
                registrar(
                    "ADVERTENCIA: la respuesta se cortó por 'max_output_tokens'; "
                    "el informe puede estar incompleto. Subí el valor en el .agent.md."
                )
            return turno.texto

        resultados = []
        for llamada in turno.llamadas:
            if llamada.nombre not in permitidas:
                registrar(f"[{iteracion}] herramienta no permitida: {llamada.nombre}")
                resultado = {
                    "error": f"La herramienta '{llamada.nombre}' no está habilitada para esta skill."
                }
            else:
                registrar(f"[{iteracion}] {llamada.nombre}({llamada.argumentos})")
                try:
                    resultado = await herramientas.llamar(
                        llamada.nombre, llamada.argumentos
                    )
                except Exception as exc:  # el error vuelve al modelo, no corta el bucle
                    registrar(f"[{iteracion}] fallo en {llamada.nombre}: {exc}")
                    resultado = {"error": f"Falló la herramienta: {exc}"}
            resultados.append(ResultadoHerramienta(llamada.nombre, resultado))

        entrada = resultados

    raise LimiteDeIteracionesError(
        f"El agente superó el máximo de {agente.max_tool_iterations} iteraciones de herramientas."
    )
