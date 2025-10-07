import argparse
import time
import json
import struct
import requests
import paho.mqtt.client as mqtt
import serial

from datetime import datetime, timedelta
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from app.models import HVCell

from collections import defaultdict
from queue import Queue

#####################################################
# НАСТРОЙКИ
#####################################################
# ANSI escape-коды для цветов
COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[32m"
COLOR_BLUE = "\033[36m"

# Значения по умолчанию
DB_URL = "sqlite:///database.db"
SERIAL_BAUDRATE = 115200
MQTT_BROKER = "mqtt.umxx.ru"
MQTT_PORT = 1883
MQTT_TOPIC = "sp"
MQTT_QOS = 1  # Добавляем QoS для надежности
MQTT_KEEPALIVE = 60
TELEGRAM_TOKEN = "7276598964:AAG3mw9i7Ybt2PSyYBpwhElGU9F3IC7ZF2s"
TELEGRAM_CHAT_ID = "-4650871809"
DEVICE_NAME = "SIM-TM"
DEVICE_SERIAL = "300000000200"
DEVICE_FW = "v25.0.0"
DEVICE_TYPE = 42
POLL_INTERVAL_SEC = 1.0
MIN_DB_WRITE_INTERVAL_SEC = 60
NO_RESPONSE_THRESHOLD_SEC = 300
TELEGRAM_HEADER = "ТМ. Стенд"
FLASK_HOST = "127.0.0.1"
FLASK_HOST_KEY = "127.0.0.1"
FLASK_PORT = 5555

# Параметр DEVICE_SIDE будет передаваться через аргумент командной строки
DEVICE_SIDE = None

# SERIAL_PORT будет формироваться динамически на основе аргумента -s
SERIAL_PORT = None

# Глобальные переменные для MQTT
mqtt_client = None
is_mqtt_connected = False
mqtt_reconnect_attempts = 0
MAX_MQTT_RECONNECT_ATTEMPTS = 5
MQTT_RECONNECT_DELAY = 5  # секунды

# Очередь для неотправленных сообщений
mqtt_message_queue = Queue()

# Глобальные переменные для COM порта
serial_port = None
last_com_error_telegram_time = None
last_mqtt_error_telegram_time = None


#####################################################
# ФУНКЦИЯ: Загрузка конфигурации из JSON файла
#####################################################

def load_config_from_json(file_path):
    """
    Загружает конфигурацию из JSON файла и обновляет глобальные переменные.
    """
    try:
        with open(file_path, 'r') as f:
            config = json.load(f)

        global SERIAL_BAUDRATE, MQTT_BROKER, MQTT_PORT, MQTT_TOPIC, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
        global DEVICE_NAME, DEVICE_SERIAL, DEVICE_FW, DEVICE_TYPE, POLL_INTERVAL_SEC
        global MIN_DB_WRITE_INTERVAL_SEC, NO_RESPONSE_THRESHOLD_SEC, TELEGRAM_HEADER, FLASK_HOST, FLASK_PORT

        SERIAL_BAUDRATE = config.get("SERIAL_BAUDRATE", SERIAL_BAUDRATE)
        MQTT_BROKER = config.get("MQTT_BROKER", MQTT_BROKER)
        MQTT_PORT = config.get("MQTT_PORT", MQTT_PORT)
        MQTT_TOPIC = config.get("MQTT_TOPIC", MQTT_TOPIC)
        TELEGRAM_TOKEN = config.get("TELEGRAM_TOKEN", TELEGRAM_TOKEN)
        TELEGRAM_CHAT_ID = config.get("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)
        DEVICE_NAME = config.get("DEVICE_NAME", DEVICE_NAME)
        DEVICE_SERIAL = config.get("DEVICE_SERIAL", DEVICE_SERIAL)
        DEVICE_FW = config.get("DEVICE_FW", DEVICE_FW)
        DEVICE_TYPE = config.get("DEVICE_TYPE", DEVICE_TYPE)
        POLL_INTERVAL_SEC = config.get("POLL_INTERVAL_SEC", POLL_INTERVAL_SEC)
        MIN_DB_WRITE_INTERVAL_SEC = config.get("MIN_DB_WRITE_INTERVAL_SEC", MIN_DB_WRITE_INTERVAL_SEC)
        NO_RESPONSE_THRESHOLD_SEC = config.get("NO_RESPONSE_THRESHOLD_SEC", NO_RESPONSE_THRESHOLD_SEC)
        TELEGRAM_HEADER = config.get("TELEGRAM_HEADER", TELEGRAM_HEADER)
        FLASK_HOST = config.get("FLASK_HOST", FLASK_HOST)
        FLASK_PORT = config.get("FLASK_PORT", FLASK_PORT)

        # Выводим значения всех полей с комментариями, выровненными по столбцам
        print(f"[INFO]КОНФИГУРАЦИЯ ЗАГРУЖЕНА. Значения полей:")
        print(
            f"{COLOR_BLUE}{'SERIAL_BAUDRATE'.ljust(25)} {COLOR_GREEN}{str(config.get('SERIAL_BAUDRATE')).ljust(15)}{COLOR_RESET} (Скорость передачи данных для последовательного порта)")
        print(
            f"{COLOR_BLUE}{'MQTT_BROKER'.ljust(25)} {COLOR_GREEN}{str(config.get('MQTT_BROKER')).ljust(15)}{COLOR_RESET} (Адрес MQTT-брокера)")
        print(
            f"{COLOR_BLUE}{'MQTT_PORT'.ljust(25)} {COLOR_GREEN}{str(config.get('MQTT_PORT')).ljust(15)}{COLOR_RESET} (Порт MQTT-брокера)")
        print(
            f"{COLOR_BLUE}{'MQTT_TOPIC'.ljust(25)} {COLOR_GREEN}{str(config.get('MQTT_TOPIC')).ljust(15)}{COLOR_RESET} (Топик MQTT для публикации сообщений)")
        print(
            f"{COLOR_BLUE}{'TELEGRAM_TOKEN'.ljust(25)} {COLOR_GREEN}{str(config.get('TELEGRAM_TOKEN')).ljust(15)}{COLOR_RESET} (Токен для доступа к Telegram Bot API)")
        print(
            f"{COLOR_BLUE}{'TELEGRAM_CHAT_ID'.ljust(25)} {COLOR_GREEN}{str(config.get('TELEGRAM_CHAT_ID')).ljust(15)}{COLOR_RESET} (ID чата в Telegram для отправки сообщений)")
        print(
            f"{COLOR_BLUE}{'DEVICE_NAME'.ljust(25)} {COLOR_GREEN}{str(config.get('DEVICE_NAME')).ljust(15)}{COLOR_RESET} (Название устройства)")
        print(
            f"{COLOR_BLUE}{'DEVICE_SERIAL'.ljust(25)} {COLOR_GREEN}{str(config.get('DEVICE_SERIAL')).ljust(15)}{COLOR_RESET} (Серийный номер устройства)")
        print(
            f"{COLOR_BLUE}{'DEVICE_FW'.ljust(25)} {COLOR_GREEN}{str(config.get('DEVICE_FW')).ljust(15)}{COLOR_RESET} (Версия прошивки устройства)")
        print(
            f"{COLOR_BLUE}{'DEVICE_TYPE'.ljust(25)} {COLOR_GREEN}{str(config.get('DEVICE_TYPE')).ljust(15)}{COLOR_RESET} (Тип устройства)")
        print(
            f"{COLOR_BLUE}{'POLL_INTERVAL_SEC'.ljust(25)} {COLOR_GREEN}{str(config.get('POLL_INTERVAL_SEC')).ljust(15)}{COLOR_RESET} (Интервал опроса устройств в секундах)")
        print(
            f"{COLOR_BLUE}{'MIN_DB_WRITE_INTERVAL_SEC'.ljust(25)} {COLOR_GREEN}{str(config.get('MIN_DB_WRITE_INTERVAL_SEC')).ljust(15)}{COLOR_RESET} (Минимальный интервал записи в базу данных в секундах)")
        print(
            f"{COLOR_BLUE}{'NO_RESPONSE_THRESHOLD_SEC'.ljust(25)} {COLOR_GREEN}{str(config.get('NO_RESPONSE_THRESHOLD_SEC')).ljust(15)}{COLOR_RESET} (Порог времени без ответа от устройства в секундах)")
        print(
            f"{COLOR_BLUE}{'TELEGRAM_HEADER'.ljust(25)} {COLOR_GREEN}{str(config.get('TELEGRAM_HEADER')).ljust(15)}{COLOR_RESET} (Заголовок для сообщений в Telegram)")
        print(
            f"{COLOR_BLUE}{'FLASK_HOST'.ljust(25)} {COLOR_GREEN}{str(config.get('FLASK_HOST')).ljust(15)}{COLOR_RESET} (Адрес Flask-приложения)")
        print(
            f"{COLOR_BLUE}{'FLASK_PORT'.ljust(25)} {COLOR_GREEN}{str(config.get('FLASK_PORT')).ljust(15)}{COLOR_RESET} (Порт Flask-приложения)")
    except Exception as e:
        print(f"[ERROR] Ошибка при загрузке конфигурации из JSON файла: {e}")


#####################################################
# Обработка аргументов командной строки
#####################################################

def parse_arguments():
    """
    Парсит аргументы командной строки.
    """
    parser = argparse.ArgumentParser(description="Запуск мониторинга устройств.")
    parser.add_argument(
        "-s",  # Короткое имя аргумента
        type=int,  # Ожидаем целое число
        required=True,
        help="Номер устройства для формирования SERIAL_PORT (например, '1' для /dev/ttyUSB3, так как 4 - 1 = 3)."
    )
    return parser.parse_args()


# Парсим аргументы командной строки
args = parse_arguments()
DEVICE_SIDE = str(args.s)  # Устанавливаем значение DEVICE_SIDE из аргумента

# Формируем SERIAL_PORT на основе аргумента -s: 4 - s
SERIAL_PORT = f"/dev/ttyUSB{4 - args.s}"
print(f"[INFO] SERIAL_PORT установлен в {SERIAL_PORT}")

# Загрузка конфигурации из JSON файла
load_config_from_json("config.json")


#####################################################
# ФУНКЦИЯ: получаем новый ключ из Flask
#####################################################
def get_new_key_from_web():
    """
    Обращаемся к маршруту /api/new_key,
    чтобы сгенерировать новый ключ в Flask
    и вернуть его сюда.
    """
    url = f"http://{FLASK_HOST_KEY}:{FLASK_PORT}/api/new_key"
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
# ФУНКЦИИ ДЛЯ MQTT (УЛУЧШЕННЫЕ)
#####################################################

def get_mqtt_topic():
    """
    Формирует MQTT топик в формате: sp/200000891619/out/meter/data/post
    где sp - из MQTT_TOPIC, 200000891619 - из DEVICE_SERIAL
    """
    return f"{MQTT_TOPIC}/{DEVICE_SERIAL}/out/meter/data/post"


def on_mqtt_connect(client, userdata, flags, rc):
    """Callback при подключении к MQTT брокеру"""
    global is_mqtt_connected, mqtt_reconnect_attempts
    if rc == 0:
        print(f"[MQTT] Успешно подключен к {MQTT_BROKER}:{MQTT_PORT}")
        is_mqtt_connected = True
        mqtt_reconnect_attempts = 0

        # При подключении пытаемся отправить все сообщения из очереди
        process_mqtt_queue()
    else:
        print(f"[MQTT] Ошибка подключения, код: {rc}")
        is_mqtt_connected = False


def on_mqtt_disconnect(client, userdata, rc):
    """Callback при отключении от MQTT брокера"""
    global is_mqtt_connected
    print(f"[MQTT] Отключен от брокера, код: {rc}")
    is_mqtt_connected = False


def on_mqtt_publish(client, userdata, mid):
    """Callback при успешной публикации сообщения"""
    print(f"[MQTT] Сообщение {mid} доставлено")


def initialize_mqtt_client():
    """Инициализирует и настраивает MQTT клиент"""
    global mqtt_client
    try:
        client = mqtt.Client()
        client.on_connect = on_mqtt_connect
        client.on_disconnect = on_mqtt_disconnect
        client.on_publish = on_mqtt_publish

        # Настройка таймаутов и повторных подключений
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        return client
    except Exception as e:
        print(f"[ERROR] Ошибка инициализации MQTT клиента: {e}")
        return None


def try_connect_mqtt():
    """
    Пытается подключиться к MQTT с обработкой ошибок и повторными попытками.
    Возвращает (mqtt_client, success_flag)
    """
    global mqtt_client, is_mqtt_connected, mqtt_reconnect_attempts

    if mqtt_client is None:
        mqtt_client = initialize_mqtt_client()
        if mqtt_client is None:
            return (None, False)

    try:
        print(f"[MQTT] Подключение к {MQTT_BROKER}:{MQTT_PORT}...")
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, MQTT_KEEPALIVE)
        mqtt_client.loop_start()  # Запускаем фоновый цикл для обработки сообщений
        time.sleep(1)  # Даем время для установления соединения

        if is_mqtt_connected:
            print(f"[MQTT] Успешно подключен к {MQTT_BROKER}:{MQTT_PORT}")
            mqtt_reconnect_attempts = 0
            return (mqtt_client, True)
        else:
            mqtt_reconnect_attempts += 1
            print(f"[MQTT] Попытка подключения {mqtt_reconnect_attempts} не удалась")
            return (mqtt_client, False)

    except Exception as e:
        mqtt_reconnect_attempts += 1
        print(f"[ERROR] MQTT connect error: {e}")
        return (mqtt_client, False)


def send_mqtt_message(payload: dict) -> bool:
    """
    Отправляет сообщение в MQTT с проверкой подключения и обработкой ошибок.
    Возвращает True если успешно, False если ошибка.
    """
    global mqtt_client, is_mqtt_connected

    print(
        f"[DEBUG] send_mqtt_message вызвана, mqtt_client={mqtt_client is not None}, is_mqtt_connected={is_mqtt_connected}")

    if mqtt_client is None:
        print("[ERROR] MQTT client not initialized")
        return False

    if not is_mqtt_connected:
        print("[ERROR] MQTT client not connected")
        return False

    try:
        msg = json.dumps(payload)
        topic = get_mqtt_topic()
        print(f"[DEBUG] Отправка MQTT сообщения в топик: {topic}")
        print(f"[DEBUG] Сообщение: {msg}")

        result = mqtt_client.publish(topic, msg, qos=MQTT_QOS)

        # Ждем подтверждения публикации для QoS > 0
        if MQTT_QOS > 0:
            result.wait_for_publish(timeout=2.0)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print(f"[MQTT] Published to {topic}: {msg}")
            return True
        else:
            print(f"[MQTT] Publish failed with code: {result.rc}")
            # Если публикация не удалась, помечаем соединение как разорванное
            is_mqtt_connected = False
            return False

    except Exception as e:
        print(f"[MQTT] Publish error: {e}")
        is_mqtt_connected = False
        return False

def queue_mqtt_message(payload: dict):
    """
    Добавляет сообщение в очередь для отправки.
    Если MQTT подключен - отправляет сразу.
    Если нет - сохраняет в очередь.
    """
    global mqtt_message_queue

    print(f"[DEBUG] queue_mqtt_message вызвана, is_mqtt_connected={is_mqtt_connected}")

    # Если подключены, пытаемся отправить сразу
    if is_mqtt_connected:
        print("[DEBUG] MQTT подключен, пытаемся отправить сразу")
        if send_mqtt_message(payload):
            return True
        else:
            # Если отправка не удалась, добавляем в очередь
            mqtt_message_queue.put(payload)
            print(f"[MQTT] Сообщение добавлено в очередь (размер очереди: {mqtt_message_queue.qsize()})")
            return False
    else:
        # Если не подключены, просто добавляем в очередь
        mqtt_message_queue.put(payload)
        print(f"[MQTT] Сообщение добавлено в очередь (размер очереди: {mqtt_message_queue.qsize()})")
        return False

def process_mqtt_queue():
    """
    Обрабатывает очередь сообщений, отправляя их если MQTT подключен.
    Возвращает количество отправленных сообщений.
    """
    global mqtt_message_queue, is_mqtt_connected

    if not is_mqtt_connected or mqtt_message_queue.empty():
        return 0

    sent_count = 0
    temp_queue = Queue()

    # Обрабатываем все сообщения в очереди
    while not mqtt_message_queue.empty():
        payload = mqtt_message_queue.get()

        if send_mqtt_message(payload):
            sent_count += 1
            print(f"[MQTT] Отправлено сообщение из очереди ({sent_count})")
        else:
            # Если отправка не удалась, возвращаем сообщение в очередь
            temp_queue.put(payload)

    # Возвращаем неотправленные сообщения обратно в основную очередь
    while not temp_queue.empty():
        mqtt_message_queue.put(temp_queue.get())

    if sent_count > 0:
        print(f"[MQTT] Успешно отправлено {sent_count} сообщений из очереди")

    return sent_count


def check_and_reconnect_mqtt_if_needed():
    """
    Проверяет, есть ли неотправленные сообщения и пытается переподключиться если нужно.
    Возвращает True если переподключение успешно или не требуется.
    """
    global is_mqtt_connected, mqtt_message_queue

    # Если нет неотправленных сообщений, не переподключаемся
    if mqtt_message_queue.empty():
        return True

    # Если есть неотправленные сообщения и нет подключения, пытаемся восстановить
    if not is_mqtt_connected:
        print(f"[MQTT] Есть {mqtt_message_queue.qsize()} неотправленных сообщений, пытаемся восстановить соединение...")
        mqtt_client, ok = try_connect_mqtt()
        if ok:
            print("[MQTT] Соединение восстановлено для отправки сообщений из очереди")
            return True
        else:
            print("[MQTT] Не удалось восстановить соединение")
            return False

    return True


def send_initial_state_to_mqtt():
    """
    Отправляет полное состояние всех контролируемых устройств из базы данных при старте программы.
    """
    print("[INFO] Отправка начального состояния всех устройств...")

    s = SessionLocal()
    try:
        # Получаем все ячейки для текущей стороны
        hv_cells = s.query(HVCell).filter(HVCell.side == DEVICE_SIDE).all()

        if not hv_cells:
            print("[INFO] Нет устройств для отправки начального состояния")
            return

        # Группируем по unit_id
        devices_state = defaultdict(list)

        for cell in hv_cells:
            if cell.value is not None:
                devices_state[cell.unit_id].append({
                    "tag": cell.mqtt_channel,  # Ключ "tag" вместо "channel_name"
                    "val": bool(cell.value)
                })

        # Формируем payload для каждого устройства
        devices_list = []
        timestamp_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")

        for unit_id, tags in devices_state.items():
            if tags:  # Если есть данные для этого устройства
                dev_payload = {
                    "id": unit_id,
                    "type": DEVICE_TYPE,
                    "serial": unit_id,
                    "vals": [{
                        "ts": timestamp_str,
                        "diff": 0,
                        "tags": tags
                    }]
                }
                devices_list.append(dev_payload)

        if devices_list:
            final_payload = {
                "name": DEVICE_NAME,
                "serial": DEVICE_SERIAL,
                "fw": DEVICE_FW,
                "measures": [{
                    "measure": "mDIn",
                    "devices": devices_list
                }]
            }

            # Отправляем начальное состояние
            success = queue_mqtt_message(final_payload)
            if success:
                print(f"[INFO] Отправлено начальное состояние для {len(devices_list)} устройств")
            else:
                print(f"[INFO] Начальное состояние добавлено в очередь для {len(devices_list)} устройств")
        else:
            print("[INFO] Нет данных для отправки начального состояния")

    except Exception as e:
        print(f"[ERROR] Ошибка при отправке начального состояния: {e}")
    finally:
        s.close()
#####################################################
# СОЕДИНЕНИЕ С БД + ВЫБОРКА HVCell
#####################################################
engine = create_engine(DB_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)
session = SessionLocal()

# Берём только те ячейки, где side=DEVICE_SIDE
hv_cells_all = session.query(HVCell).filter(HVCell.side == DEVICE_SIDE).all()
session.close()

if not hv_cells_all:
    print(f"[INFO] Нет hv_cells с side={DEVICE_SIDE}, нечего опрашивать.")
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
            "cell_number": sc.cell_number,  # << добавили
            "cell_name": sc.cell_name,
            "param_desc": sc.parameter_description,
            "state_true": sc.state_name_true,
            "state_false": sc.state_name_false
        })
    devices_info[unit_id] = info

