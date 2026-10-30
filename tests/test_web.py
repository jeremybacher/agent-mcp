"""Tests de la UI web (`web.py`) con el cliente de pruebas de Flask. El agente
se reemplaza por un doble: no hay Gemini, ARCA ni subprocesos. Patrón AAA."""

import json
import threading
import time
from pathlib import Path

import pytest

import historia
import web
from agente import entradas
from agente.config import ConfigError

VALIDO = "20000000028"
INVALIDO = "20000000029"
DIRECTORIO_WEB = Path(web.DIRECTORIO_WEB)


@pytest.fixture
def cliente(monkeypatch, tmp_path):
    """Cliente Flask con estado limpio y una base de historial temporal."""
    monkeypatch.setattr(web, "_trabajos", web.OrderedDict())
    monkeypatch.setattr(web, "_en_curso", None)
    monkeypatch.setattr(historia, "DB_PATH", str(tmp_path / "historial.db"))
    historia.inicializar_db()
    return web.app.test_client()


class Llamadas(list):
    """Lista de (skill, pedido) con las temperaturas recibidas aparte."""

    def __init__(self):
        super().__init__()
        self.temperaturas = []


@pytest.fixture
def agente_falso(monkeypatch):
    """Reemplaza `ejecutar_agente` y registra con qué se lo llamó."""
    llamadas = Llamadas()

    def falso(skill, pedido, registrar, eventos=None, temperature=None):
        llamadas.append((skill, pedido))
        llamadas.temperaturas.append(temperature)
        registrar("[1] consultar_cuit({'cuit': 'x'})")
        return "# Informe\n\nOK"

    monkeypatch.setattr(web, "ejecutar_agente", falso)
    return llamadas


def _esperar(cliente, id_trabajo, plazo=3.0):
    limite = time.monotonic() + plazo
    while time.monotonic() < limite:
        trabajo = cliente.get(f"/api/trabajos/{id_trabajo}").get_json()
        if trabajo["estado"] != "en_curso":
            return trabajo
        time.sleep(0.01)
    pytest.fail("el trabajo no terminó a tiempo")


def _crear(cliente, texto=VALIDO, skill="verificar-proveedores"):
    return cliente.post("/api/trabajos", json={"skill": skill, "texto": texto})


# ---------- seguridad ----------


def test_la_pagina_y_la_api_llevan_cabeceras_de_seguridad(cliente):
    # Arrange / Act
    respuestas = [cliente.get("/"), cliente.get("/api/config")]
    # Assert
    for respuesta in respuestas:
        csp = respuesta.headers["Content-Security-Policy"]
        assert "script-src 'self'" in csp
        assert "unsafe-inline" not in csp
        assert "frame-ancestors 'none'" in csp
        assert respuesta.headers["X-Content-Type-Options"] == "nosniff"
        assert respuesta.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("host", ["evil.example", "localhost.evil.example", "10.0.0.5:5051"])
def test_un_host_no_local_se_rechaza_contra_dns_rebinding(cliente, host):
    # Arrange / Act
    respuesta = cliente.get("/api/config", headers={"Host": host})
    # Assert
    assert respuesta.status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.1:5051", "localhost:5051", "localhost"])
def test_los_hosts_locales_se_aceptan(cliente, host):
    # Arrange / Act
    respuesta = cliente.get("/api/config", headers={"Host": host})
    # Assert
    assert respuesta.status_code == 200


def test_un_post_desde_otro_origen_se_rechaza_contra_csrf(cliente, agente_falso):
    # Arrange
    cabeceras = {"Origin": "http://evil.example"}
    # Act
    respuesta = cliente.post(
        "/api/trabajos", json={"skill": "verificar-proveedores", "texto": VALIDO},
        headers=cabeceras,
    )
    # Assert
    assert respuesta.status_code == 403
    assert agente_falso == []


def test_un_post_del_mismo_origen_se_acepta(cliente, agente_falso):
    # Arrange
    cabeceras = {"Origin": "http://localhost"}  # el cliente de pruebas usa Host: localhost
    # Act
    respuesta = cliente.post(
        "/api/trabajos", json={"skill": "verificar-proveedores", "texto": VALIDO},
        headers=cabeceras,
    )
    # Assert
    assert respuesta.status_code == 202


def test_un_post_que_no_es_json_se_rechaza(cliente, agente_falso):
    # Arrange: un formulario HTML cruzado enviaría text/plain o urlencoded.
    # Act
    respuesta = cliente.post(
        "/api/trabajos", data="skill=verificar-proveedores&texto=x",
        content_type="application/x-www-form-urlencoded",
    )
    # Assert
    assert respuesta.status_code == 415
    assert agente_falso == []


