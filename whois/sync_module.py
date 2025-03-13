import time
import json
import struct
import requests  # << важно, чтобы импорт requests был
import paho.mqtt.client as mqtt
import serial

from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import HVCell

from collections import defaultdict

#####################################################
# НАСТРОЙКИ
#####################################################

DB_URL = "sqlite:///database.db"

SERIAL_PORT = "COM4"
SERIAL_BAUDRATE = 115200

MQTT_BROKER = "mqtt.umxx.ru"
MQTT_PORT = 1883
MQTT_TOPIC = "my/fast/topic"

TELEGRAM_TOKEN = "7276598964:AAG3mw9i7Ybt2PSyYBpwhElGU9F3IC7ZF2s"
TELEGRAM_CHAT_ID = "-1002349322419"  # суперчат ID

# «Шапка» MQTT-сообщения
DEVICE_NAME = "MyDeviceName"
DEVICE_SERIAL = "SN-2025-0001"
DEVICE_FW = "v1.0.0"
DEVICE_TYPE = 42  # Условно

# Период опроса (сек)
POLL_INTERVAL_SEC = 1.0

# Не чаще 1 раза в минуту обновляем value_date, если значение не менялось
MIN_DB_WRITE_INTERVAL_SEC = 60

# Порог безответного состояния
NO_RESPONSE_THRESHOLD_SEC = 5 * 60  # 5 минут

# Дополнительный «адрес» (заголовок) для Телеграм
TELEGRAM_HEADER = "ОФИС СИМ. Каширский проезд д.13. Луч А"

# Адрес (и порт) вашего Flask-приложения
# (Предполагаем, что оно запущено локально на порту 5555)
FLASK_HOST = "192.168.203.6"
FLASK_PORT = 5555


#####################################################
# ФУНКЦИЯ: получаем новый ключ из Flask
#####################################################
def get_new_key_from_web():
    """
    Обращаемся к маршруту /api/new_key,
    чтобы сгенерировать новый ключ в Flask
    и вернуть его сюда.
    """
    url = f"http://{FLASK_HOST}:{FLASK_PORT}/api/new_key"
    try:
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("key")
        else:
            print(f"[ERROR] /api/new_key вернул статус {resp.status_code}")
            return None
    except Exception as e:
        print(f"[ERROR] Не удалось получить новый ключ: {e}")
        return None


#####################################################
# СОЕДИНЕНИЕ С БД + ВЫБОРКА HVCell
#####################################################
engine = create_engine(DB_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)
session = SessionLocal()

# Берём только те ячейки, где side='1'
hv_cells_all = session.query(HVCell).filter(HVCell.side == "1").all()
session.close()

if not hv_cells_all:
    print("[INFO] Нет hv_cells с side=1, нечего опрашивать.")
    exit(0)

# Группируем по unit_id
devices_map = defaultdict(list)
for c in hv_cells_all:
    devices_map[c.unit_id].append(c)

# Преобразуем в структуру:
# { unit_id: {
#    'min_coil': X,
#    'hv_cells': [ { id, coil_register, display_state, state_name_true, state_name_false, parameter_description, ... }, ... ]
#   },
#   ...
# }
devices_info = {}

for unit_id, cells in devices_map.items():
    sorted_cells = sorted(cells, key=lambda x: x.coil_register)
    min_reg = sorted_cells[0].coil_register

    info = {
        "unit_id": unit_id,
        "min_coil": min_reg,
        "hv_cells": []
    }
    for sc in sorted_cells:
        info["hv_cells"].append({
            "id": sc.id,
            "coil_reg": sc.coil_register,
            "display_state": sc.display_state,  # bool
            "mqtt_channel": sc.mqtt_channel,
            "cell_name": sc.cell_name,
            "param_desc": sc.parameter_description,
            "state_true": sc.state_name_true,
            "state_false": sc.state_name_false
        })
    devices_info[unit_id] = info

print(f"[INFO] Обнаружено {len(devices_info)} устройств (unit_id), всего {len(hv_cells_all)} регистров.")

#####################################################
# ПОДГОТОВКА SERIAL / MQTT
#####################################################
try:
    ser = serial.Serial(
        port=SERIAL_PORT,
        baudrate=SERIAL_BAUDRATE,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.EIGHTBITS,
        timeout=0.1
    )
    print(f"[INFO] Открыл порт {SERIAL_PORT} @ {SERIAL_BAUDRATE}")
