import os
import sys
from sqlalchemy import create_engine, inspect

# Importar Base y el logger desde main.py
from main import Base, app_logger

app_logger.info("Iniciando script de inicialización de base de datos...")

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    app_logger.warning("No se encontró DATABASE_URL. Omitiendo la inicialización de la base de datos.")
    app_logger.info("Script de inicialización de base de datos finalizado sin realizar acciones.")
    sys.exit(0)

try:
    engine = create_engine(DATABASE_URL)
    app_logger.info("Verificando la existencia de la tabla 'memories'...")
    Base.metadata.create_all(bind=engine, checkfirst=True)
    app_logger.info("La verificación/creación de la tabla 'memories' ha finalizado.")
    app_logger.info("Script de inicialización de base de datos finalizado con éxito.")
except Exception as e:
    app_logger.error(f"Ocurrió un error durante la inicialización de la base de datos: {e}", exc_info=True)
    sys.exit(1) # Salir con un código de error para fallar el build
