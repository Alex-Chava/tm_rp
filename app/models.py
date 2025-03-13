# models.py

from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Boolean, DateTime

Base = declarative_base()

class HVCell(Base):
    __tablename__ = 'hv_cells'

    id = Column(Integer, primary_key=True)
    cell_number = Column(Integer)
    cell_name = Column(String(64))
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