except Exception as e:
    print(f"[ERROR] Не удалось открыть {SERIAL_PORT}: {e}")
    exit(1)

mqtt_client = mqtt.Client()
try:
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    print(f"[INFO] MQTT connected to {MQTT_BROKER}:{MQTT_PORT}")
except Exception as e:
    print(f"[ERROR] MQTT connect error: {e}")
    exit(1)

#####################################################
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
#####################################################

def calculate_crc(data: bytes) -> int:
    """CRC16 Modbus (0xA001)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if (crc & 1):
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc

def create_modbus_request(unit_id: int, function_code: int, start_address: int, quantity: int) -> bytes:
    req = struct.pack('>BBHH', unit_id, function_code, start_address, quantity)
    crc_val = calculate_crc(req)
    req += struct.pack('<H', crc_val)
    return req

def send_modbus_request(ser: serial.Serial, request: bytes) -> bytes:
    ser.write(request)
    time.sleep(0.02)
    response = ser.read(256)
    return response

def parse_multiple_coils(response: bytes, quantity: int):
    """Парсим ответ при чтении coils (function=1). Возвращаем список [0/1,...] длиной quantity или None."""
    if len(response) < 5:
        return None
    crc_received = struct.unpack('<H', response[-2:])[0]
    crc_calc = calculate_crc(response[:-2])
    if crc_received != crc_calc:
        print("[MODBUS] CRC mismatch!")
        return None

    byte_count = response[2]
    data_bytes = response[3:3+byte_count]

    if len(data_bytes) < byte_count:
        return None

    coil_vals = []
    for i in range(quantity):
        byte_i = i // 8
        bit_i = i % 8
        val = (data_bytes[byte_i] >> bit_i) & 0x01
        coil_vals.append(val)
    return coil_vals

def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        r = requests.post(url, data=data)
        if r.status_code == 200:
            print(f"[TG] Sent: {text}")
        else:
            print(f"[TG] Error {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[TG] Exception: {e}")

def send_mqtt_message(payload: dict):
    try:
        msg = json.dumps(payload)
        mqtt_client.publish(MQTT_TOPIC, msg)
        print(f"[MQTT] Published to {MQTT_TOPIC}: {msg}")
    except Exception as e:
        print(f"[MQTT] Publish error: {e}")

# Помощники для работы с БД
def update_db_value(cell_id: int, new_val: bool):
    s = SessionLocal()
    c = s.get(HVCell, cell_id)
    if c:
        c.value = new_val
        c.value_date = datetime.now()
        s.commit()
    s.close()

def update_db_value_date(cell_id: int):
    s = SessionLocal()
    c = s.get(HVCell, cell_id)
    if c:
        c.value_date = datetime.now()
        s.commit()
    s.close()

#####################################################
# ПЕРЕМЕННЫЕ ДЛЯ ЛОГИКИ
#####################################################
previous_values = {}
last_db_write_time = {}
last_success_device = {}
alert_sent = {}

now_ = datetime.now()
s = SessionLocal()
for uid, dev_info in devices_info.items():
    alert_sent[uid] = False
    last_success_device[uid] = None
    for cell in dev_info["hv_cells"]:
        cid = cell["id"]
        hv_obj = s.get(HVCell, cid)
        if hv_obj and hv_obj.value is not None:
            previous_values[cid] = 1 if hv_obj.value else 0
        else:
            previous_values[cid] = None
        last_db_write_time[cid] = now_ - timedelta(minutes=60)
s.close()

print("[INFO] Инициализация previous_values из БД завершена.")

#####################################################
# ГЛАВНЫЙ ЦИКЛ
#####################################################
print("[INFO] Старт опроса...")

while True:
    changed_params = []
    telegram_msgs = []

    for uid, dev_info in devices_info.items():
        unit_id = dev_info["unit_id"]
        start_addr = dev_info["min_coil"]
        quantity = 16

        # print(f"[DEBUG] Опрос unit_id={unit_id}, coil_range=[{start_addr}..{start_addr + quantity - 1}]")

        req = create_modbus_request(unit_id, 1, start_addr, quantity)
        resp = send_modbus_request(ser, req)
        coil_vals = parse_multiple_coils(resp, quantity)
        if coil_vals is None:
            print(f"[DEBUG] Устройство unit_id={unit_id} НЕ ответило на запрос.")
            last_ok = last_success_device[uid]
            if last_ok is not None:
                delta_sec = (datetime.now() - last_ok).total_seconds()
                print(f"[DEBUG] Последний успешный опрос был {delta_sec:.1f} сек назад.")
                if delta_sec > NO_RESPONSE_THRESHOLD_SEC and not alert_sent[uid]:
                    msg = (f"Нет ответа от устройства unit_id={uid} >5мин "
                           f"(последний успешный опрос: {last_ok.strftime('%H:%M:%S')}).")
                    print(f"[DEBUG] Отправляем тревогу в телеграм: {msg}")
                    send_telegram_message(msg)
                    alert_sent[uid] = True
            else:
                print(f"[DEBUG] Первая попытка — не отправляем тревогу.")
            continue
        else:
            # print(f"[DEBUG] Успешно прочитали unit_id={unit_id}, coil_vals={coil_vals}")
            now_success = datetime.now()
            last_success_device[uid] = now_success
            if alert_sent[uid]:
                print(f"[INFO] Устройство unit_id={uid} восстановило связь.")
                alert_sent[uid] = False

            coil_map = {}
            for c in dev_info["hv_cells"]:
                coil_map[c["coil_reg"]] = c

            for i in range(quantity):
                curr_reg = start_addr + i
                val = coil_vals[i]
                cell_found = coil_map.get(curr_reg)
                if not cell_found:
                    continue

                cid = cell_found["id"]
                old_val = previous_values[cid]
                if old_val is not None and old_val != val:
                    previous_values[cid] = val
                    update_db_value(cid, bool(val))

                    is_normal = (val == cell_found["display_state"])
                    st_str = cell_found["state_true"] if is_normal else cell_found["state_false"]

                    changed_params.append({
                        "unit_id": uid,
                        "channel_name": cell_found["mqtt_channel"],
                        "val": bool(val),
                        "desc": cell_found["param_desc"] or cell_found["cell_name"] or f"Cell {cid}",
                        "state_str": st_str
                    })
                    param_name = cell_found["param_desc"] or cell_found["cell_name"] or f"Cell {cid}"
                    telegram_msgs.append(f"{param_name}: {st_str}")

                elif old_val is None:
                    # Первая инициализация
                    previous_values[cid] = val
                    update_db_value(cid, bool(val))
                    # Не отправляем в Телеграм, чтобы не spam'ить.
                else:
                    # Нет изменения. Раз в минуту обновляем value_date
                    last_upd = last_db_write_time[cid]
                    if (datetime.now() - last_upd).total_seconds() >= MIN_DB_WRITE_INTERVAL_SEC:
                        update_db_value_date(cid)
                        last_db_write_time[cid] = datetime.now()

    if changed_params:
        timestamp_str = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
        dev_dict = defaultdict(list)
        for ch in changed_params:
            dev_dict[ch["unit_id"]].append(ch)

        devices_list = []
        for uid2, items in dev_dict.items():
            tags = []
            for it in items:
                tags.append({"tag": it["channel_name"], "val": it["val"]})
            dev_payload = {
                "id": uid2,
                "type": DEVICE_TYPE,
                "serial": DEVICE_SERIAL,
                "vals": [{
                    "ts": timestamp_str,
                    "diff": 0,
                    "tags": tags
                }]
            }
            devices_list.append(dev_payload)

        final_payload = {
            "name": DEVICE_NAME,
            "serial": DEVICE_SERIAL,
            "fw": DEVICE_FW,
            "measures": [{
                "measure": "mDIn",
                "devices": devices_list
            }]
        }
        send_mqtt_message(final_payload)

        if telegram_msgs:
            # Формируем текст для Телеграм
            msg_text = f"{TELEGRAM_HEADER}\n\nИзменения:\n" + "\n".join(telegram_msgs)

            # *** ВАЖНО ***: Получаем новый ключ у Flask
            new_key = get_new_key_from_web()
            if new_key:
                # Формируем ссылку
                link = f"http://{FLASK_HOST}:{FLASK_PORT}/?key={new_key}"
                # Добавляем в конец сообщения
                msg_text += f'\n\n<a href="{link}">Подробнее на мнемосхеме</a>'

            send_telegram_message(msg_text)

    time.sleep(POLL_INTERVAL_SEC)
