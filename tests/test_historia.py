"""Tests de historia.py: guardar y buscar consultas en el historial local.

Usa la fixture `historia_module` (ver conftest.py), que redirige
`historia.DB_PATH` a un archivo dentro de `tmp_path`, así los tests nunca
tocan `historial.db` real.
"""


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
