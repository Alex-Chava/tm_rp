# models.py

from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float
from datetime import datetime


Base = declarative_base()

class HVCell(Base):
    __tablename__ = 'hv_cells'

    id = Column(Integer, primary_key=True)
    cell_number = Column(Integer)
    cell_name = Column(String(64))
    cell_type = Column(String(16))
    unit_id = Column(Integer)
    coil_register = Column(Integer)
    mqtt_channel = Column(String(64))
    parameter_description = Column(String(128))
    state_name_true = Column(String(64))
    state_name_false = Column(String(64))
    display_state = Column(Boolean)
    display_text = Column(String(128))
    value = Column(Boolean)
    value_date = Column(DateTime)
    com = Column(String(64))
    side = Column(String(64))

class AskueData(Base):
    __tablename__ = 'askue_data'

    id = Column(Integer, primary_key=True)

    meter_serial = Column(String(64), nullable=False)

    cell_number = Column(Integer)  # новая колонка
    ktt = Column(Float, default=1.0)  # новая колонка
    ktn = Column(Float, default=1.0)  # новая колонка

    # Напряжение
    UA = Column(Float)
    UB = Column(Float)
    UC = Column(Float)

    # Ток
    IA = Column(Float)
    IB = Column(Float)
    IC = Column(Float)

    # Мощность активная (PS, PA, PB, PC) – предполагаю S=сумма, A/B/C=по фазам
    PS = Column(Float)
    PA = Column(Float)
    PB = Column(Float)
    PC = Column(Float)

    # Мощность реактивная (QS, QA, QB, QC)
    QS = Column(Float)
    QA = Column(Float)
    QB = Column(Float)
    QC = Column(Float)

    # Углы (AngAB, AngBC, AngAC)
    AngAB = Column(Float)
    AngBC = Column(Float)
    AngAC = Column(Float)

    # Коэффициент мощности (kPS, kPA, kPB, kPC)
    kPS = Column(Float)
    kPA = Column(Float)
    kPB = Column(Float)
    kPC = Column(Float)

    # Частота
    Freq = Column(Float)

    last_update = Column(DateTime, default=datetime.now)

    def __init__(self, meter_serial):
        self.meter_serial = meter_serial
        self.last_update = datetime.now()