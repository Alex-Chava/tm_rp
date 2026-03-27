import argparse
import time
import json
import struct
import requests
import paho.mqtt.client as mqtt
import serial
import threading
from queue import Queue, Full, Empty


from datetime import datetime, timedelta
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from app.models import HVCell, AskueData

from collections import defaultdict

#####################################################
# НАСТРОЙКИ
#####################################################
# ANSI escape-коды для цветов
COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[32m"
COLOR_BLUE = "\033[36m"

# Значения по умолчанию
DB_URL = None
SERIAL_BAUDRATE = 115200
MQTT_BROKER = "mqtt.umxx.ru"
MQTT_PORT = 1883
MQTT_TOPIC = "sp"
MQTT_QOS = 1  # Добавляем QoS для надежности
MQTT_KEEPALIVE = 60
TELEGRAM_TOKEN = "7276598964:AAG3mw9i7Ybt2PSyYBpwhElGU9F3IC7ZF2s"
TELEGRAM_CHAT_ID = "-4650871809"
TELEGRAM_URL = "https://api.telegram.org"
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

# === WEB KEY cache (обновляем 1 раз в сутки) ===
current_web_key = None
current_web_key_date = None  # date()

# Очередь для Telegram (чтобы не блокировать основной цикл)
TG_QUEUE_MAX = 2000
tg_queue = Queue(maxsize=TG_QUEUE_MAX)

tg_worker_thread = None

# очередь для mqtt
MQTT_QUEUE_MAX = 5000  # сколько сообщений держим максимум
mqtt_message_queue = Queue(maxsize=MQTT_QUEUE_MAX)

mqtt_loop_started = False

FULL_STATE_ON_LINK_CHANGE_COOLDOWN_SEC = 30
last_full_state_link_change_send = None  # datetime


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

        global SERIAL_BAUDRATE, MQTT_BROKER, MQTT_PORT, MQTT_TOPIC, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_URL
        global DEVICE_NAME, DEVICE_SERIAL, DEVICE_FW, DEVICE_TYPE, POLL_INTERVAL_SEC
        global MIN_DB_WRITE_INTERVAL_SEC, NO_RESPONSE_THRESHOLD_SEC, TELEGRAM_HEADER, FLASK_HOST, FLASK_PORT
        global FULL_STATE_INTERVAL_SEC
        global DB_URL

        SERIAL_BAUDRATE = config.get("SERIAL_BAUDRATE", SERIAL_BAUDRATE)
        MQTT_BROKER = config.get("MQTT_BROKER", MQTT_BROKER)
        MQTT_PORT = config.get("MQTT_PORT", MQTT_PORT)
        MQTT_TOPIC = config.get("MQTT_TOPIC", MQTT_TOPIC)
        TELEGRAM_TOKEN = config.get("TELEGRAM_TOKEN", TELEGRAM_TOKEN)
        TELEGRAM_CHAT_ID = config.get("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)
        TELEGRAM_URL = config.get("TELEGRAM_URL", TELEGRAM_URL)
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
        FULL_STATE_INTERVAL_SEC = config.get("FULL_STATE_INTERVAL_SEC", 3600)
        DB_URL = f"sqlite:///{DEVICE_NAME}.db"

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
        print(
            f"{COLOR_BLUE}{'FULL_STATE_PUBLISH_SEC'.ljust(25)} {COLOR_GREEN}{str(config.get('FULL_STATE_PUBLISH_SEC')).ljust(15)}{COLOR_RESET} (Интервал отправки полного состояния в MQTT, сек)")
        print(f"[INFO] DB_URL установлен в {DB_URL}")

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

def mqtt_queue_put(payload: dict) -> bool:
    """
    Положить сообщение в MQTT-очередь.
    Если очередь заполнена — выкидываем самое старое и кладём новое.
    Возвращает True если положили.
    """
    try:
        mqtt_message_queue.put_nowait(payload)
        return True
    except Full:
        try:
            _ = mqtt_message_queue.get_nowait()  # выкинули самое старое
        except Empty:
            pass
        try:
            mqtt_message_queue.put_nowait(payload)
            return True
        except Full:
            return False

def send_full_state_on_link_change(is_event: bool):
    """
    Отправляет полный снимок при изменении связи (отвал/восстановление),
    но не чаще cooldown.
    """
    global last_full_state_link_change_send
    now = datetime.now()

    if last_full_state_link_change_send is not None:
        if (now - last_full_state_link_change_send).total_seconds() < FULL_STATE_ON_LINK_CHANGE_COOLDOWN_SEC:
            print("[INFO] full_state on link-change skipped (cooldown)")
            return False

    send_full_state_to_mqtt(is_event=is_event)
    # (по желанию) сразу же догоняем ASKUE
    send_askue_snapshot_to_mqtt()

    last_full_state_link_change_send = now
    return True


#####################################################
# ФУНКЦИЯ: получаем новый ключ из Flask
#####################################################
def get_new_key_from_web():
    """
    Обращаемся к маршруту /api/new_key,
    чтобы сгенерировать новый ключ в Flask
    и вернуть его сюда.
    """
    url = f"http://{FLASK_HOST_KEY}:{FLASK_PORT}/api/web_key"
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

def get_web_key_daily():
    """
    Возвращает текущий ключ для WEB.
    Обновляет ключ только если наступил новый день (по локальному времени).
    """
    global current_web_key, current_web_key_date

    today = datetime.now().date()

    # Если ключ ещё не получали — получаем
    if current_web_key is None or current_web_key_date is None:
        k = get_new_key_from_web()
        if k:
            current_web_key = k
            current_web_key_date = today
        return current_web_key

    # Если день сменился — обновляем
    if today != current_web_key_date:
        k = get_new_key_from_web()
        if k:
            current_web_key = k
            current_web_key_date = today

    return current_web_key


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
    global mqtt_client, is_mqtt_connected, mqtt_reconnect_attempts, mqtt_loop_started

    if mqtt_client is None:
        mqtt_client = initialize_mqtt_client()
        if mqtt_client is None:
            return (None, False)

    try:
        print(f"[MQTT] Подключение к {MQTT_BROKER}:{MQTT_PORT}...")
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, MQTT_KEEPALIVE)

        if not mqtt_loop_started:
            mqtt_client.loop_start()
            mqtt_loop_started = True

        time.sleep(1)

        if is_mqtt_connected:
            mqtt_reconnect_attempts = 0
            return (mqtt_client, True)
        else:
            mqtt_reconnect_attempts += 1
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

def queue_mqtt_message(payload: dict) -> bool:
    """
    Всегда стараемся НЕ терять сообщение:
    - если MQTT подключён -> пробуем отправить
    - если не получилось / не подключён -> кладём в очередь (с лимитом)
    """
    global is_mqtt_connected

    if is_mqtt_connected:
        if send_mqtt_message(payload):
            return True

    ok = mqtt_queue_put(payload)
    if ok:
        print(f"[MQTT] Сообщение в очереди (size={mqtt_message_queue.qsize()}/{MQTT_QUEUE_MAX})")
    else:
        print("[MQTT][ERROR] Очередь переполнена и не удалось положить сообщение (даже после дропа)")
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
        mqtt_queue_put(temp_queue.get())

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
    ts ставим НЕ общий на пакет, а по каждому unit_id: MAX(value_date) по тегам устройства.
    """
    print("[INFO] Отправка начального состояния всех устройств...")

    s = SessionLocal()
    try:
        hv_cells = s.query(HVCell).filter(HVCell.side == DEVICE_SIDE).all()

        if not hv_cells:
            print("[INFO] Нет устройств для отправки начального состояния")
            return

        devices_state = defaultdict(list)  # unit_id -> tags[]
        devices_ts = {}                    # unit_id -> max(value_date)

        for cell in hv_cells:
            # собираем tags
            if cell.value is not None:
                devices_state[cell.unit_id].append({
                    "tag": cell.mqtt_channel,
                    "val": bool(cell.value)
                })

            # max(value_date) по устройству
            if cell.value_date is not None:
                prev = devices_ts.get(cell.unit_id)
                if prev is None or cell.value_date > prev:
                    devices_ts[cell.unit_id] = cell.value_date

        devices_list = []

        for unit_id, tags in devices_state.items():
            if not tags:
                continue

            dt = devices_ts.get(unit_id)
            if dt is not None:
                try:
                    ts = dt.astimezone().isoformat(timespec="seconds")
                except Exception:
                    ts = datetime.now().astimezone().isoformat(timespec="seconds")
            else:
                ts = datetime.now().astimezone().isoformat(timespec="seconds")

            devices_list.append({
                "id": unit_id,
                "type": DEVICE_TYPE,
                "serial": f"{DEVICE_SIDE}_{unit_id}",
                "vals": [{
                    "ts": ts,
                    "diff": 0,
                    "tags": tags
                }]
            })

        if not devices_list:
            print("[INFO] Нет данных для отправки начального состояния")
            return

        final_payload = {
            "name": DEVICE_NAME,
            "serial": DEVICE_SERIAL,
            "fw": DEVICE_FW,
            "is_event": True,  # как было у тебя
            "measures": [{
                "measure": "mDIn",
                "devices": devices_list
            }]
        }

        success = queue_mqtt_message(final_payload)
        if success:
            print(f"[INFO] Отправлено начальное состояние для {len(devices_list)} устройств")
        else:
            print(f"[INFO] Начальное состояние добавлено в очередь для {len(devices_list)} устройств")

    except Exception as e:
        print(f"[ERROR] Ошибка при отправке начального состояния: {e}")
    finally:
        s.close()


def send_full_state_to_mqtt(is_event: bool = False):
    print("[INFO] Отправка полного состояния всех устройств...")

    s = SessionLocal()
    try:
        hv_cells = s.query(HVCell).filter(HVCell.side == DEVICE_SIDE).all()
        if not hv_cells:
            print("[INFO] Нет устройств для отправки полного состояния")
            return

        devices_state = defaultdict(list)
        devices_ts = {}  # unit_id -> datetime (max value_date)

        for cell in hv_cells:
            if cell.value is not None:
                devices_state[cell.unit_id].append({
                    "tag": cell.mqtt_channel,
                    "val": bool(cell.value)
                })

            # собираем max(value_date) на устройство
            if cell.value_date is not None:
                prev = devices_ts.get(cell.unit_id)
                if prev is None or cell.value_date > prev:
                    devices_ts[cell.unit_id] = cell.value_date

        devices_list = []

        for unit_id, tags in devices_state.items():
            if not tags:
                continue

            # ts устройства = max(value_date) по его тегам, иначе fallback "сейчас"
            dt = devices_ts.get(unit_id)
            if dt is not None:
                try:
                    ts = dt.astimezone().isoformat(timespec="seconds")
                except Exception:
                    ts = datetime.now().astimezone().isoformat(timespec="seconds")
            else:
                ts = datetime.now().astimezone().isoformat(timespec="seconds")

            dev_payload = {
                "id": unit_id,
                "type": DEVICE_TYPE,
                "serial": f"{DEVICE_SIDE}_{unit_id}",
                "vals": [{
                    "ts": ts,
                    "diff": 0,
                    "tags": tags
                }]
            }
            devices_list.append(dev_payload)

        if not devices_list:
            print("[INFO] Нет данных для отправки полного состояния")
            return

        final_payload = {
            "name": DEVICE_NAME,
            "serial": DEVICE_SERIAL,
            "fw": DEVICE_FW,
            "is_event": bool(is_event),
            "measures": [{
                "measure": "mDIn",
                "devices": devices_list
            }]
        }

        ok = queue_mqtt_message(final_payload)
        if ok:
            print(f"[INFO] Полное состояние отправлено ({len(devices_list)} устройств)")
        else:
            print(f"[INFO] Полное состояние добавлено в очередь ({len(devices_list)} устройств)")

    except Exception as e:
        print(f"[ERROR] Ошибка при отправке полного состояния: {e}")
    finally:
        s.close()


def send_askue_snapshot_to_mqtt():
    """
    Отправляет в MQTT один "снимок" всех доступных AskueData.
    В телеграм не дублируем.
    """
    s = SessionLocal()
    try:
        rows = s.query(AskueData).all()
        if not rows:
            return

        devices_list = []
        ts_now = datetime.now().astimezone().isoformat(timespec="seconds")

        for r in rows:
            tags = []

            # базовые поля, чтобы на стороне сервера легче связывать
            if r.cell_number is not None:
                tags.append({"tag": "cell_number", "val": int(r.cell_number)})
            if r.ktt is not None:
                tags.append({"tag": "ktt", "val": float(r.ktt)})
            if r.ktn is not None:
                tags.append({"tag": "ktn", "val": float(r.ktn)})

            # электрические параметры
            for key in ["UA","UB","UC","IA","IB","IC","PS","PA","PB","PC","QS","QA","QB","QC",
                        "AngAB","AngBC","AngAC","kPS","kPA","kPB","kPC","Freq"]:
                val = getattr(r, key, None)
                if val is not None:
                    tags.append({"tag": key, "val": float(val)})

            # временная метка из БД, если есть
            if r.last_update is not None:
                try:
                    ts = r.last_update.astimezone().isoformat(timespec="seconds")
                except Exception:
                    ts = ts_now
            else:
                ts = ts_now

            devices_list.append({
                "id": r.meter_serial,
                "type": DEVICE_TYPE,
                "serial": r.meter_serial,
                "vals": [{
                    "ts": ts,
                    "diff": 0,
                    "tags": tags
                }]
            })

        payload = {
            "name": DEVICE_NAME,
            "serial": DEVICE_SERIAL,
            "fw": DEVICE_FW,
            "is_event": False,
            "measures": [{
                "measure": "aQual",
                "devices": devices_list
            }]
        }

        queue_mqtt_message(payload)

    except Exception as e:
        print(f"[ERROR] Ошибка отправки ASKUE snapshot: {e}")
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

def tg_queue_put(text: str) -> bool:
    """Положить в очередь TG, если переполнена — дропнуть самое старое."""
    try:
        tg_queue.put_nowait(text)
        return True
    except Full:
        try:
            _ = tg_queue.get_nowait()
        except Empty:
            pass
        try:
            tg_queue.put_nowait(text)
            return True
        except Full:
            return False

def send_telegram_message_async(text: str):
    ok = tg_queue_put(text)
    if ok:
        print(f"[TG] queued (size={tg_queue.qsize()}/{TG_QUEUE_MAX})")
    else:
        print("[TG][ERROR] queue overflow: drop")
    return ok

def telegram_worker():
    url = f"{TELEGRAM_URL}/bot{TELEGRAM_TOKEN}/sendMessage"

    fail_streak = 0

    while True:
        try:
            text = tg_queue.get(timeout=1)
        except Empty:
            continue

        data = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}

        ok = False
        last_err = None

        for attempt in range(3):
            try:
                r = requests.post(url, data=data, timeout=(3, 10))
                if r.status_code == 200:
                    ok = True
                    break
                else:
                    last_err = f"HTTP {r.status_code}: {r.text[:120]}"
            except Exception as e:
                last_err = str(e)

            time.sleep(2)

        if ok:
            fail_streak = 0
            print(f"[TG] Sent (queue={tg_queue.qsize()}/{TG_QUEUE_MAX}) : {text[:80]}...")
            tg_queue.task_done()
            continue

        # НЕ УДАЛОСЬ: возвращаем обратно в очередь
        fail_streak += 1
        tg_queue.task_done()

        requeued = tg_queue_put(text)
        print(f"[TG] Failed, requeue={requeued}, streak={fail_streak}, err={last_err}")

        # backoff чтобы не молотить сеть
        sleep_sec = min(60, 5 * fail_streak)  # 5,10,15.. до 60
        time.sleep(sleep_sec)

def send_telegram_error_once_in_period(error_text, last_send_time, period_sec=3600):
    """
    Отправляет error_text в Телеграм, если с момента last_send_time
    прошло не меньше period_sec. Возвращает новое значение last_send_time.
    """
    now = datetime.now()
    if last_send_time is None or (now - last_send_time).total_seconds() >= period_sec:
        send_telegram_message_async(error_text)
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

# Запуск фонового отправщика Telegram
tg_worker_thread = threading.Thread(target=telegram_worker, daemon=True)
tg_worker_thread.start()
print("[TG] Telegram worker started")


# Отправляем начальное состояние всех устройств (это НЕ событие)
send_full_state_to_mqtt(is_event=False)


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
    new_key = get_web_key_daily()
    msg_text = (
        f"{TELEGRAM_HEADER}\n\n"
        "Запуск мониторинга после отключения.\n"
        f"Крайний успешный опрос - {date_str}\n\n"
        f'<a href="http://{FLASK_HOST}:{FLASK_PORT}/?key={new_key}">Мнемосхема</a>'
    )

    send_telegram_message_async(msg_text)


send_initial_telegram_message()

#####################################################
# ГЛАВНЫЙ ЦИКЛ
#####################################################
print("[INFO] Старт опроса...")

last_mqtt_queue_check = datetime.now()
MQTT_QUEUE_CHECK_INTERVAL = 10  # Проверять очередь раз в минуту

last_full_state_send = datetime.now()
# FULL_STATE_INTERVAL_SEC = 3600  # раз в час

while True:
    current_time = datetime.now()

    # 0) Раз в час отправляем полный снимок (MQTT only)
    if (current_time - last_full_state_send).total_seconds() >= FULL_STATE_INTERVAL_SEC:
        send_full_state_to_mqtt(is_event=False)
        send_askue_snapshot_to_mqtt()
        last_full_state_send = current_time


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
                    send_telegram_message_async(msg)

                    # MQTT: отправляем ПОЛНЫЙ снимок ВСЕХ устройств как событие
                    send_full_state_on_link_change(is_event=True)

                    alert_sent[uid] = True
            else:
                print(f"[DEBUG] Первая попытка — не отправляем тревогу.")
            continue
        else:
            now_success = datetime.now()
            last_success_device[uid] = now_success
            if alert_sent[uid]:
                print(f"[INFO] Устройство unit_id={uid} восстановило связь.")

                # MQTT: отправляем ПОЛНЫЙ снимок ВСЕХ устройств как обычный снимок
                send_full_state_on_link_change(is_event=False)

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
                "serial": f"{DEVICE_SIDE}_{uid2}",
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
            "is_event": True,
            "measures": [{
                "measure": "mDIn",
                "devices": devices_list
            }]
        }

        # Используем очередь для отправки MQTT сообщений
        mqtt_success = queue_mqtt_message(final_payload)
        if not mqtt_success and not is_mqtt_connected:
            print(f"[WARN] MQTT не подключен, сообщение добавлено в очередь ({mqtt_message_queue.qsize()} в очереди)")

        # Дополнительно шлём ПКЭ/АСКУЭ в MQTT (в телегу не дублируем)
        send_askue_snapshot_to_mqtt()

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
        new_key = get_web_key_daily()

        if new_key:
            # Формируем ссылку
            link = f"http://{FLASK_HOST}:{FLASK_PORT}/?key={new_key}"
            # Добавляем в конец сообщения
            msg_text += f'\n\n<a href="{link}">Подробнее на мнемосхеме</a>'

        send_telegram_message_async(msg_text)

    time.sleep(POLL_INTERVAL_SEC)