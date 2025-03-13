# app/insert_dummy_data.py

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from createdb import HVCell

# Настройка подключения к базе данных
DATABASE_URL = "sqlite:///hv_cells.db"
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

# Добавление 32 новых пустых записей
for _ in range(64):
    new_cell = HVCell(
        cell_number='',  # Пустая строка для номера ячейки
        cell_name='',    # Пустая строка для наименования ячейки
        unit_id=0,       # По умолчанию, например, 0
        coil_register=0, # По умолчанию, например, 0
        mqtt_channel='', # Пустая строка для MQTT канала
        parameter_description='',  # Пустая строка для описания параметра
        state_name_true='',        # Пустая строка для состояния TRUE
        state_name_false='',       # Пустая строка для состояния FALSE
        display_state=False,       # Ложное состояние по умолчанию
        display_text=''            # Пустая строка для отображаемого текста
    )
    session.add(new_cell)

# Сохранение изменений в базе данных
session.commit()
print("32 пустые строки успешно добавлены в таблицу hv_cells.")
