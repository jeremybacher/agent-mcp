import os
import sys

from dotenv import load_dotenv

import padron
import wsaa

load_dotenv()


def main():
    cuit = os.environ.get("ARCA_CUIT")
    cert = os.environ.get("ARCA_CERT_PATH")
    key = os.environ.get("ARCA_KEY_PATH")

    if not all([cuit, cert, key]):
        sys.exit("Faltan variables de entorno. Copiá .env.example a .env y completalo.")

    print("Autenticando contra WSAA...")
    credenciales = wsaa.login("ws_sr_padron_a13", cert, key)
    print("Token obtenido. Expira:", credenciales["expiracion"])

    print(f"Consultando el CUIT {cuit} en el Padrón...")
    datos = padron.consultar_persona(cuit, cuit, credenciales["token"], credenciales["sign"])
    print(datos)


if __name__ == "__main__":
    main()
