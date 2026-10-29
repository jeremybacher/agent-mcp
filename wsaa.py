import base64
import json
import os
import subprocess
import tempfile
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import zeep

WSAA_WSDL = "https://wsaa.afip.gov.ar/ws/services/LoginCms?wsdl"

DIRECTORIO_ACTUAL = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(DIRECTORIO_ACTUAL, "token_cache.json")

_FORMATO_FECHA_WSAA = "%Y-%m-%dT%H:%M:%S%z"
_MARGEN_SEGURIDAD = timedelta(minutes=5)

_cache_lock = threading.Lock()


def _generar_tra(servicio: str) -> str:
    ahora = datetime.utcnow()
    generation_time = (ahora - timedelta(minutes=10)).strftime(
        "%Y-%m-%dT%H:%M:%S-00:00"
    )
    expiration_time = (ahora + timedelta(minutes=10)).strftime(
        "%Y-%m-%dT%H:%M:%S-00:00"
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<loginTicketRequest version="1.0">
  <header>
    <uniqueId>{int(ahora.timestamp())}</uniqueId>
    <generationTime>{generation_time}</generationTime>
    <expirationTime>{expiration_time}</expirationTime>
  </header>
  <service>{servicio}</service>
</loginTicketRequest>"""


def _firmar_tra(tra_xml: str, cert_path: str, key_path: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".xml", mode="w", delete=False) as tra_file:
        tra_file.write(tra_xml)
        tra_path = tra_file.name
    cms_path = tra_path + ".cms"

    try:
        subprocess.run(
            [
                "openssl",
                "smime",
                "-sign",
                "-signer",
                cert_path,
                "-inkey",
                key_path,
                "-outform",
                "DER",
                "-nodetach",
                "-in",
                tra_path,
                "-out",
                cms_path,
            ],
            check=True,
            capture_output=True,
        )
        with open(cms_path, "rb") as f:
            return f.read()
    finally:
        os.remove(tra_path)
        if os.path.exists(cms_path):
            os.remove(cms_path)


def _leer_cache() -> dict:
    try:
        with open(CACHE_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _escribir_cache(cache: dict) -> None:
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f)


def _token_vigente(credenciales: dict) -> bool:
    expiracion = credenciales.get("expiracion")
    if not expiracion:
        return False
    try:
        vencimiento = datetime.strptime(expiracion, _FORMATO_FECHA_WSAA)
    except ValueError:
        return False
    return datetime.now(timezone.utc) < (vencimiento - _MARGEN_SEGURIDAD)


def login(servicio: str, cert_path: str, key_path: str) -> dict:
    """Autentica contra WSAA de ARCA y devuelve token, sign y expiración.

    El resultado se cachea en `token_cache.json` por servicio: mientras el
    token cacheado siga vigente (con 5 minutos de margen), se reutiliza en
    vez de volver a autenticar contra WSAA.
    """
    with _cache_lock:
        cache = _leer_cache()
        credenciales = cache.get(servicio)
        if credenciales and _token_vigente(credenciales):
            return credenciales

        tra_xml = _generar_tra(servicio)
        cms = _firmar_tra(tra_xml, cert_path, key_path)
        cms_b64 = base64.b64encode(cms).decode("ascii")

        cliente = zeep.Client(WSAA_WSDL)
        respuesta_xml = cliente.service.loginCms(cms_b64)

        raiz = ET.fromstring(respuesta_xml)
        credenciales = {
            "token": raiz.findtext(".//token"),
            "sign": raiz.findtext(".//sign"),
            "expiracion": raiz.findtext(".//expirationTime"),
        }

        cache[servicio] = credenciales
        _escribir_cache(cache)
        return credenciales