print(f"[INFO] Обнаружено {len(devices_info)} устройств (unit_id), всего {len(hv_cells_all)} регистров.")


#####################################################
# Остальной код программы...
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
    # Если есть эхо, читаем его:
    echo = ser.read(len(request))  # игнорируем
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
    data_bytes = response[3:3 + byte_count]

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


def send_telegram_error_once_in_period(error_text, last_send_time, period_sec=3600):
    """
    Отправляет error_text в Телеграм, если с момента last_send_time
    прошло не меньше period_sec. Возвращает новое значение last_send_time.
    """
    now = datetime.now()
    if last_send_time is None or (now - last_send_time).total_seconds() >= period_sec:
        send_telegram_message(error_text)
        return now
    return last_send_time  # если не отправили, возвращаем старое время


def open_serial_port_with_retries():
    """
    Пытается открыть COM-порт в цикле.
    Если не получилось, шлёт Телеграм раз в час,
    ждёт минуту, снова пробует.
    Возвращает объект serial.Serial при успехе.
    """
    global last_com_error_telegram_time

    while True:
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
            return ser
        except Exception as e:
            print(f"[ERROR] Не удалось открыть {SERIAL_PORT}: {e}")
            # Шлём сообщение раз в час
            last_com_error_telegram_time = send_telegram_error_once_in_period(
                f"Ошибка открытия COM-порта {SERIAL_PORT}: {e}",
                last_com_error_telegram_time,
                period_sec=3600
            )
            # Ждём минуту и повторяем
            time.sleep(60)


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
# ПОДГОТОВКА SERIAL / MQTT
#####################################################

