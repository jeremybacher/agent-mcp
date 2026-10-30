"""Interfaz web del agente de proveedores.

Sirve una página que ejecuta el agente en segundo plano y transmite en vivo
(Server-Sent Events) el texto de la respuesta y las herramientas que va usando.
Escucha solo en 127.0.0.1.

    python web.py   ->   http://127.0.0.1:5051
"""

import argparse
import asyncio
import json
import logging
import os
import secrets
import sys
import threading
import traceback
from collections import OrderedDict
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory
from google.genai import errors as genai_errors
from werkzeug.exceptions import HTTPException

import agent
import historia
import validacion
from agente import runner
from agente.config import ConfigError, cargar_agente, validar_temperature
from agente.entradas import (
    EntradaInvalidaError,
    armar_pedido_verificacion,
    extraer_cuits,
)
from agente.runner import LimiteDeIteracionesError

DIRECTORIO = os.path.dirname(os.path.abspath(__file__))
DIRECTORIO_WEB = os.path.join(DIRECTORIO, "web")
PUERTO = 5051

HOSTS_PERMITIDOS = {"127.0.0.1", "localhost"}
SKILL_VERIFICAR = "verificar-proveedores"
MAX_PEDIDO = 500
MAX_TURNOS = 6
MAX_CHARS_TURNO = 2000
MAX_CHARS_INFORME = 8000
MAX_TRABAJOS = 20
MAX_HISTORIAL = 50
MAX_LINEAS_TRAZA = 500
MAX_EVENTOS = 5000
MAX_BYTES_PETICION = 128 * 1024
SEGUNDOS_LATIDO = 15

# Sin scripts ni estilos inline: lo que devuelva el padrón nunca se ejecuta.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

