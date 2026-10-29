import zeep
import zeep.helpers

PADRON_A13_WSDL = "https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA13?WSDL"


def consultar_persona(cuit_representada: str, cuit_consultado: str, token: str, sign: str) -> dict:
    """Consulta los datos de un CUIT en el Padrón de ARCA (Alcance 13)."""
    cliente = zeep.Client(PADRON_A13_WSDL)
    respuesta = cliente.service.getPersona(token, sign, cuit_representada, cuit_consultado)
    return zeep.helpers.serialize_object(respuesta, dict)
