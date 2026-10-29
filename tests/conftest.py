"""Fixtures compartidas para los tests.

Estas fixtures se aseguran de que ningún test toque la base de datos real
(`historial.db`) ni el servicio de ARCA: `historia.DB_PATH` se redirige a un
archivo temporal (vía `tmp_path`) antes de importar `server`, y `server` se
reimporta en cada test para garantizar aislamiento total entre pruebas.
"""

import sys

import pytest


@pytest.fixture
def historia_module(tmp_path, monkeypatch):
    """Módulo `historia` apuntando a una base de datos SQLite temporal."""
    import historia

    monkeypatch.setattr(historia, "DB_PATH", str(tmp_path / "historial_test.db"))
    historia.inicializar_db()
    return historia


@pytest.fixture
def server_module(tmp_path, monkeypatch):
    """Módulo `server` recién importado, con `historia.DB_PATH` apuntando a
    un archivo temporal para no tocar `historial.db` real."""
    import historia

    monkeypatch.setattr(historia, "DB_PATH", str(tmp_path / "historial_test.db"))

    sys.modules.pop("server", None)
    import server

    yield server

    sys.modules.pop("server", None)
