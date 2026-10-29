"""CLI del agente de proveedores.

Ejemplos:
    python agent.py --skill verificar-proveedores "Verificá 30-00000006-6"
    python agent.py --skill verificar-proveedores --csv proveedores.csv --salida hoy.md
    python agent.py --skill resumen-historial "¿Qué proveedores ya verifiqué?"
"""

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv
from google.genai import errors as genai_errors

from agente import runner
from agente.config import ConfigError, cargar_agente
from agente.entradas import (
    EntradaInvalidaError,
    armar_pedido_verificacion,
    leer_csv_cuits,
    resolver_salida,
)
from agente.gemini import ModeloGemini
from agente.mcp_cliente import ClienteMCP

DIRECTORIO = os.path.dirname(os.path.abspath(__file__))
AGENTE_POR_DEFECTO = os.path.join(DIRECTORIO, "agents", "analista-proveedores.agent.md")
DIRECTORIO_SKILLS = os.path.join(DIRECTORIO, "skills")
DIRECTORIO_INFORMES = os.path.join(DIRECTORIO, "informes")


def parsear_argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    """Define y parsea los argumentos del CLI."""
    parser = argparse.ArgumentParser(description="Agente de debida diligencia de proveedores.")
    parser.add_argument("pedido", nargs="?", help="Pedido en lenguaje natural.")
    parser.add_argument("--skill", required=True, help="Skill a activar.")
    parser.add_argument("--csv", help="CSV con una columna 'cuit'.")
    parser.add_argument("--salida", help="Nombre del .md a guardar dentro de informes/.")
    parser.add_argument("--agente", default=AGENTE_POR_DEFECTO, help="Ruta al .agent.md.")
    return parser.parse_args(argv)


async def principal(args: argparse.Namespace) -> tuple[str, str | None]:
    """Carga la configuración, conecta con el MCP y corre el agente.

    Devuelve el texto del informe y la ruta de salida ya validada (o None).
    """
    agente = cargar_agente(args.agente, DIRECTORIO_SKILLS)
    if args.skill not in agente.skills:
        raise ConfigError(
            f"la skill '{args.skill}' no está habilitada en el agente "
            f"(disponibles: {', '.join(agente.skills)})"
        )
    skill = agente.skills[args.skill]

    if args.csv:
        validos, invalidos = leer_csv_cuits(args.csv)
        if not validos and not invalidos:
            raise EntradaInvalidaError("el CSV no tiene CUITs")
        pedido = armar_pedido_verificacion(validos, invalidos)
    elif args.pedido:
        pedido = args.pedido
    else:
        raise EntradaInvalidaError("indicá un pedido o un --csv")

    destino = resolver_salida(args.salida, DIRECTORIO_INFORMES) if args.salida else None

    runner.log(
        f"Agente '{agente.nombre}' | modelo={agente.modelo} "
        f"temperature={agente.temperature} max_output_tokens={agente.max_output_tokens} "
        f"| skill={skill.nombre}"
    )

    async with ClienteMCP(agente.mcp_command, agente.mcp_args, DIRECTORIO) as mcp:
        disponibles = {h.nombre: h for h in await mcp.listar_herramientas()}
        faltantes = set(skill.herramientas) - set(disponibles)
        if faltantes:
            raise ConfigError(f"el servidor MCP no expone: {', '.join(sorted(faltantes))}")

        modelo = ModeloGemini(
            modelo=agente.modelo,
            system_prompt=runner.armar_system_prompt(agente, skill),
            herramientas=[disponibles[n] for n in skill.herramientas],
            temperature=agente.temperature,
            max_output_tokens=agente.max_output_tokens,
        )
        texto = await runner.ejecutar(agente, skill, pedido, modelo, mcp)

    return texto, destino


def guardar_informe(texto: str, destino: str) -> None:
    """Escribe el informe en `destino` (ya validado dentro de informes/)."""
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8") as archivo:
        archivo.write(texto + "\n")
    runner.log(f"Informe guardado en {destino}")


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada: devuelve el código de salida del proceso."""
    load_dotenv()
    args = parsear_argumentos(argv)
    try:
        texto, destino = asyncio.run(principal(args))
        if destino:
            guardar_informe(texto, destino)
        print(texto)
    except (ConfigError, EntradaInvalidaError, runner.LimiteDeIteracionesError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (RuntimeError, genai_errors.APIError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
