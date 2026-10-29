"""Carga y validación de la definición declarativa del agente y sus skills.

El agente vive en un `.agent.md` y cada skill en `skills/<nombre>/SKILL.md`.
Ambos son Markdown con frontmatter YAML: el frontmatter configura el modelo y
las herramientas, el cuerpo es el prompt.
"""

import os
import re
from dataclasses import dataclass, field

import yaml

PROVIDERS_SOPORTADOS = ("gemini",)
_PATRON_NOMBRE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_PATRON_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


class ConfigError(ValueError):
    """La definición del agente o de una skill es inválida."""


@dataclass(frozen=True)
class Skill:
    """Una habilidad empaquetada: prompt más las herramientas MCP que puede usar."""

    nombre: str
    descripcion: str
    herramientas: tuple[str, ...]
    instrucciones: str


@dataclass(frozen=True)
class Agente:
    """Agente completo: configuración del modelo, skills y servidor MCP."""

    nombre: str
    descripcion: str
    provider: str
    modelo: str
    temperature: float
    max_output_tokens: int
    max_tool_iterations: int
    system_prompt: str
    mcp_command: str
    mcp_args: tuple[str, ...]
    skills: dict[str, Skill] = field(default_factory=dict)


def separar_frontmatter(texto: str) -> tuple[dict, str]:
    """Separa un documento Markdown en (frontmatter YAML, cuerpo)."""
    coincidencia = _PATRON_FRONTMATTER.match(texto)
    if coincidencia is None:
        raise ConfigError("el archivo no empieza con un bloque frontmatter '---'")
    try:
        meta = yaml.safe_load(coincidencia.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"frontmatter YAML inválido: {exc}") from exc
    if not isinstance(meta, dict):
        raise ConfigError("el frontmatter debe ser un mapa clave: valor")
    return meta, coincidencia.group(2).strip()


def _requerido(meta: dict, clave: str, tipo: type | tuple, origen: str):
    if clave not in meta:
        raise ConfigError(f"{origen}: falta el campo obligatorio '{clave}'")
    valor = meta[clave]
    # bool es subclase de int: no lo aceptamos como número.
    if isinstance(valor, bool) or not isinstance(valor, tipo):
        raise ConfigError(f"{origen}: '{clave}' tiene un tipo inválido")
    return valor


def _validar_nombre(nombre: str, origen: str) -> str:
    if not _PATRON_NOMBRE.match(nombre):
        raise ConfigError(
            f"{origen}: nombre '{nombre}' inválido (solo minúsculas, números y guiones)"
        )
    return nombre


def _leer(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as archivo:
            return archivo.read()
    except OSError as exc:
        raise ConfigError(f"no se pudo leer '{path}': {exc.strerror}") from exc


def cargar_skill(nombre: str, directorio_skills: str) -> Skill:
    """Carga `skills/<nombre>/SKILL.md`."""
    _validar_nombre(nombre, "skill")
    path = os.path.join(directorio_skills, nombre, "SKILL.md")
    meta, cuerpo = separar_frontmatter(_leer(path))
    origen = f"skill '{nombre}'"

    if _requerido(meta, "name", str, origen) != nombre:
        raise ConfigError(f"{origen}: 'name' no coincide con el nombre del directorio")
    herramientas = _requerido(meta, "tools", list, origen)
    if not herramientas or not all(isinstance(h, str) for h in herramientas):
        raise ConfigError(f"{origen}: 'tools' debe ser una lista de nombres no vacía")

    return Skill(
        nombre=nombre,
        descripcion=_requerido(meta, "description", str, origen),
        herramientas=tuple(herramientas),
        instrucciones=cuerpo,
    )


def cargar_agente(path: str, directorio_skills: str) -> Agente:
    """Carga un `.agent.md` y todas las skills que referencia."""
    meta, cuerpo = separar_frontmatter(_leer(path))
    origen = f"agente '{os.path.basename(path)}'"

    provider = _requerido(meta, "provider", str, origen)
    if provider not in PROVIDERS_SOPORTADOS:
        raise ConfigError(
            f"{origen}: provider '{provider}' no soportado ({', '.join(PROVIDERS_SOPORTADOS)})"
        )

    temperature = _requerido(meta, "temperature", (int, float), origen)
    if not 0 <= temperature <= 2:
        raise ConfigError(f"{origen}: 'temperature' debe estar entre 0 y 2")

    max_tokens = _requerido(meta, "max_output_tokens", int, origen)
    if max_tokens < 1:
        raise ConfigError(f"{origen}: 'max_output_tokens' debe ser >= 1")

    iteraciones = _requerido(meta, "max_tool_iterations", int, origen)
    if iteraciones < 1:
        raise ConfigError(f"{origen}: 'max_tool_iterations' debe ser >= 1")

    nombres_skills = _requerido(meta, "skills", list, origen)
    if not nombres_skills or not all(isinstance(s, str) for s in nombres_skills):
        raise ConfigError(f"{origen}: 'skills' debe ser una lista de nombres no vacía")

    servidor = _requerido(meta, "mcp_server", dict, origen)
    args = servidor.get("args", [])
    if not isinstance(servidor.get("command"), str) or not isinstance(args, list):
        raise ConfigError(f"{origen}: 'mcp_server' necesita 'command' y 'args'")

    return Agente(
        nombre=_validar_nombre(_requerido(meta, "name", str, origen), origen),
        descripcion=_requerido(meta, "description", str, origen),
        provider=provider,
        modelo=_requerido(meta, "model", str, origen),
        temperature=float(temperature),
        max_output_tokens=max_tokens,
        max_tool_iterations=iteraciones,
        system_prompt=cuerpo,
        mcp_command=servidor["command"],
        mcp_args=tuple(str(a) for a in args),
        skills={n: cargar_skill(n, directorio_skills) for n in nombres_skills},
    )
