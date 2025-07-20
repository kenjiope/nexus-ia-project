import os
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.orm import sessionmaker, declarative_base

# Get the database URL from environment variables (provided by Render)
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    # SQLAlchemy 1.4+ requires "postgresql://" instead of "postgres://"
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL) if DATABASE_URL else None
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) if engine else None

Base = declarative_base()

class MemoryDB(Base):
    """SQLAlchemy model for the memories table."""
    __tablename__ = "memories"
    session_id = Column(String, primary_key=True, index=True)
    memory_json = Column(Text, nullable=False)
    history_json = Column(Text, nullable=True) # Columna para el historial de chat
