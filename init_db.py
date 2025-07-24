import os
import sys
import logging

# --- Set up a simple logger for this script ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout # Log to standard output, which is standard for deploy environments
)
logger = logging.getLogger("InitDB")

# Importar los componentes necesarios desde sus archivos de origen
from database import Base, engine, DATABASE_URL

logger.info("Iniciando script de inicialización de base de datos...")

if not DATABASE_URL:
    logger.warning("No se encontró DATABASE_URL. Omitiendo la inicialización de la base de datos.")
    logger.info("Script de inicialización de base de datos finalizado sin realizar acciones.")
    sys.exit(0)

try:
    if not engine:
        raise ConnectionError("El motor de la base de datos no se pudo inicializar. Verifica la DATABASE_URL.")
    logger.info("Verificando la existencia de la tabla 'memories'...")
    Base.metadata.create_all(bind=engine, checkfirst=True)
    logger.info("La verificación/creación de la tabla 'memories' ha finalizado.")
    logger.info("Script de inicialización de base de datos finalizado con éxito.")
except Exception as e:
    logger.error(f"Ocurrió un error durante la inicialización de la base de datos: {e}", exc_info=True)
    sys.exit(1) # Salir con un código de error para que el build falle
