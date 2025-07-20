import os
import sys

# Importar los componentes necesarios desde sus archivos de origen
# Esto rompe la dependencia circular que causaba el error de despliegue.
from database import Base, engine, DATABASE_URL
from main import app_logger

app_logger.info("Iniciando script de inicialización de base de datos...")

if not DATABASE_URL:
    app_logger.warning("No se encontró DATABASE_URL. Omitiendo la inicialización de la base de datos.")
    app_logger.info("Script de inicialización de base de datos finalizado sin realizar acciones.")
    sys.exit(0)

try:
    if not engine:
        raise ConnectionError("El motor de la base de datos no se pudo inicializar. Verifica la DATABASE_URL.")
    app_logger.info("Verificando la existencia de la tabla 'memories'...")
    Base.metadata.create_all(bind=engine, checkfirst=True)
    app_logger.info("La verificación/creación de la tabla 'memories' ha finalizado.")
    app_logger.info("Script de inicialización de base de datos finalizado con éxito.")
except Exception as e:
    app_logger.error(f"Ocurrió un error durante la inicialización de la base de datos: {e}", exc_info=True)
    sys.exit(1) # Salir con un código de error para que el build falle
