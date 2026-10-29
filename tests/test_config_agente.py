"""Tests unitarios de `agente.config`: carga declarativa del `.agent.md` y las
skills. Cada test arma sus archivos en `tmp_path`. Patrón AAA."""

import textwrap

import pytest

from agente.config import ConfigError, cargar_agente, cargar_skill, separar_frontmatter

AGENTE_VALIDO = """\
---
name: analista
description: Agente de prueba
provider: gemini
model: gemini-2.5-flash
temperature: 0
max_output_tokens: 512
max_tool_iterations: 3
skills:
  - verificar
mcp_server:
  command: python3
  args: [server.py]
---
Sos un analista.
"""

SKILL_VALIDA = """\
---
name: verificar
description: Verifica CUITs
tools:
  - consultar_cuit
---
Llamá a consultar_cuit por cada CUIT.
"""


@pytest.fixture
def proyecto(tmp_path):
    """Directorio con un agente válido y la skill `verificar`."""
    skill_dir = tmp_path / "skills" / "verificar"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(SKILL_VALIDA, encoding="utf-8")
    agente = tmp_path / "analista.agent.md"
    agente.write_text(AGENTE_VALIDO, encoding="utf-8")
    return tmp_path


def _reescribir(proyecto, viejo, nuevo):
    ruta = proyecto / "analista.agent.md"
    ruta.write_text(AGENTE_VALIDO.replace(viejo, nuevo), encoding="utf-8")
    return str(ruta)


def test_cargar_agente_valido_expone_parametros_del_modelo(proyecto):
    # Arrange
    ruta = str(proyecto / "analista.agent.md")
    # Act
    agente = cargar_agente(ruta, str(proyecto / "skills"))
    # Assert
    assert agente.modelo == "gemini-2.5-flash"
    assert agente.temperature == 0.0
    assert agente.max_output_tokens == 512
    assert agente.max_tool_iterations == 3
    assert agente.mcp_args == ("server.py",)
    assert agente.system_prompt == "Sos un analista."


def test_cargar_agente_carga_las_skills_referenciadas(proyecto):
    # Arrange
    ruta = str(proyecto / "analista.agent.md")
    # Act
    agente = cargar_agente(ruta, str(proyecto / "skills"))
    # Assert
    skill = agente.skills["verificar"]
    assert skill.herramientas == ("consultar_cuit",)
    assert "consultar_cuit" in skill.instrucciones


@pytest.mark.parametrize(
    "viejo, nuevo, fragmento",
    [
        ("temperature: 0\n", "temperature: 5\n", "temperature"),
        ("temperature: 0\n", "temperature: -1\n", "temperature"),
        ("temperature: 0\n", "temperature: true\n", "tipo inválido"),
        ("temperature: 0\n", "", "falta el campo obligatorio 'temperature'"),
        ("max_tool_iterations: 3", "max_tool_iterations: 0", "max_tool_iterations"),
        ("max_output_tokens: 512", "max_output_tokens: 0", "max_output_tokens"),
        ("provider: gemini", "provider: skynet", "no soportado"),
        ("skills:\n  - verificar", "skills: []", "skills"),
        ("name: analista", "name: Analista Raro", "inválido"),
    ],
)
def test_cargar_agente_rechaza_configuracion_invalida(
    proyecto, viejo, nuevo, fragmento
):
    # Arrange
    ruta = _reescribir(proyecto, viejo, nuevo)
    # Act / Assert
    with pytest.raises(ConfigError, match=fragmento):
        cargar_agente(ruta, str(proyecto / "skills"))


def test_cargar_agente_con_skill_inexistente_falla(proyecto):
    # Arrange
    ruta = _reescribir(proyecto, "- verificar", "- fantasma")
    # Act / Assert
    with pytest.raises(ConfigError, match="no se pudo leer"):
        cargar_agente(ruta, str(proyecto / "skills"))


@pytest.mark.parametrize("nombre", ["../etc", "..", "a/b", "/abs", "Mayus", ""])
def test_cargar_skill_rechaza_nombres_que_escapan_del_directorio(proyecto, nombre):
    # Arrange: nombres con path traversal o fuera del patrón permitido.
    directorio = str(proyecto / "skills")
    # Act / Assert
    with pytest.raises(ConfigError, match="inválido"):
        cargar_skill(nombre, directorio)


def test_cargar_skill_con_name_distinto_al_directorio_falla(proyecto):
    # Arrange
    ruta = proyecto / "skills" / "verificar" / "SKILL.md"
    ruta.write_text(SKILL_VALIDA.replace("name: verificar", "name: otra"), encoding="utf-8")
    # Act / Assert
    with pytest.raises(ConfigError, match="no coincide"):
        cargar_skill("verificar", str(proyecto / "skills"))


def test_cargar_skill_sin_herramientas_falla(proyecto):
    # Arrange
    ruta = proyecto / "skills" / "verificar" / "SKILL.md"
    ruta.write_text(
        SKILL_VALIDA.replace("tools:\n  - consultar_cuit", "tools: []"), encoding="utf-8"
    )
    # Act / Assert
    with pytest.raises(ConfigError, match="tools"):
        cargar_skill("verificar", str(proyecto / "skills"))


def test_separar_frontmatter_sin_bloque_falla():
    # Arrange
    texto = "# Solo markdown, sin frontmatter"
    # Act / Assert
    with pytest.raises(ConfigError, match="frontmatter"):
        separar_frontmatter(texto)


def test_separar_frontmatter_con_yaml_roto_falla():
    # Arrange
    texto = textwrap.dedent("---\nclave: [sin cerrar\n---\ncuerpo\n")
    # Act / Assert
    with pytest.raises(ConfigError, match="YAML"):
        separar_frontmatter(texto)


def test_separar_frontmatter_no_ejecuta_etiquetas_yaml_peligrosas():
    # Arrange: yaml.safe_load debe rechazar tags que instancian objetos Python.
    texto = "---\nclave: !!python/object/apply:os.system ['echo hola']\n---\ncuerpo\n"
    # Act / Assert
    with pytest.raises(ConfigError):
        separar_frontmatter(texto)