print("[INFO] Инициализация COM-порта...")
serial_port = open_serial_port_with_retries()  # бесконечно пытается открыть COM

print("[INFO] Инициализация MQTT...")
mqtt_client, is_mqtt_connected = try_connect_mqtt()
if not is_mqtt_connected:
    print("[INFO] MQTT не подключен, но программа продолжит работу. Сообщения будут накапливаться в очереди.")

# Отправляем начальное состояние всех устройств
send_initial_state_to_mqtt()


#####################################################
# ПОЗДОРОВАЙСЯ
#####################################################

def send_initial_telegram_message():
    """Отправляет приветственное сообщение при запуске модуля."""
    s = SessionLocal()
    max_date = s.query(func.max(HVCell.value_date)).scalar()
    s.close()

    if max_date is None:
        date_str = "неизвестно"
    else:
        date_str = max_date.strftime("%d.%m.%Y %H:%M:%S")
    new_key = get_new_key_from_web()
    msg_text = (
        f"{TELEGRAM_HEADER}\n\n"
        "Запуск мониторинга после отключения.\n"
        f"Крайний успешный опрос - {date_str}\n\n"
        f'<a href="http://{FLASK_HOST}:{FLASK_PORT}/?key={new_key}">Мнемосхема</a>'
    )

    send_telegram_message(msg_text)


