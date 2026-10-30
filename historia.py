import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

DIRECTORIO_ACTUAL = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("ARCA_HISTORIAL_DB") or os.path.join(
    DIRECTORIO_ACTUAL, "historial.db"
)


def _conectar() -> sqlite3.Connection:
    conexion = sqlite3.connect(DB_PATH)
    conexion.row_factory = sqlite3.Row
    return conexion


def inicializar_db() -> None:
    """Crea la tabla 'consultas' si todavía no existe."""
    with _conectar() as conexion:
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS consultas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cuit TEXT NOT NULL,
                razon_social TEXT,
                estado TEXT,
                fecha TEXT NOT NULL,
                datos_json TEXT
            )
            """
        )
        conexion.execute(
            "CREATE INDEX IF NOT EXISTS idx_consultas_cuit ON consultas (cuit)"
        )


def _razon_social(persona: dict) -> str | None:
    if persona.get("razonSocial"):
        return persona["razonSocial"]
    nombre = persona.get("nombre", "") or ""
    apellido = persona.get("apellido", "") or ""
    completo = " ".join(parte for parte in (apellido, nombre) if parte)
    return completo or None


def guardar_consulta(cuit: str, resultado: dict) -> None:
    """Guarda una consulta al Padrón (cuit, razón social, estado y fecha) en la base local."""
    persona = (resultado or {}).get("persona", {})
    razon_social = _razon_social(persona)
    estado = persona.get("estadoClave")
    fecha = datetime.now(timezone.utc).isoformat()

    with _conectar() as conexion:
        conexion.execute(
            "INSERT INTO consultas (cuit, razon_social, estado, fecha, datos_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                cuit,
                razon_social,
                estado,
                fecha,
                json.dumps(resultado, ensure_ascii=False),
            ),
        )


def buscar_por_cuit(cuit: str) -> dict | None:
    """Devuelve la consulta más reciente guardada para un CUIT, o None si no hay ninguna."""
    with _conectar() as conexion:
        fila = conexion.execute(
            "SELECT * FROM consultas WHERE cuit = ? ORDER BY fecha DESC, id DESC LIMIT 1",
            (cuit,),
        ).fetchone()

    if fila is None:
        return None

    return {
        "cuit": fila["cuit"],
        "razon_social": fila["razon_social"],
        "estado": fila["estado"],
        "fecha": fila["fecha"],
        "resultado": json.loads(fila["datos_json"]) if fila["datos_json"] else None,
    }


def listar_ultimas(limite: int = 20) -> list[dict]:
    """Lista las últimas consultas guardadas, más recientes primero."""
    with _conectar() as conexion:
        filas = conexion.execute(
            "SELECT cuit, razon_social, estado, fecha, datos_json FROM consultas "
            "ORDER BY fecha DESC, id DESC LIMIT ?",
            (limite,),
        ).fetchall()

    resultado = []
    for fila in filas:
        item = dict(fila)
        datos_json = item.pop("datos_json", None)
        item["resultado"] = json.loads(datos_json) if datos_json else None
        resultado.append(item)

    return resultado


def contar() -> int:
    """Cantidad de consultas guardadas."""
    with closing(_conectar()) as conexion:
        return conexion.execute("SELECT COUNT(*) FROM consultas").fetchone()[0]


def eliminar_por_cuit(cuit: str) -> int:
    """Borra todas las consultas guardadas de un CUIT. Devuelve cuántas filas eliminó."""
    with closing(_conectar()) as conexion, conexion:
        return conexion.execute("DELETE FROM consultas WHERE cuit = ?", (cuit,)).rowcount


def eliminar_todo() -> int:
    """Vacía el historial y compacta el archivo. Devuelve cuántas filas eliminó.

    El `VACUUM` hace que los datos borrados no queden recuperables dentro del
    archivo SQLite (sin él, las páginas liberadas conservan el contenido).
    """
    with closing(_conectar()) as conexion, conexion:
        eliminadas = conexion.execute("DELETE FROM consultas").rowcount
    with closing(_conectar()) as conexion:
        conexion.execute("VACUUM")
    return eliminadas
