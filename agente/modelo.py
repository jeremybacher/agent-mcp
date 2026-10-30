"""Tipos neutrales entre el runner y el proveedor del LLM."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class LlamadaHerramienta:
    """El modelo pide ejecutar una herramienta."""

    nombre: str
    argumentos: dict


@dataclass(frozen=True)
class ResultadoHerramienta:
    """Respuesta de una herramienta, para devolvérsela al modelo."""

    nombre: str
    resultado: dict


@dataclass(frozen=True)
class Turno:
    """Lo que respondió el modelo: texto final y/o llamadas a herramientas.

    `truncado` indica que el modelo cortó por el tope de tokens de salida.
    """

    texto: str = ""
    llamadas: tuple[LlamadaHerramienta, ...] = field(default_factory=tuple)
    truncado: bool = False


class Modelo(Protocol):
    """Conversación con un LLM. Mantiene su propio historial."""

    def enviar(
        self,
        entrada: "str | list[ResultadoHerramienta]",
        al_texto: Callable[[str], None] | None = None,
    ) -> Turno:
        """Envía el pedido del usuario o los resultados de herramientas.

        Si se pasa `al_texto`, el modelo transmite la respuesta y llama a esa
        función con cada fragmento de texto a medida que llega.
        """
        ...
