"""Cliente MCP por stdio que habla con `server.py`."""

import json
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Self

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@dataclass(frozen=True)
class HerramientaMCP:
    """Descripción de una herramienta expuesta por el servidor."""

    nombre: str
    descripcion: str
    esquema: dict


def _resolver_comando(comando: str, base: str) -> str:
    # Un comando relativo con separador ("venv/bin/python3") se interpreta
    # respecto del proyecto, no del directorio desde el que se lance el CLI.
    if os.sep in comando and not os.path.isabs(comando):
        return os.path.join(base, comando)
    return comando


def _extraer_resultado(respuesta) -> dict:
    """Convierte un CallToolResult en un dict, tolerando salidas de solo texto."""
    estructurado = getattr(respuesta, "structured_content", None)
    if isinstance(estructurado, dict):
        return estructurado

    texto = "".join(
        bloque.text for bloque in respuesta.content if getattr(bloque, "text", None)
    )
    try:
        valor = json.loads(texto)
    except json.JSONDecodeError:
        return {"error" if respuesta.is_error else "texto": texto}
    return valor if isinstance(valor, dict) else {"resultado": valor}


class ClienteMCP:
    """Context manager asíncrono: levanta `server.py` y expone sus herramientas."""

    def __init__(
        self,
        comando: str,
        args: tuple[str, ...],
        directorio: str,
        env: dict[str, str] | None = None,
    ):
        self._parametros = StdioServerParameters(
            command=_resolver_comando(comando, directorio),
            args=list(args),
            cwd=directorio,
            env=env,
        )
        self._pila = AsyncExitStack()
        self._sesion: ClientSession | None = None

    async def __aenter__(self) -> Self:
        # `async with` no llama a __aexit__ si __aenter__ falla: sin este
        # cierre, el subproceso de server.py quedaría huérfano.
        try:
            lectura, escritura = await self._pila.enter_async_context(
                stdio_client(self._parametros)
            )
            self._sesion = await self._pila.enter_async_context(
                ClientSession(lectura, escritura)
            )
            await self._sesion.initialize()
        except BaseException:
            await self._pila.aclose()
            raise
        return self

    async def __aexit__(self, *excepcion) -> None:
        await self._pila.aclose()

    async def listar_herramientas(self) -> list[HerramientaMCP]:
        """Devuelve las herramientas que publica el servidor."""
        respuesta = await self._sesion.list_tools()
        return [
            HerramientaMCP(t.name, t.description or "", t.input_schema)
            for t in respuesta.tools
        ]

    async def llamar(self, nombre: str, argumentos: dict) -> dict:
        """Ejecuta una herramienta y devuelve su resultado como dict."""
        respuesta = await self._sesion.call_tool(nombre, argumentos)
        return _extraer_resultado(respuesta)
