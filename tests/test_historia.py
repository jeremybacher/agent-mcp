"""Tests de historia.py: guardar y buscar consultas en el historial local.

Usa la fixture `historia_module` (ver conftest.py), que redirige
`historia.DB_PATH` a un archivo dentro de `tmp_path`, así los tests nunca
tocan `historial.db` real.
"""

import pytest


def test_buscar_por_cuit_sin_datos_devuelve_none(historia_module):
    assert historia_module.buscar_por_cuit("20000000026") is None


def test_guardar_y_buscar_consulta(historia_module):
    cuit = "20000000026"
    resultado = {
        "persona": {
            "razonSocial": "ACME SA",
            "estadoClave": "ACTIVO",
        }
    }

    historia_module.guardar_consulta(cuit, resultado)
    encontrada = historia_module.buscar_por_cuit(cuit)

    assert encontrada is not None
    assert encontrada["cuit"] == cuit
    assert encontrada["razon_social"] == "ACME SA"
    assert encontrada["estado"] == "ACTIVO"
    assert encontrada["resultado"] == resultado
    assert encontrada["fecha"]  # se guardó algún timestamp


def test_guardar_consulta_con_nombre_y_apellido(historia_module):
    cuit = "27000000035"
    resultado = {
        "persona": {
            "nombre": "Juan",
            "apellido": "Perez",
            "estadoClave": "ACTIVO",
        }
    }

    historia_module.guardar_consulta(cuit, resultado)
    encontrada = historia_module.buscar_por_cuit(cuit)

    assert encontrada["razon_social"] == "Perez Juan"


def test_buscar_por_cuit_devuelve_la_consulta_mas_reciente(historia_module):
    cuit = "20000000026"
    resultado_viejo = {"persona": {"razonSocial": "Vieja SA", "estadoClave": "ACTIVO"}}
    resultado_nuevo = {"persona": {"razonSocial": "Nueva SA", "estadoClave": "ACTIVO"}}

    historia_module.guardar_consulta(cuit, resultado_viejo)
    historia_module.guardar_consulta(cuit, resultado_nuevo)

    encontrada = historia_module.buscar_por_cuit(cuit)
    assert encontrada["razon_social"] == "Nueva SA"


def test_listar_ultimas(historia_module):
    historia_module.guardar_consulta(
        "20000000026", {"persona": {"razonSocial": "A", "estadoClave": "ACTIVO"}}
    )
    historia_module.guardar_consulta(
        "27000000035", {"persona": {"razonSocial": "B", "estadoClave": "ACTIVO"}}
    )

    consultas = historia_module.listar_ultimas(limite=10)

    assert len(consultas) == 2
    cuits = {c["cuit"] for c in consultas}
    assert cuits == {"20000000026", "27000000035"}


def test_buscar_por_cuit_no_mezcla_cuits_distintos(historia_module):
    historia_module.guardar_consulta(
        "20000000026", {"persona": {"razonSocial": "A", "estadoClave": "ACTIVO"}}
    )

    assert historia_module.buscar_por_cuit("27000000035") is None


# ---------- borrado ----------


def test_contar_devuelve_la_cantidad_de_consultas(historia_module):
    # Arrange
    assert historia_module.contar() == 0
    historia_module.guardar_consulta("20000000028", {"persona": {"razonSocial": "A"}})
    historia_module.guardar_consulta("30000000066", {"persona": {"razonSocial": "B"}})
    # Act
    total = historia_module.contar()
    # Assert
    assert total == 2


def test_eliminar_por_cuit_borra_solo_las_filas_de_ese_cuit(historia_module):
    # Arrange: el mismo CUIT consultado dos veces y otro distinto.
    historia_module.guardar_consulta("20000000028", {"persona": {"razonSocial": "A"}})
    historia_module.guardar_consulta("20000000028", {"persona": {"razonSocial": "A2"}})
    historia_module.guardar_consulta("30000000066", {"persona": {"razonSocial": "B"}})
    # Act
    eliminadas = historia_module.eliminar_por_cuit("20000000028")
    # Assert
    assert eliminadas == 2
    assert historia_module.buscar_por_cuit("20000000028") is None
    assert historia_module.buscar_por_cuit("30000000066") is not None


def test_eliminar_por_cuit_inexistente_no_borra_nada(historia_module):
    # Arrange
    historia_module.guardar_consulta("30000000066", {"persona": {"razonSocial": "B"}})
    # Act
    eliminadas = historia_module.eliminar_por_cuit("20000000028")
    # Assert
    assert eliminadas == 0
    assert historia_module.contar() == 1


@pytest.mark.parametrize("cuit", ["' OR '1'='1", "1; DROP TABLE consultas", "%", "*"])
def test_eliminar_por_cuit_trata_la_entrada_como_dato_no_como_sql(historia_module, cuit):
    # Arrange
    historia_module.guardar_consulta("30000000066", {"persona": {"razonSocial": "B"}})
    # Act
    eliminadas = historia_module.eliminar_por_cuit(cuit)
    # Assert: consulta parametrizada: ni borra de más ni rompe la tabla.
    assert eliminadas == 0
    assert historia_module.contar() == 1


def test_eliminar_todo_vacia_el_historial_y_devuelve_la_cantidad(historia_module):
    # Arrange
    for cuit in ("20000000028", "30000000066", "30000000012"):
        historia_module.guardar_consulta(cuit, {"persona": {"razonSocial": "X"}})
    # Act
    eliminadas = historia_module.eliminar_todo()
    # Assert
    assert eliminadas == 3
    assert historia_module.contar() == 0
    assert historia_module.listar_ultimas(10) == []


def test_eliminar_todo_con_el_historial_vacio_devuelve_cero(historia_module):
    # Arrange / Act
    eliminadas = historia_module.eliminar_todo()
    # Assert
    assert eliminadas == 0


def test_eliminar_todo_no_deja_los_datos_dentro_del_archivo(historia_module):
    # Arrange: un texto reconocible, que sin VACUUM seguiría en las páginas libres.
    marca = "MARCA_UNICA_PARA_BUSCAR_EN_EL_ARCHIVO"
    historia_module.guardar_consulta("30000000066", {"persona": {"razonSocial": marca}})
    with open(historia_module.DB_PATH, "rb") as archivo:
        assert marca.encode() in archivo.read()
    # Act
    historia_module.eliminar_todo()
    # Assert
    with open(historia_module.DB_PATH, "rb") as archivo:
        assert marca.encode() not in archivo.read()


def test_se_puede_seguir_guardando_despues_de_vaciar(historia_module):
    # Arrange
    historia_module.guardar_consulta("30000000066", {"persona": {"razonSocial": "B"}})
    historia_module.eliminar_todo()
    # Act
    historia_module.guardar_consulta("20000000028", {"persona": {"razonSocial": "A"}})
    # Assert
    assert historia_module.contar() == 1
