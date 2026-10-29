"""Tests de `server.consultar_cuit`, sin llamar nunca a ARCA:

- `wsaa.login` y `padron.consultar_persona` se mockean.
- `historia.DB_PATH` apunta a un archivo en `tmp_path` (ver `server_module`
  en conftest.py), así los tests no tocan `historial.db` real.
"""

import padron
import wsaa


def test_consultar_cuit_invalido_no_llama_a_arca(server_module, monkeypatch):
    login_mock_llamado = []
    consultar_mock_llamado = []
    monkeypatch.setattr(wsaa, "login", lambda *a, **k: login_mock_llamado.append(1))
    monkeypatch.setattr(
        padron, "consultar_persona", lambda *a, **k: consultar_mock_llamado.append(1)
    )

    resultado = server_module.consultar_cuit("123")

    assert "error" in resultado
    assert login_mock_llamado == []
    assert consultar_mock_llamado == []


def test_consultar_cuit_valido_consulta_arca_y_guarda_en_historial(
    server_module, monkeypatch
):
    cuit = "20000000028"

    def fake_login(servicio, cert_path, key_path):
        return {
            "token": "TOKEN123",
            "sign": "SIGN123",
            "expiracion": "2999-01-01T00:00:00-00:00",
        }

    def fake_consultar_persona(cuit_representada, cuit_consultado, token, sign):
        assert cuit_consultado == cuit
        assert token == "TOKEN123"
        assert sign == "SIGN123"
        return {
            "persona": {
                "razonSocial": "ACME SA",
                "estadoClave": "ACTIVO",
                "tipoPersona": "JURIDICA",
            }
        }

    monkeypatch.setattr(wsaa, "login", fake_login)
    monkeypatch.setattr(padron, "consultar_persona", fake_consultar_persona)

    resultado = server_module.consultar_cuit(cuit)

    assert resultado["persona"]["razonSocial"] == "ACME SA"
    assert resultado["persona"]["estadoClave"] == "ACTIVO"

    # Se guardó en el historial local.
    guardada = server_module.historia.buscar_por_cuit(cuit)
    assert guardada is not None
    assert guardada["razon_social"] == "ACME SA"


def test_consultar_cuit_usa_historial_y_no_llama_a_arca_de_nuevo(
    server_module, monkeypatch
):
    cuit = "27000000030"

    login_llamado = []
    consultar_llamado = []

    def fake_login(*args, **kwargs):
        login_llamado.append(1)
        return {"token": "T", "sign": "S", "expiracion": "2999-01-01T00:00:00-00:00"}

    def fake_consultar_persona(*args, **kwargs):
        consultar_llamado.append(1)
        return {"persona": {"razonSocial": "Primera Consulta", "estadoClave": "ACTIVO"}}

    monkeypatch.setattr(wsaa, "login", fake_login)
    monkeypatch.setattr(padron, "consultar_persona", fake_consultar_persona)

    primer_resultado = server_module.consultar_cuit(cuit)
    assert primer_resultado["persona"]["razonSocial"] == "Primera Consulta"
    assert len(login_llamado) == 1
    assert len(consultar_llamado) == 1

    segundo_resultado = server_module.consultar_cuit(cuit)

    # No se volvió a llamar a WSAA ni al Padrón: vino del historial.
    assert len(login_llamado) == 1
    assert len(consultar_llamado) == 1
    assert segundo_resultado["_origen"] == "historial"
    assert segundo_resultado["persona"]["razonSocial"] == "Primera Consulta"


def test_consultar_cuit_maneja_error_de_arca(server_module, monkeypatch):
    cuit = "30000000058"

    def fake_login(*args, **kwargs):
        raise RuntimeError("WSAA no disponible")

    monkeypatch.setattr(wsaa, "login", fake_login)

    resultado = server_module.consultar_cuit(cuit)

    assert "error" in resultado
    assert server_module.historia.buscar_por_cuit(cuit) is None