def test_el_html_no_tiene_scripts_estilos_ni_handlers_inline():
    # Arrange
    html = (DIRECTORIO_WEB / "index.html").read_text(encoding="utf-8")
    # Act / Assert: lo exige la CSP; si alguien lo agrega, la página se rompe.
    assert 'src="/static/app.js"' in html
    assert "<script>" not in html
    assert " style=" not in html
    assert "<style" not in html
    assert " onclick=" not in html


@pytest.mark.parametrize("peligroso", ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("])
def test_el_js_nunca_inserta_html_ni_evalua_texto(peligroso):
    # Arrange: lo que devuelve el padrón o el modelo se muestra solo como texto.
    codigo = (DIRECTORIO_WEB / "app.js").read_text(encoding="utf-8")
    # Act / Assert
    assert peligroso not in codigo


def test_el_dashboard_del_servidor_mcp_no_usa_innerhtml_con_datos_del_padron():
    # Arrange
    html = (Path(web.DIRECTORIO) / "index.html").read_text(encoding="utf-8")
    # Act / Assert
    assert "innerHTML" not in html


# ---------- validación de pedidos ----------


@pytest.mark.parametrize(
    "cuerpo, fragmento",
    [
        ([1, 2], "Cuerpo inválido"),
        ({"skill": 5, "texto": "x"}, "Cuerpo inválido"),
        ({"skill": "verificar-proveedores", "texto": 7}, "Cuerpo inválido"),
        ({"skill": "no-existe", "texto": VALIDO}, "no disponible"),
        ({"skill": "verificar-proveedores", "texto": "sin numeros aca"}, "ningún CUIT"),
        ({"skill": "verificar-proveedores", "texto": "9" * 100}, "demasiado largo"),
    ],
)
def test_pedidos_invalidos_devuelven_400_sin_ejecutar_el_agente(
    cliente, agente_falso, cuerpo, fragmento
):
    # Arrange / Act
    respuesta = cliente.post("/api/trabajos", json=cuerpo)
    # Assert
    assert respuesta.status_code == 400
    assert fragmento in respuesta.get_json()["error"]
    assert agente_falso == []


def test_un_cuerpo_gigante_se_corta_con_413_en_json(cliente, agente_falso):
    # Arrange
    texto = "1" * (web.MAX_BYTES_PETICION + 10)
    # Act
    respuesta = _crear(cliente, texto)
    # Assert
    assert respuesta.status_code == 413
    assert "error" in respuesta.get_json()
    assert agente_falso == []


def test_una_ruta_inexistente_responde_json(cliente):
    # Arrange / Act
    respuesta = cliente.get("/api/nada")
    # Assert
    assert respuesta.status_code == 404
    assert "error" in respuesta.get_json()


def test_un_trabajo_inexistente_devuelve_404(cliente):
    # Arrange / Act
    respuesta = cliente.get("/api/trabajos/inexistente")
    # Assert
    assert respuesta.status_code == 404


# ---------- ciclo de vida del trabajo ----------


def test_verificar_arma_el_pedido_y_devuelve_informe_y_traza(cliente, agente_falso):
    # Arrange
    texto = f"{VALIDO}\n{INVALIDO}"
    # Act
    respuesta = _crear(cliente, texto)
    trabajo = _esperar(cliente, respuesta.get_json()["id"])
    # Assert
    assert respuesta.status_code == 202
    assert trabajo["estado"] == "listo"
    assert trabajo["informe"] == "# Informe\n\nOK"
    assert trabajo["traza"] == ["[1] consultar_cuit({'cuit': 'x'})"]
    assert trabajo["cuits"] == {"validos": 1, "invalidos": 1}
    skill, pedido = agente_falso[0]
    assert skill == "verificar-proveedores"
    assert VALIDO in pedido
    assert f"no los consultes y reportalos como 'CUIT inválido': {INVALIDO}" in pedido


def test_una_pregunta_vacia_se_rechaza_sin_ejecutar_el_agente(cliente, agente_falso):
    # Arrange / Act
    respuesta = _crear(cliente, "  ", skill="consultar-datos")
    # Assert
    assert respuesta.status_code == 400
    assert "pregunta" in respuesta.get_json()["error"]
    assert agente_falso == []


def test_una_pregunta_sin_contexto_llega_sola_al_agente(cliente, agente_falso):
    # Arrange / Act
    respuesta = _crear(cliente, "¿Cuáles están inactivos?", skill="consultar-datos")
    _esperar(cliente, respuesta.get_json()["id"])
    # Assert
    assert agente_falso == [("consultar-datos", "Pregunta actual: ¿Cuáles están inactivos?")]


def test_las_preguntas_largas_se_recortan(cliente, agente_falso):
    # Arrange
    pregunta = "a" * (web.MAX_PEDIDO + 300)
    # Act
    respuesta = _crear(cliente, pregunta, skill="consultar-datos")
    _esperar(cliente, respuesta.get_json()["id"])
    # Assert
    assert agente_falso[0][1] == f"Pregunta actual: {'a' * web.MAX_PEDIDO}"


def _preguntar(cliente, **extra):
    cuerpo = {"skill": "consultar-datos", "texto": "¿Y de esos?", **extra}
    respuesta = cliente.post("/api/trabajos", json=cuerpo)
    if respuesta.status_code == 202:
        _esperar(cliente, respuesta.get_json()["id"])
    return respuesta


def test_la_conversacion_previa_y_el_informe_viajan_como_contexto_delimitado(
    cliente, agente_falso
):
    # Arrange
    conversacion = [{"pregunta": "¿Cuántos hay?", "respuesta": "Dos."}]
    # Act
    _preguntar(cliente, conversacion=conversacion, informe="# Informe\n| CUIT |")
    # Assert
    pedido = agente_falso[0][1]
    assert "<conversacion>\nUsuario: ¿Cuántos hay?\nAsistente: Dos.\n</conversacion>" in pedido
    assert "<informe_actual>\n# Informe\n| CUIT |\n</informe_actual>" in pedido
    assert pedido.endswith("Pregunta actual: ¿Y de esos?")
    # La pregunta actual va al final, después del contexto.
    assert pedido.index("<conversacion>") < pedido.index("<informe_actual>")


def test_solo_se_conservan_los_ultimos_turnos_de_la_conversacion(cliente, agente_falso):
    # Arrange
    turnos = [{"pregunta": f"p{i}", "respuesta": f"r{i}"} for i in range(web.MAX_TURNOS + 3)]
    # Act
    _preguntar(cliente, conversacion=turnos)
    # Assert
    pedido = agente_falso[0][1]
    assert pedido.count("Usuario: ") == web.MAX_TURNOS
    assert "Usuario: p2\n" not in pedido  # los más viejos quedan afuera
    assert f"Usuario: p{web.MAX_TURNOS + 2}\n" in pedido


def test_los_turnos_y_el_informe_largos_se_recortan(cliente, agente_falso):
    # Arrange
    largo = "x" * 20_000  # supera los topes por turno, pero entra en la petición
    # Act
    _preguntar(
        cliente, conversacion=[{"pregunta": largo, "respuesta": largo}], informe=largo
    )
    # Assert
    pedido = agente_falso[0][1]
    assert pedido.count("x") == 2 * web.MAX_CHARS_TURNO + web.MAX_CHARS_INFORME


def test_sin_informe_ni_conversacion_no_se_agregan_bloques_vacios(cliente, agente_falso):
    # Arrange / Act
    _preguntar(cliente, conversacion=[], informe="   ")
    # Assert
    pedido = agente_falso[0][1]
    assert "<conversacion>" not in pedido
    assert "<informe_actual>" not in pedido


@pytest.mark.parametrize(
    "extra, fragmento",
    [
        ({"conversacion": "no es una lista"}, "Conversación inválida"),
        ({"conversacion": ["texto suelto"]}, "Conversación inválida"),
        ({"conversacion": [{"pregunta": "p"}]}, "Conversación inválida"),
        ({"conversacion": [{"pregunta": 1, "respuesta": "r"}]}, "Conversación inválida"),
        ({"informe": {"no": "texto"}}, "Informe inválido"),
    ],
)
def test_contexto_mal_formado_devuelve_400(cliente, agente_falso, extra, fragmento):
    # Arrange / Act
    respuesta = _preguntar(cliente, **extra)
    # Assert
    assert respuesta.status_code == 400
    assert fragmento in respuesta.get_json()["error"]
    assert agente_falso == []


def test_verificar_ignora_la_conversacion_y_el_informe(cliente, agente_falso):
    # Arrange / Act
    respuesta = cliente.post(
        "/api/trabajos",
        json={
            "skill": "verificar-proveedores", "texto": VALIDO,
            "conversacion": "basura", "informe": "# viejo",
        },
    )
    _esperar(cliente, respuesta.get_json()["id"])
    # Assert
    assert respuesta.status_code == 202
    assert "viejo" not in agente_falso[0][1]


def test_un_error_conocido_se_muestra_al_usuario(cliente, monkeypatch):
    # Arrange
    def falla(*_, **__):
        raise RuntimeError("Falta GEMINI_API_KEY en el entorno o en .env")

    monkeypatch.setattr(web, "ejecutar_agente", falla)
    # Act
    trabajo = _esperar(cliente, _crear(cliente).get_json()["id"])
    # Assert
    assert trabajo["estado"] == "error"
    assert "GEMINI_API_KEY" in trabajo["error"]
    assert trabajo["informe"] is None


def test_un_error_de_configuracion_se_muestra_al_usuario(cliente, monkeypatch):
    # Arrange
    def falla(*_, **__):
        raise ConfigError("falta el campo obligatorio 'model'")

    monkeypatch.setattr(web, "ejecutar_agente", falla)
    # Act
    trabajo = _esperar(cliente, _crear(cliente).get_json()["id"])
    # Assert
    assert trabajo["error"] == "falta el campo obligatorio 'model'"


def test_un_error_inesperado_no_filtra_detalles_al_navegador(cliente, monkeypatch):
    # Arrange
    def falla(*_, **__):
        raise ValueError("ruta interna /home/usuario/secreto.key")

    monkeypatch.setattr(web, "ejecutar_agente", falla)
    # Act
    trabajo = _esperar(cliente, _crear(cliente).get_json()["id"])
    # Assert
    assert trabajo["estado"] == "error"
    assert "secreto" not in trabajo["error"]
    assert "terminal" in trabajo["error"]


def test_la_traza_se_acota(cliente, monkeypatch):
    # Arrange
    def ruidoso(skill, pedido, registrar, **_):
        for i in range(web.MAX_LINEAS_TRAZA + 50):
            registrar(f"linea {i}")
        return "listo"

    monkeypatch.setattr(web, "ejecutar_agente", ruidoso)
    # Act
    trabajo = _esperar(cliente, _crear(cliente).get_json()["id"])
    # Assert
    assert len(trabajo["traza"]) == web.MAX_LINEAS_TRAZA


def test_solo_se_conservan_los_ultimos_trabajos(cliente, agente_falso):
    # Arrange / Act
    ids = []
    for _ in range(web.MAX_TRABAJOS + 3):
        id_trabajo = _crear(cliente).get_json()["id"]
        _esperar(cliente, id_trabajo)
        ids.append(id_trabajo)
    # Assert
    assert cliente.get(f"/api/trabajos/{ids[0]}").status_code == 404
    assert cliente.get(f"/api/trabajos/{ids[-1]}").status_code == 200


def test_no_se_lanzan_dos_ejecuciones_a_la_vez(cliente, monkeypatch):
    # Arrange: el agente queda bloqueado hasta que el test lo libere.
    liberar = threading.Event()

    def lento(*_, **__):
        liberar.wait(timeout=5)
        return "listo"

    monkeypatch.setattr(web, "ejecutar_agente", lento)
    primero = _crear(cliente)
    # Act
    segundo = _crear(cliente)
    liberar.set()
    trabajo = _esperar(cliente, primero.get_json()["id"])
    tercero = _crear(cliente)
    # Assert
    assert primero.status_code == 202
    assert segundo.status_code == 409
    assert trabajo["estado"] == "listo"
    assert tercero.status_code == 202  # al terminar, el cupo queda libre
    _esperar(cliente, tercero.get_json()["id"])


# ---------- configuración e historial ----------


def test_config_expone_los_parametros_del_agent_md(cliente):
    # Arrange / Act
    datos = cliente.get("/api/config").get_json()
    # Assert
    assert datos["temperature"] == 0.0
    assert datos["modelo"].startswith("gemini-")
    assert {s["nombre"] for s in datos["skills"]} == {"verificar-proveedores", "consultar-datos"}
    assert datos["max_tool_iterations"] >= 1


def test_historial_devuelve_lo_guardado_sin_pasar_por_el_modelo(cliente):
    # Arrange
    historia.guardar_consulta(VALIDO, {"persona": {"razonSocial": "ACME SA", "estadoClave": "ACTIVO"}})
    # Act
    datos = cliente.get("/api/historial").get_json()
    # Assert
    assert [c["cuit"] for c in datos["consultas"]] == [VALIDO]
    assert datos["consultas"][0]["razon_social"] == "ACME SA"


def test_historial_devuelve_datos_hostiles_tal_cual_para_que_el_front_los_escape(cliente):
    # Arrange: el servidor no sanea; el front los inserta con textContent.
    nombre = '<img src=x onerror="alert(1)">'
    historia.guardar_consulta(VALIDO, {"persona": {"razonSocial": nombre, "estadoClave": "ACTIVO"}})
    # Act
    datos = cliente.get("/api/historial").get_json()
    # Assert
    assert datos["consultas"][0]["razon_social"] == nombre


# ---------- temperatura editable ----------


def _con_temperature(cliente, valor, texto=VALIDO):
    return cliente.post(
        "/api/trabajos",
        json={"skill": "verificar-proveedores", "texto": texto, "temperature": valor},
    )


@pytest.mark.parametrize("valor, esperada", [(0, 0.0), (0.7, 0.7), (2, 2.0), (1, 1.0)])
def test_la_temperatura_elegida_llega_al_agente(cliente, agente_falso, valor, esperada):
    # Arrange / Act
    respuesta = _con_temperature(cliente, valor)
    _esperar(cliente, respuesta.get_json()["id"])
    # Assert
    assert respuesta.status_code == 202
    assert agente_falso.temperaturas == [esperada]


def test_sin_temperatura_se_usa_la_del_agent_md(cliente, agente_falso):
    # Arrange / Act
    respuesta = _crear(cliente)
    _esperar(cliente, respuesta.get_json()["id"])
    # Assert: None significa "no reemplazar".
    assert agente_falso.temperaturas == [None]


@pytest.mark.parametrize("valor", [-0.1, 2.5, 100, True, "0.5", [0], {"t": 1}])
def test_una_temperatura_invalida_devuelve_400_sin_ejecutar_el_agente(
    cliente, agente_falso, valor
):
    # Arrange / Act
    respuesta = _con_temperature(cliente, valor)
    # Assert
    assert respuesta.status_code == 400
    assert "temperature" in respuesta.get_json()["error"]
    assert agente_falso == []


def test_una_temperatura_nan_enviada_como_json_crudo_se_rechaza(cliente, agente_falso):
    # Arrange: Python acepta NaN al leer JSON aunque no sea JSON válido.
    cuerpo = f'{{"skill": "verificar-proveedores", "texto": "{VALIDO}", "temperature": NaN}}'
    # Act
    respuesta = cliente.post("/api/trabajos", data=cuerpo, content_type="application/json")
    # Assert
    assert respuesta.status_code == 400
    assert agente_falso == []


# ---------- streaming de eventos (SSE) ----------


def _leer_sse(cuerpo: str):
    """Devuelve ([(id, evento)], [líneas de comentario]) a partir de un cuerpo SSE."""
    eventos, comentarios = [], []
    for bloque in cuerpo.split("\n\n"):
        if not bloque.strip():
            continue
        if bloque.startswith(":"):
            comentarios.append(bloque)
            continue
        campos = dict(linea.split(": ", 1) for linea in bloque.split("\n") if ": " in linea)
        eventos.append((int(campos["id"]), json.loads(campos["data"])))
    return eventos, comentarios


@pytest.fixture
def agente_con_eventos(monkeypatch):
    """Agente falso que emite herramientas y texto en pedazos, como el real."""

    def falso(skill, pedido, registrar, eventos=None, temperature=None):
        eventos({"tipo": "herramienta", "id": 1, "nombre": "historial_consultas",
                 "argumentos": {"limite": 100}})
        eventos({"tipo": "herramienta_fin", "id": 1, "ok": True, "ms": 12, "error": None})
        eventos({"tipo": "texto", "delta": "Hay "})
        eventos({"tipo": "texto", "delta": "3 años"})
        return "Hay 3 años"

    monkeypatch.setattr(web, "ejecutar_agente", falso)


def test_el_stream_entrega_herramientas_texto_y_evento_final_en_orden(
    cliente, agente_con_eventos
):
    # Arrange
    id_trabajo = _crear(cliente).get_json()["id"]
    _esperar(cliente, id_trabajo)
    # Act
    respuesta = cliente.get(f"/api/trabajos/{id_trabajo}/eventos")
    eventos, _ = _leer_sse(respuesta.get_data(as_text=True))
    # Assert
    assert respuesta.mimetype == "text/event-stream"
    assert [e["tipo"] for _, e in eventos] == [
        "herramienta", "herramienta_fin", "texto", "texto", "fin",
    ]
    assert [i for i, _ in eventos] == [1, 2, 3, 4, 5]
    assert eventos[0][1]["nombre"] == "historial_consultas"
    assert eventos[-1][1] == {
        "tipo": "fin", "estado": "listo", "informe": "Hay 3 años", "error": None,
    }


def test_el_stream_conserva_los_caracteres_no_ascii(cliente, agente_con_eventos):
    # Arrange
    id_trabajo = _crear(cliente).get_json()["id"]
    _esperar(cliente, id_trabajo)
    # Act
    cuerpo = cliente.get(f"/api/trabajos/{id_trabajo}/eventos").get_data(as_text=True)
    # Assert: sin escapes \uXXXX innecesarios.
    assert "3 años" in cuerpo


@pytest.mark.parametrize("como", ["query", "cabecera"])
def test_el_stream_se_puede_retomar_sin_repetir_eventos(cliente, agente_con_eventos, como):
    # Arrange
    id_trabajo = _crear(cliente).get_json()["id"]
    _esperar(cliente, id_trabajo)
    url = f"/api/trabajos/{id_trabajo}/eventos"
    # Act
    if como == "query":
        respuesta = cliente.get(url + "?desde=3")
    else:
        respuesta = cliente.get(url, headers={"Last-Event-ID": "3"})
    eventos, _ = _leer_sse(respuesta.get_data(as_text=True))
    # Assert
    assert [i for i, _ in eventos] == [4, 5]
    assert [e["tipo"] for _, e in eventos] == ["texto", "fin"]


@pytest.mark.parametrize("desde", ["abc", "-5", ""])
def test_un_punto_de_reanudacion_invalido_empieza_desde_el_principio(
    cliente, agente_con_eventos, desde
):
    # Arrange
    id_trabajo = _crear(cliente).get_json()["id"]
    _esperar(cliente, id_trabajo)
    # Act
    respuesta = cliente.get(f"/api/trabajos/{id_trabajo}/eventos?desde={desde}")
    eventos, _ = _leer_sse(respuesta.get_data(as_text=True))
    # Assert
    assert [i for i, _ in eventos] == [1, 2, 3, 4, 5]


def test_el_stream_de_un_trabajo_inexistente_devuelve_404(cliente):
    # Arrange / Act
    respuesta = cliente.get("/api/trabajos/inexistente/eventos")
    # Assert
    assert respuesta.status_code == 404


def test_un_error_se_transmite_como_evento_final(cliente, monkeypatch):
    # Arrange
    def falla(*_, **__):
        raise RuntimeError("Falta GEMINI_API_KEY en el entorno o en .env")

    monkeypatch.setattr(web, "ejecutar_agente", falla)
    id_trabajo = _crear(cliente).get_json()["id"]
    _esperar(cliente, id_trabajo)
    # Act
    eventos, _ = _leer_sse(cliente.get(f"/api/trabajos/{id_trabajo}/eventos").get_data(as_text=True))
    # Assert
    assert eventos[-1][1]["tipo"] == "fin"
    assert eventos[-1][1]["estado"] == "error"
    assert "GEMINI_API_KEY" in eventos[-1][1]["error"]


def test_las_lineas_de_traza_tambien_viajan_como_eventos(cliente, agente_falso):
    # Arrange
    id_trabajo = _crear(cliente).get_json()["id"]
    _esperar(cliente, id_trabajo)
    # Act
    eventos, _ = _leer_sse(cliente.get(f"/api/trabajos/{id_trabajo}/eventos").get_data(as_text=True))
    # Assert
    trazas = [e["linea"] for _, e in eventos if e["tipo"] == "traza"]
    assert trazas == ["[1] consultar_cuit({'cuit': 'x'})"]


def test_el_stream_entrega_los_eventos_mientras_el_agente_sigue_trabajando(
    cliente, monkeypatch
):
    # Arrange: el agente emite un evento y se queda esperando; el segundo llega después.
    liberar = threading.Event()
    monkeypatch.setattr(web, "SEGUNDOS_LATIDO", 0.1)

    def en_dos_tiempos(skill, pedido, registrar, eventos=None, temperature=None):
        eventos({"tipo": "texto", "delta": "primero"})
        liberar.wait(timeout=10)
        eventos({"tipo": "texto", "delta": "segundo"})
        return "primero segundo"

    monkeypatch.setattr(web, "ejecutar_agente", en_dos_tiempos)
    id_trabajo = _crear(cliente).get_json()["id"]
    respuesta = cliente.get(f"/api/trabajos/{id_trabajo}/eventos")
    trozos = respuesta.iter_encoded()
    # Act: se lee el stream sin que el agente haya terminado.
    vistos = []
    for _ in range(50):
        trozo = next(trozos).decode()
        if trozo.startswith("id:"):
            vistos.append(trozo)
            break
    antes_de_liberar = web._trabajos[id_trabajo].estado
    liberar.set()
    resto = b"".join(trozos).decode()
    # Assert
    assert vistos and '"primero"' in vistos[0]
    assert antes_de_liberar == "en_curso"
    assert '"segundo"' in resto
    assert '"estado": "listo"' in resto


def test_si_no_pasa_nada_el_stream_manda_latidos_para_mantener_la_conexion(
    cliente, monkeypatch
):
    # Arrange
    liberar = threading.Event()
    monkeypatch.setattr(web, "SEGUNDOS_LATIDO", 0.05)
    monkeypatch.setattr(web, "ejecutar_agente", lambda *_, **__: liberar.wait(timeout=10) or "ok")
    id_trabajo = _crear(cliente).get_json()["id"]
    trozos = cliente.get(f"/api/trabajos/{id_trabajo}/eventos").iter_encoded()
    # Act
    primero = next(trozos).decode()
    liberar.set()
    b"".join(trozos)
    # Assert
    assert primero.startswith(": latido")


# ---------- objeto Trabajo ----------


def test_trabajo_acota_los_eventos_pero_siempre_registra_el_final(monkeypatch):
    # Arrange
    monkeypatch.setattr(web, "MAX_EVENTOS", 3)
    trabajo = web.Trabajo(None)
    # Act
    for i in range(10):
        trabajo.emitir({"tipo": "texto", "delta": str(i)})
    trabajo.terminar("listo", "x", None)
    # Assert
    assert [e["tipo"] for e in trabajo.eventos] == ["texto", "texto", "texto", "fin"]


def test_trabajo_esperar_devuelve_vacio_si_vence_el_plazo():
    # Arrange
    trabajo = web.Trabajo(None)
    # Act
    eventos, terminado = trabajo.esperar(0, timeout=0.01)
    # Assert
    assert (eventos, terminado) == ([], False)


def test_trabajo_esperar_despierta_cuando_llega_un_evento():
    # Arrange
    trabajo = web.Trabajo(None)
    threading.Timer(0.05, trabajo.emitir, args=({"tipo": "texto", "delta": "a"},)).start()
    # Act
    inicio = time.monotonic()
    eventos, terminado = trabajo.esperar(0, timeout=5)
    # Assert
    assert eventos == [{"tipo": "texto", "delta": "a"}]
    assert terminado is False
    assert time.monotonic() - inicio < 2  # despertó por el evento, no por el plazo


def test_trabajo_publico_no_expone_el_estado_interno():
    # Arrange
    trabajo = web.Trabajo({"validos": 1, "invalidos": 0})
    trabajo.registrar("linea")
    # Act
    datos = trabajo.publico()
    # Assert
    assert set(datos) == {"estado", "traza", "informe", "error", "cuits"}
    assert datos["traza"] == ["linea"]
    datos["traza"].append("otra")  # es una copia
    assert trabajo.traza == ["linea"]


# ---------- borrado del historial ----------


def _sembrar(*cuits):
    for cuit in cuits:
        historia.guardar_consulta(cuit, {"persona": {"razonSocial": f"EMPRESA {cuit}"}})


def test_el_historial_informa_el_total_ademas_de_la_lista(cliente):
    # Arrange
    _sembrar("20000000028", "30000000066")
    # Act
    datos = cliente.get("/api/historial").get_json()
    # Assert
    assert datos["total"] == 2
    assert len(datos["consultas"]) == 2


def test_vaciar_el_historial_con_confirmacion_borra_todo(cliente):
    # Arrange
    _sembrar("20000000028", "30000000066", "30000000012")
    # Act
    respuesta = cliente.delete("/api/historial", json={"confirmar": True})
    # Assert
    assert respuesta.status_code == 200
    assert respuesta.get_json() == {"eliminadas": 3}
    assert cliente.get("/api/historial").get_json() == {"consultas": [], "total": 0}


@pytest.mark.parametrize(
    "cuerpo", [{}, {"confirmar": False}, {"confirmar": "true"}, {"confirmar": 1}, [True], "si"]
)
def test_vaciar_el_historial_sin_confirmacion_explicita_no_borra_nada(cliente, cuerpo):
    # Arrange
    _sembrar("20000000028")
    # Act
    respuesta = cliente.delete("/api/historial", json=cuerpo)
    # Assert
    assert respuesta.status_code == 400
    assert "confirm" in respuesta.get_json()["error"].lower()
    assert historia.contar() == 1


def test_vaciar_sin_cuerpo_json_se_rechaza(cliente):
    # Arrange
    _sembrar("20000000028")
    # Act: sin Content-Type JSON (como enviaría un formulario o un enlace cruzado).
    respuesta = cliente.delete("/api/historial")
    # Assert
    assert respuesta.status_code == 415
    assert historia.contar() == 1


def test_vaciar_desde_otro_origen_se_rechaza_contra_csrf(cliente):
    # Arrange
    _sembrar("20000000028")
    # Act
    respuesta = cliente.delete(
        "/api/historial", json={"confirmar": True}, headers={"Origin": "http://evil.example"}
    )
    # Assert
    assert respuesta.status_code == 403
    assert historia.contar() == 1


def test_borrar_un_cuit_elimina_solo_ese_cuit(cliente):
    # Arrange
    _sembrar("20000000028", "30000000066")
    # Act
    respuesta = cliente.delete("/api/historial/20-00000002-8", json={})
    # Assert
    assert respuesta.status_code == 200
    assert respuesta.get_json() == {"eliminadas": 1}
    assert [c["cuit"] for c in cliente.get("/api/historial").get_json()["consultas"]] == [
        "30000000066"
    ]


def test_borrar_un_cuit_que_no_esta_devuelve_cero(cliente):
    # Arrange
    _sembrar("30000000066")
    # Act
    respuesta = cliente.delete("/api/historial/20000000028", json={})
    # Assert
    assert respuesta.status_code == 200
    assert respuesta.get_json() == {"eliminadas": 0}
    assert historia.contar() == 1


@pytest.mark.parametrize("cuit", ["123", "abc", "2000000002a", "200000000280", "%27%20OR%20%271%27=%271"])
def test_borrar_con_un_cuit_mal_formado_devuelve_400_sin_tocar_nada(cliente, cuit):
    # Arrange
    _sembrar("20000000028")
    # Act
    respuesta = cliente.delete(f"/api/historial/{cuit}", json={})
    # Assert
    assert respuesta.status_code == 400
    assert historia.contar() == 1


def test_no_se_borra_mientras_hay_una_ejecucion_en_curso(cliente, monkeypatch):
    # Arrange: el agente queda bloqueado; podría estar por escribir en el historial.
    liberar = threading.Event()
    monkeypatch.setattr(web, "ejecutar_agente", lambda *_, **__: liberar.wait(timeout=10) or "ok")
    _sembrar("20000000028")
    id_trabajo = _crear(cliente).get_json()["id"]
    # Act
    todo = cliente.delete("/api/historial", json={"confirmar": True})
    uno = cliente.delete("/api/historial/20000000028", json={})
    liberar.set()
    _esperar(cliente, id_trabajo)
    despues = cliente.delete("/api/historial/20000000028", json={})
    # Assert
    assert (todo.status_code, uno.status_code) == (409, 409)
    assert despues.get_json() == {"eliminadas": 1}


# ---------- la ayuda de la interfaz ----------


def _html_normalizado():
    html = (DIRECTORIO_WEB / "index.html").read_text(encoding="utf-8")
    return " ".join(html.split())  # los saltos de línea del marcado no importan


@pytest.mark.parametrize(
    "id_elemento",
    [
        "abrir-ayuda", "ayuda", "ayuda-cerrar", "ver-funciones", "nueva", "abrir-historial",
        "historial-limpiar", "abrir-ajustes", "temperature", "temperature-reset", "archivo",
        "entrada", "enviar", "bajar", "modos",
    ],
)
def test_los_elementos_que_menciona_la_ayuda_existen_y_estan_conectados(id_elemento):
    # Arrange
    html = (DIRECTORIO_WEB / "index.html").read_text(encoding="utf-8")
    js = (DIRECTORIO_WEB / "app.js").read_text(encoding="utf-8")
    # Act / Assert: la ayuda describe estas funciones; si desaparecen, la ayuda miente.
    assert f'id="{id_elemento}"' in html
    assert f'"{id_elemento}"' in js  # `$("id")` o una lista de ids


@pytest.mark.parametrize("boton", ["Copiar", "Descargar .md", "Reintentar"])
def test_los_botones_de_cada_respuesta_que_menciona_la_ayuda_existen(boton):
    # Arrange
    ayuda = _html_normalizado()
    js = (DIRECTORIO_WEB / "app.js").read_text(encoding="utf-8")
    # Act / Assert
    assert boton in ayuda
    assert f'"{boton}"' in js


def test_los_numeros_de_la_ayuda_coinciden_con_los_limites_reales():
    # Arrange
    ayuda = _html_normalizado()
    js = (DIRECTORIO_WEB / "app.js").read_text(encoding="utf-8")
    # Act / Assert
    assert f"hasta {entradas.MAX_BYTES_CSV // 1024} KB y {entradas.MAX_FILAS_CSV} CUITs" in ayuda
    assert f"hasta {web.MAX_PEDIDO} caracteres" in ayuda
    assert f"últimos {web.MAX_TURNOS} intercambios" in ayuda
    assert f"las {web.MAX_HISTORIAL} más recientes" in ayuda
    # El front aplica los mismos topes que el servidor.
    assert f"MAX_TURNOS = {web.MAX_TURNOS};" in js
    assert f"MAX_BYTES_ARCHIVO = {entradas.MAX_BYTES_CSV // 1024} * 1024;" in js


def test_el_historial_nunca_devuelve_mas_de_lo_que_dice_la_ayuda(cliente):
    # Arrange
    for numero in range(web.MAX_HISTORIAL + 5):
        historia.guardar_consulta(f"20{numero:09d}", {"persona": {"razonSocial": "X"}})
    # Act
    datos = cliente.get("/api/historial").get_json()
    # Assert
    assert len(datos["consultas"]) == web.MAX_HISTORIAL
    assert datos["total"] == web.MAX_HISTORIAL + 5


def test_no_empieza_una_ejecucion_a_mitad_de_un_borrado(monkeypatch, agente_falso, tmp_path):
    # Arrange: el borrado queda trabado adentro; una consulta que llegue justo ahí
    # tiene que esperar, no colarse (chocaría con el VACUUM o perdería lo que guarda).
    monkeypatch.setattr(web, "_trabajos", web.OrderedDict())
    monkeypatch.setattr(web, "_en_curso", None)
    monkeypatch.setattr(historia, "DB_PATH", str(tmp_path / "h.db"))
    historia.inicializar_db()
    entro, liberar, resultado = threading.Event(), threading.Event(), {}

    def borrado_lento():
        entro.set()
        liberar.wait(timeout=5)
        return 0

    monkeypatch.setattr(historia, "eliminar_todo", borrado_lento)
    borrar = threading.Thread(
        target=lambda: web.app.test_client().delete("/api/historial", json={"confirmar": True})
    )
    crear = threading.Thread(target=lambda: resultado.update(r=_crear(web.app.test_client())))
    # Act
    borrar.start()
    assert entro.wait(timeout=5)
    crear.start()
    crear.join(timeout=0.4)
    quedo_esperando = crear.is_alive()
    liberar.set()
    borrar.join(timeout=5)
    crear.join(timeout=5)
    # Assert
    assert quedo_esperando
    assert resultado["r"].status_code == 202
