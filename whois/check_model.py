import os
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base  # Импорт из sqlalchemy.orm

# Определение базового класса модели
Base = declarative_base()

# Определение модели таблицы
class HVCell(Base):
    __tablename__ = 'hv_cells'
    id = Column(Integer, primary_key=True)
    cell_number = Column(Integer, default=0)
    cell_name = Column(String(64), default='')
    unit_id = Column(Integer, default=0)
    coil_register = Column(Integer, default=0)
    mqtt_channel = Column(String(64), default='')
    parameter_description = Column(String(128), default='')
    state_name_true = Column(String(64), default='')
    state_name_false = Column(String(64), default='')
    display_state = Column(Boolean, default=False)
    display_text = Column(String(128), default='')
    value = Column(Boolean, default=False)
    value_date = Column(DateTime)

# Определение пути к базе данных
base_dir = os.path.abspath(os.path.dirname(__file__))
database_path = os.path.join(base_dir, 'database.db')
DATABASE_URL = f"sqlite:///{database_path}"

# Настройка подключения к базе данных
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

# Создание таблиц, если они не существуют
Base.metadata.create_all(engine)

# Добавление 32 пустых строк
def add_empty_rows(num_rows=32):
    for _ in range(num_rows):
        new_cell = HVCell()
        session.add(new_cell)
    session.commit()

# Вызов функции для добавления строк
add_empty_rows()