app = Flask(__name__, static_folder=DIRECTORIO_WEB, static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = MAX_BYTES_PETICION


class Trabajo:
    """Una ejecución del agente: su estado y el registro de eventos, seguros entre hilos."""

    def __init__(self, cuits: dict | None):
        self.estado = "en_curso"
        self.traza: list[str] = []
        self.informe: str | None = None
        self.error: str | None = None
        self.cuits = cuits
        self.eventos: list[dict] = []
        self._cond = threading.Condition()

    def emitir(self, evento: dict) -> None:
        """Agrega un evento y avisa a quienes lo están esperando. Se acota para no crecer sin fin."""
        with self._cond:
            if len(self.eventos) < MAX_EVENTOS:
                self.eventos.append(evento)
                self._cond.notify_all()

    def registrar(self, linea: str) -> None:
        """Guarda una línea de traza y la emite como evento."""
        with self._cond:
            if len(self.traza) < MAX_LINEAS_TRAZA:
                self.traza.append(linea)
        self.emitir({"tipo": "traza", "linea": linea})

    def terminar(self, estado: str, informe: str | None, error: str | None) -> None:
        """Fija el resultado y emite el evento final (siempre se registra)."""
        with self._cond:
            self.informe, self.error, self.estado = informe, error, estado
            self.eventos.append(
                {"tipo": "fin", "estado": estado, "informe": informe, "error": error}
            )
            self._cond.notify_all()

    def esperar(self, desde: int, timeout: float) -> tuple[list[dict], bool]:
        """Bloquea hasta que haya eventos desde `desde` o termine; devuelve (eventos, terminó)."""
        with self._cond:
            self._cond.wait_for(
                lambda: len(self.eventos) > desde or self.estado != "en_curso", timeout
            )
            return list(self.eventos[desde:]), self.estado != "en_curso"

    def publico(self) -> dict:
        """Estado serializable para la API de consulta."""
        with self._cond:
            return {
                "estado": self.estado, "traza": list(self.traza), "informe": self.informe,
                "error": self.error, "cuits": self.cuits,
            }


_trabajos: OrderedDict[str, Trabajo] = OrderedDict()
_candado = threading.Lock()
_en_curso: str | None = None


def _nombre_host(valor: str) -> str:
    return (urlparse(f"//{valor}").hostname or "").lower()


@app.before_request
def _validar_origen():
    # Evita DNS rebinding: el Host tiene que ser local.
    if _nombre_host(request.host) not in HOSTS_PERMITIDOS:
        return jsonify(error="Host no permitido."), 403
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        # Evita que otra página del navegador dispare consultas (CSRF).
        origen = request.headers.get("Origin")
        if origen and urlparse(origen).netloc != request.host:
            return jsonify(error="Origen no permitido."), 403
        if not request.is_json:
            return jsonify(error="Se espera application/json."), 415
    return None


@app.after_request
def _cabeceras_de_seguridad(respuesta):
    respuesta.headers["Content-Security-Policy"] = CSP
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["Referrer-Policy"] = "no-referrer"
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


@app.errorhandler(HTTPException)
def _error_http(exc):
    return jsonify(error=exc.description), exc.code


def ejecutar_agente(
    skill: str, pedido: str, registrar, eventos=None, temperature: float | None = None
) -> str:
    """Corre el agente con la configuración por defecto y devuelve el informe.

    `eventos` recibe el texto transmitido y las herramientas usadas;
    `temperature`, si se pasa, reemplaza la del `.agent.md` solo en esta ejecución.
    """
    args = argparse.Namespace(
        skill=skill, pedido=pedido, csv=None, salida=None,
        agente=agent.AGENTE_POR_DEFECTO, temperature=temperature,
    )
    texto, _ = asyncio.run(agent.principal(args, registrar, eventos))
    return texto


def _correr_trabajo(id_trabajo: str, skill: str, pedido: str, temperature: float | None) -> None:
    global _en_curso
    trabajo = _trabajos[id_trabajo]

    def registrar(linea: str) -> None:
        trabajo.registrar(linea)
        runner.log(linea)

    estado, informe, error = "listo", None, None
    try:
        informe = ejecutar_agente(
            skill, pedido, registrar, eventos=trabajo.emitir, temperature=temperature
        )
    except (ConfigError, EntradaInvalidaError, LimiteDeIteracionesError, RuntimeError) as exc:
        estado, error = "error", str(exc)
    except genai_errors.APIError as exc:
        estado, error = "error", f"Falló la API del modelo: {exc}"
    except Exception:  # no se filtra el detalle al navegador
        runner.log(traceback.format_exc())
        estado, error = "error", "Error inesperado. Revisá la terminal donde corre web.py."

    # Se libera el cupo antes de publicar el estado final: "listo" o "error"
    # implican que ya se puede lanzar otra ejecución.
    with _candado:
        _en_curso = None
    trabajo.terminar(estado, informe, error)


def _turnos_previos(valor) -> list[tuple[str, str]]:
    """Valida la conversación enviada por el navegador y conserva los últimos turnos."""
    if not isinstance(valor, list):
        raise EntradaInvalidaError("Conversación inválida.")
    turnos = []
    for turno in valor[-MAX_TURNOS:]:
        if not isinstance(turno, dict):
            raise EntradaInvalidaError("Conversación inválida.")
        pregunta, respuesta = turno.get("pregunta"), turno.get("respuesta")
        if not isinstance(pregunta, str) or not isinstance(respuesta, str):
            raise EntradaInvalidaError("Conversación inválida.")
        turnos.append((pregunta[:MAX_CHARS_TURNO], respuesta[:MAX_CHARS_TURNO]))
    return turnos


def _pedido_de_preguntas(pregunta: str, turnos: list[tuple[str, str]], informe: str) -> str:
    """Arma el pedido de `consultar-datos`: contexto delimitado más la pregunta actual."""
    partes = []
    if turnos:
        dialogo = "\n".join(f"Usuario: {p}\nAsistente: {r}\n" for p, r in turnos)
        partes.append(f"<conversacion>\n{dialogo}</conversacion>")
    if informe.strip():
        partes.append(f"<informe_actual>\n{informe[:MAX_CHARS_INFORME]}\n</informe_actual>")
    partes.append(f"Pregunta actual: {pregunta}")
    return "\n\n".join(partes)


def _armar_pedido(skill: str, datos: dict) -> tuple[str, dict | None]:
    """Convierte lo escrito en la UI en el pedido para el agente."""
    texto = datos["texto"]
    if skill == SKILL_VERIFICAR:
        validos, invalidos = extraer_cuits(texto)
        if not validos and not invalidos:
            raise EntradaInvalidaError("No encontré ningún CUIT en el texto.")
        resumen = {"validos": len(validos), "invalidos": len(invalidos)}
        return armar_pedido_verificacion(validos, invalidos), resumen

    pregunta = texto.strip()[:MAX_PEDIDO]
    if not pregunta:
        raise EntradaInvalidaError("Escribí una pregunta.")
    informe = datos.get("informe", "")
    if not isinstance(informe, str):
        raise EntradaInvalidaError("Informe inválido.")
    turnos = _turnos_previos(datos.get("conversacion", []))
    return _pedido_de_preguntas(pregunta, turnos, informe), None


@app.get("/")
def indice():
    return send_from_directory(DIRECTORIO_WEB, "index.html")


@app.get("/api/config")
def configuracion():
    try:
        cfg = cargar_agente(agent.AGENTE_POR_DEFECTO, agent.DIRECTORIO_SKILLS)
    except ConfigError as exc:
        return jsonify(error=str(exc)), 500
    return jsonify(
        nombre=cfg.nombre,
        modelo=cfg.modelo,
        temperature=cfg.temperature,
        max_output_tokens=cfg.max_output_tokens,
        max_tool_iterations=cfg.max_tool_iterations,
        skills=[{"nombre": s.nombre, "descripcion": s.descripcion} for s in cfg.skills.values()],
    )


@app.post("/api/trabajos")
def crear_trabajo():
    global _en_curso
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify(error="Cuerpo inválido."), 400
    skill, texto = datos.get("skill"), datos.get("texto", "")
    if not isinstance(skill, str) or not isinstance(texto, str):
        return jsonify(error="Cuerpo inválido."), 400

    temperature = datos.get("temperature")
    if temperature is not None:
        try:
            temperature = validar_temperature(temperature)
        except ConfigError as exc:
            return jsonify(error=str(exc)), 400

    try:
        cfg = cargar_agente(agent.AGENTE_POR_DEFECTO, agent.DIRECTORIO_SKILLS)
    except ConfigError as exc:
        return jsonify(error=str(exc)), 500
    if skill not in cfg.skills:
        return jsonify(error=f"Skill '{skill}' no disponible."), 400

    try:
        pedido, resumen = _armar_pedido(skill, {**datos, "texto": texto})
    except EntradaInvalidaError as exc:
        return jsonify(error=str(exc)), 400

    with _candado:
        if _en_curso is not None:
            return jsonify(error="Ya hay una ejecución en curso."), 409
        id_trabajo = secrets.token_urlsafe(8)
        _trabajos[id_trabajo] = Trabajo(resumen)
        while len(_trabajos) > MAX_TRABAJOS:
            _trabajos.popitem(last=False)
        _en_curso = id_trabajo

    threading.Thread(
        target=_correr_trabajo, args=(id_trabajo, skill, pedido, temperature), daemon=True
    ).start()
    return jsonify(id=id_trabajo), 202


@app.get("/api/trabajos/<id_trabajo>")
def consultar_trabajo(id_trabajo: str):
    trabajo = _trabajos.get(id_trabajo)
    if trabajo is None:
        return jsonify(error="Trabajo inexistente."), 404
    return jsonify(trabajo.publico())


@app.get("/api/trabajos/<id_trabajo>/eventos")
def transmitir_eventos(id_trabajo: str):
    """Server-Sent Events: transmite los eventos del trabajo hasta que termina.

    Se puede retomar con `Last-Event-ID` (o `?desde=N`) sin perder eventos.
    """
    trabajo = _trabajos.get(id_trabajo)
    if trabajo is None:
        return jsonify(error="Trabajo inexistente."), 404
    try:
        desde = max(0, int(request.headers.get("Last-Event-ID") or request.args.get("desde") or 0))
    except ValueError:
        desde = 0

    def generar():
        indice = desde
        while True:
            lote, terminado = trabajo.esperar(indice, SEGUNDOS_LATIDO)
            for evento in lote:
                indice += 1
                carga = json.dumps(evento, ensure_ascii=False, default=str)
                yield f"id: {indice}\ndata: {carga}\n\n"
            if terminado:
                return  # el lote ya incluye el evento final
            if not lote:
                yield ": latido\n\n"

    return Response(
        generar(),
        mimetype="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.get("/api/historial")
def historial():
    return jsonify(consultas=historia.listar_ultimas(MAX_HISTORIAL), total=historia.contar())


def _borrar_sin_ejecuciones(accion):
    """Corre `accion` (un borrado) con el cupo de ejecución tomado.

    Se mantiene el candado durante todo el borrado: si se revisara "no hay ejecución"
    y se borrara después, una consulta podría empezar en ese hueco y chocar con el
    VACUUM o perder lo que acaba de guardar.
    """
    with _candado:
        if _en_curso is not None:
            return jsonify(error="Hay una ejecución en curso. Esperá a que termine."), 409
        return jsonify(eliminadas=accion())


# El borrado solo se expone a la UI, nunca como herramienta MCP: un modelo no
# debería poder borrar datos.
@app.delete("/api/historial")
def vaciar_historial():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict) or datos.get("confirmar") is not True:
        return jsonify(error='Falta la confirmación: {"confirmar": true}.'), 400
    return _borrar_sin_ejecuciones(historia.eliminar_todo)


@app.delete("/api/historial/<cuit>")
def borrar_del_historial(cuit: str):
    cuit = validacion.normalizar_cuit(cuit)
    if len(cuit) != 11 or not cuit.isascii() or not cuit.isdigit():
        return jsonify(error="El CUIT debe tener 11 dígitos."), 400
    return _borrar_sin_ejecuciones(lambda: historia.eliminar_por_cuit(cuit))


def main() -> None:
    """Levanta el servidor web local."""
    load_dotenv()
    historia.inicializar_db()
    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # sin una línea por cada poll
    runner.log(f"ARCA Agent UI: http://127.0.0.1:{PUERTO}")
    app.run(host="127.0.0.1", port=PUERTO, threaded=True, debug=False)


if __name__ == "__main__":
    sys.exit(main())
