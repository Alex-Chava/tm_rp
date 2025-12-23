# database.py

from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker
from .models import Base

engine = None
db_session = scoped_session(sessionmaker())

def ensure_hv_cells_cell_type(engine):
    """SQLite: если в hv_cells нет колонки cell_type — добавляем."""
    with engine.connect() as conn:
        cols = conn.execute(text("PRAGMA table_info(hv_cells)")).fetchall()
        names = {c[1] for c in cols}  # 2-й элемент = name
        if "cell_type" not in names:
            conn.execute(text("ALTER TABLE hv_cells ADD COLUMN cell_type VARCHAR(16)"))
            conn.commit()

def init_db(db_url):
    global engine
    engine = create_engine(db_url, echo=False)  # echo=True для отладки SQL
    ensure_hv_cells_cell_type(engine)
    db_session.configure(bind=engine)
    Base.metadata.create_all(bind=engine)
