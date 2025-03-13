# app/createdb.py

from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Создание соединения с базой данных SQLite
DATABASE_URL = "sqlite:///hv_cells.db"
engine = create_engine(DATABASE_URL)
Base = declarative_base()


# Определение модели таблицы
class HVCell(Base):
    __tablename__ = 'hv_cells'

    id = Column(Integer, primary_key=True, autoincrement=True)
    cell_number = Column(String, nullable=False)
    cell_name = Column(String, nullable=False)
    unit_id = Column(Integer, nullable=False)
    coil_register = Column(Integer, nullable=False)
    mqtt_channel = Column(String, nullable=True)
    parameter_description = Column(String, nullable=True)
    state_name_true = Column(String, nullable=True)
    state_name_false = Column(String, nullable=True)
    display_state = Column(Boolean, nullable=False, default=False)
    display_text = Column(String, nullable=True)


# Создание таблицы в базе данных
if __name__ == "__main__":
    Base.metadata.create_all(engine)
    print("Таблица создана успешно!")
