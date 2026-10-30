"""El servidor MCP solo debe cargar las variables ARCA_* del .env: el mismo archivo
guarda la clave de Gemini, que el servidor no necesita. Patrón AAA."""

import os


def _env(tmp_path, contenido):
    ruta = tmp_path / ".env"
    ruta.write_text(contenido, encoding="utf-8")
    return str(ruta)


def test_carga_las_variables_arca_y_deja_afuera_las_demas(server_module, tmp_path, monkeypatch):
    # Arrange
    monkeypatch.setattr(os, "environ", {})
    ruta = _env(
        tmp_path,
        "ARCA_CUIT=20000000028\nARCA_CERT_PATH=certs/c.crt\nGEMINI_API_KEY=clave-secreta\nOTRA=x\n",
    )
    # Act
    server_module.cargar_variables_arca(ruta)
    # Assert
    assert os.environ == {"ARCA_CUIT": "20000000028", "ARCA_CERT_PATH": "certs/c.crt"}


def test_no_pisa_una_variable_que_ya_estaba_definida(server_module, tmp_path, monkeypatch):
    # Arrange
    monkeypatch.setattr(os, "environ", {"ARCA_CUIT": "del-entorno"})
    ruta = _env(tmp_path, "ARCA_CUIT=del-archivo\n")
    # Act
    server_module.cargar_variables_arca(ruta)
    # Assert
    assert os.environ["ARCA_CUIT"] == "del-entorno"


def test_un_env_inexistente_o_vacio_no_falla_ni_agrega_nada(server_module, tmp_path, monkeypatch):
    # Arrange
    monkeypatch.setattr(os, "environ", {})
    # Act
    server_module.cargar_variables_arca(str(tmp_path / "no_existe.env"))
    server_module.cargar_variables_arca(_env(tmp_path, ""))
    # Assert
    assert os.environ == {}


def test_ignora_una_variable_arca_sin_valor(server_module, tmp_path, monkeypatch):
    # Arrange: una clave sin "=" se lee como None y no debe volverse la cadena "None".
    monkeypatch.setattr(os, "environ", {})
    ruta = _env(tmp_path, "ARCA_CUIT\nARCA_KEY_PATH=k.key\n")
    # Act
    server_module.cargar_variables_arca(ruta)
    # Assert
    assert os.environ == {"ARCA_KEY_PATH": "k.key"}
