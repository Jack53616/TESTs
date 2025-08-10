
import os
import json
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Text, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class KV(Base):
    __tablename__ = "kv_store"
    key = Column(String(64), primary_key=True)
    value = Column(Text)  # JSON-encoded
    updated_at = Column(DateTime, default=datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_json(key: str, default=None):
    db = SessionLocal()
    try:
        row = db.get(KV, key)
        if not row:
            return default
        try:
            return json.loads(row.value)
        except Exception:
            return default
    finally:
        db.close()

def set_json(key: str, value):
    db = SessionLocal()
    try:
        payload = json.dumps(value, ensure_ascii=False)
        row = db.get(KV, key)
        if not row:
            row = KV(key=key, value=payload)
            db.add(row)
        else:
            row.value = payload
        db.commit()
    finally:
        db.close()