send_initial_telegram_message()

#####################################################
# ГЛАВНЫЙ ЦИКЛ
#####################################################
print("[INFO] Старт опроса...")

last_mqtt_queue_check = datetime.now()
MQTT_QUEUE_CHECK_INTERVAL = 60  # Проверять очередь раз в минуту

while True:
    current_time = datetime.now()

    # 1) Периодически проверяем очередь MQTT (раз в минуту)
    if (current_time - last_mqtt_queue_check).total_seconds() >= MQTT_QUEUE_CHECK_INTERVAL:
        if not mqtt_message_queue.empty():
            print(f"[MQTT] В очереди {mqtt_message_queue.qsize()} сообщений, проверяем соединение...")
            check_and_reconnect_mqtt_if_needed()
        last_mqtt_queue_check = current_time

    changed_params = []
    telegram_msgs = []

    # 2) Опрос устройств
    for uid, dev_info in devices_info.items():
        unit_id = dev_info["unit_id"]
        start_addr = dev_info["min_coil"]
        quantity = 16

        # Формируем запрос
        req = create_modbus_request(unit_id, 1, start_addr, quantity)

        # Пытаемся отправить/прочитать
        try:
            resp = send_modbus_request(serial_port, req)
        except Exception as e:
            print(f"[ERROR] Ошибка чтения/записи COM: {e}")
            # Закрываем и переоткрываем port
            try:
                serial_port.close()
            except:
                pass
            serial_port = open_serial_port_with_retries()
            # Пропустим цикл, чтобы не продолжать с нулевым resp
            continue

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
                        "cell_number": cell_found["cell_number"],
                        "cell_name": cell_found["cell_name"],
                        "channel_name": cell_found["mqtt_channel"],
                        "val": bool(val),
                        "desc": cell_found["param_desc"] or cell_found["cell_name"] or f"Cell {cid}",
                        "state_str": st_str
                    })

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

    # 3) Если есть изменения, отправляем данные
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
                "serial": uid2,
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

        # Используем очередь для отправки MQTT сообщений
        mqtt_success = queue_mqtt_message(final_payload)
        if not mqtt_success and not is_mqtt_connected:
            print(f"[WARN] MQTT не подключен, сообщение добавлено в очередь ({mqtt_message_queue.qsize()} в очереди)")

        # Группируем изменения по ячейке
        changes_by_cell = defaultdict(list)

        for ch in changed_params:
            # Ключ - строка, которая содержит номер и название ячейки
            cell_label = f"Ячейка №{ch['cell_number']} {ch['cell_name']}"
            param_name = ch["desc"]  # Например "Выключатель включен"
            state_str = ch["state_str"]  # Например "НЕТ"
            # Запишем
            changes_by_cell[cell_label].append((param_name, state_str))

        # Теперь собираем строки:
        telegram_msgs = []
        for cell_label, items in changes_by_cell.items():
            # Сначала - заголовок ячейки
            telegram_msgs.append(f"\n\n==========> {cell_label}")
            # Потом - строки "Параметр: Состояние"
            for (param_name, state_str) in items:
                telegram_msgs.append(f"{param_name}: {state_str}")

        # Собираем всё в один msg_text
        msg_text = f"{TELEGRAM_HEADER}\n\nИзменения:\n" + "\n".join(telegram_msgs)

        # Получаем новый ключ у Flask
        new_key = get_new_key_from_web()
        if new_key:
            # Формируем ссылку
            link = f"http://{FLASK_HOST}:{FLASK_PORT}/?key={new_key}"
            # Добавляем в конец сообщения
            msg_text += f'\n\n<a href="{link}">Подробнее на мнемосхеме</a>'

        send_telegram_message(msg_text)

    time.sleep(POLL_INTERVAL_SEC)