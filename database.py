import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base

# Allow database path to be configured via environment variable
# This is useful for Railway persistent volumes
DATABASE_PATH = os.getenv('DATABASE_PATH', 'food_log.db')
DATABASE_URL = f'sqlite:///{DATABASE_PATH}'

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(bind=engine)
