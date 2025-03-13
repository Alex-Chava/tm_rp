# database.py

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from .models import Base

engine = None
db_session = scoped_session(sessionmaker())

def init_db(db_url):
    global engine
    engine = create_engine(db_url, echo=False)  # echo=True для отладки SQL
    db_session.configure(bind=engine)
    Base.metadata.create_all(bind=engine)
