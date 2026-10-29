import logging
import os
import sys
import threading
import traceback

from dotenv import load_dotenv
from flask import Flask, jsonify, send_from_directory
from mcp.server.mcpserver import MCPServer

import historia
import padron
import validacion
import wsaa

load_dotenv()

MENSAJE_CUIT_INVALIDO = (
    "'{cuit}' no es un CUIT válido: deben ser 11 dígitos con prefijo y "
    "dígito verificador correctos."
)

logging.getLogger("werkzeug").disabled = True
os.environ["WERKZEUG_RUN_MAIN"] = "true"

DIRECTORIO_ACTUAL = os.path.dirname(os.path.abspath(__file__))
SERVICIO = "ws_sr_padron_a13"

CUIT_REPRESENTADA = os.environ.get("ARCA_CUIT")
CERT_PATH = os.environ.get("ARCA_CERT_PATH")
KEY_PATH = os.environ.get("ARCA_KEY_PATH")

mcp = MCPServer("ArcaAgent")
app = Flask(__name__)

historia.inicializar_db()

ULTIMA_CONSULTA = {"cuit": None, "resultado": None}

CAMPOS_PUBLICOS = (
    "nombre",
    "apellido",
    "razonSocial",
    "estadoClave",
    "descripcionActividadPrincipal",
    "tipoPersona",
)


def log(mensaje: str) -> None:
    # stderr, nunca stdout: mcp.run() usa stdout para el protocolo stdio.
    print(mensaje, file=sys.stderr, flush=True)


def _datos_minimos(persona: dict) -> dict:
    # No exponemos DNI, fecha de nacimiento ni domicilio: son más datos
    # personales de los que hace falta mostrar en una demo grabada.
    return {
        campo: persona[campo]
        for campo in CAMPOS_PUBLICOS
        if persona.get(campo) is not None
    }


@mcp.tool()
def consultar_cuit(cuit: str) -> dict:
    """Consulta los datos de un contribuyente en el Padrón de ARCA a partir de su CUIT.

    Antes de ir a ARCA, revisa el historial local (SQLite): si ya existe una
    consulta guardada para ese CUIT, devuelve ese resultado sin llamar al
    Padrón.
    """
    cuit = validacion.normalizar_cuit(cuit)
    log(f"consultar_cuit: recibida consulta para {cuit}")

    if not validacion.validar_cuit(cuit):
        log(f"consultar_cuit: '{cuit}' no es un CUIT válido")
        return {"error": MENSAJE_CUIT_INVALIDO.format(cuit=cuit)}

    previa = historia.buscar_por_cuit(cuit)
    if previa is not None:
        log(f"consultar_cuit: {cuit} encontrado en el historial, no se consulta ARCA")
        resultado = previa["resultado"]
        ULTIMA_CONSULTA["cuit"] = cuit
        ULTIMA_CONSULTA["resultado"] = resultado
        return {**resultado, "_origen": "historial", "_fecha": previa["fecha"]}

    try:
        log("consultar_cuit: autenticando contra WSAA...")
        credenciales = wsaa.login(SERVICIO, CERT_PATH, KEY_PATH)
        log("consultar_cuit: token obtenido, consultando el Padrón...")
        resultado = padron.consultar_persona(
            CUIT_REPRESENTADA, cuit, credenciales["token"], credenciales["sign"]
        )
        resultado = {"persona": _datos_minimos(resultado.get("persona", {}))}
        log(f"consultar_cuit: consulta de {cuit} completada")
    except Exception as exc:
        log(f"consultar_cuit: fallo consultando {cuit} -> {exc}")
        log(traceback.format_exc())
        return {"error": f"Fallo al consultar ARCA: {exc}"}

    historia.guardar_consulta(cuit, resultado)

    ULTIMA_CONSULTA["cuit"] = cuit
    ULTIMA_CONSULTA["resultado"] = resultado
    return resultado


@mcp.tool()
def historial_consultas(limite: int = 20) -> dict:
    """Lista las últimas consultas guardadas en el historial local (SQLite).

    `limite` se acota al rango 1-100.
    """
    limite = validacion.acotar_limite(limite)
    log(f"historial_consultas: listando últimas {limite} consultas")
    return {"consultas": historia.listar_ultimas(limite)}


@mcp.tool()
def buscar_en_historial(cuit: str) -> dict:
    """Busca en el historial local si ya existe una consulta guardada para un CUIT."""
    cuit = validacion.normalizar_cuit(cuit)
    log(f"buscar_en_historial: buscando {cuit}")

    if not validacion.validar_cuit(cuit):
        return {"error": MENSAJE_CUIT_INVALIDO.format(cuit=cuit)}

    encontrada = historia.buscar_por_cuit(cuit)
    if encontrada is None:
        return {"encontrado": False, "cuit": cuit}

    return {"encontrado": True, **encontrada}


@app.route("/")
def index():
    return send_from_directory(DIRECTORIO_ACTUAL, "index.html")


@app.route("/estado")
def consultar_estado():
    response = jsonify(ULTIMA_CONSULTA)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.route("/historial")
def consultar_historial():
    response = jsonify({"consultas": historia.listar_ultimas(50)})
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


def ejecutar_web():
    from werkzeug.serving import make_server

    try:
        server = make_server("127.0.0.1", 5050, app)
    except OSError as exc:
        log(f"Dashboard: no se pudo levantar en el puerto 5050 ({exc}).")
        log(
            "Probablemente ya haya otro proceso server.py corriendo: 'ps aux | grep server.py' y matalo."
        )
        return
    server.serve_forever()


if __name__ == "__main__":
    hilo_web = threading.Thread(target=ejecutar_web, daemon=True)
    hilo_web.start()
    log("Dashboard disponible en http://127.0.0.1:5050")
    log("Servidor MCP listo, esperando conexión por stdio...")
    mcp.run()
