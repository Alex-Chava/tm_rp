"""
askue_module.py

Модуль для опроса УМ-31 (ASKUE). Раз в минуту:
1. Авторизуется на устройстве по IP.
2. Запрашивает показания с нужными тегами и временным интервалом:
   - Временной интервал рассчитывается: start = текущий момент, end = текущий момент + 10 минут.
3. Парсит JSON-ответ, выбирая для каждого устройства запись с максимально поздней меткой времени (ts)
4. Обновляет (или создаёт) записи в таблице AskueData – для каждого счётчика (по meter_serial),
   при этом поле last_update берётся из ответа устройства (поле ts).
"""

import time
import requests
import json
import os
from datetime import datetime, timedelta
# from sqlalchemy import func
from app.database import db_session, init_db
from app.models import AskueData
import logging
from app.config import Config

# Инициализируем базу (создаются таблицы, если их ещё нет)
init_db(Config.DATABASE_URL)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Параметры авторизации
UM_LOGIN = "SamoletTM"
UM_PASSWORD = "QhV8GyML"


# Чтение параметров из config.json
def get_askue_config():
    """Чтение параметров АСКУЭ из config.json"""
    try:
        # config.json находится в той же директории, что и этот скрипт
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, 'config.json')

        logger.info("Попытка чтения config.json по пути: %s", config_path)

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        logger.info("Конфигурация успешно загружена из %s", config_path)

        return {
            "UM_IP": config.get("UM_IP", "192.168.0.1"),
            "UM_INTERVAL_MIN": config.get("UM_INTERVAL_MIN", 20),
            "UM_POLL_SEC": config.get("UM_POLL_SEC", 60)
        }
    except FileNotFoundError:
        logger.error("Файл config.json не найден. Используются значения по умолчанию.")
        return {
            "UM_IP": "192.168.0.1",
            "UM_INTERVAL_MIN": 20,
            "UM_POLL_SEC": 60
        }
    except Exception as e:
        logger.error("Ошибка чтения config.json: %s. Используются значения по умолчанию.", e)
        return {
            "UM_IP": "192.168.0.1",
            "UM_INTERVAL_MIN": 20,
            "UM_POLL_SEC": 60
        }


# Загружаем конфигурацию
config = get_askue_config()
UM_IP = config["UM_IP"]
UM_INTERVAL_MIN = config["UM_INTERVAL_MIN"]
UM_POLL_SEC = config["UM_POLL_SEC"]


##############################################################################
# Функция авторизации на УМ-31
##############################################################################
def askue_auth(ip, retries=3, delay=5):
    """
    Авторизация на УМ-31 с повторными попытками и сбросом соединения.
    """
    url = f"http://{ip}/auth"
    payload = '{"login":"%s","password":"%s"}' % (UM_LOGIN, UM_PASSWORD)

    for attempt in range(retries):
        try:
            # Создаем новую сессию для каждой попытки
            with requests.Session() as session:
                headers = {'Connection': 'close'}
                resp = session.post(url, data=payload, headers=headers, timeout=10)

                if resp.status_code == 200:
                    sessionid = resp.cookies.get("sessionid")
                    if sessionid:
                        logger.info("Успешная авторизация на %s (попытка %d)", ip, attempt + 1)
                        return sessionid

                logger.warning("Ошибка авторизации на %s, код: %s (попытка %d)",
                               ip, resp.status_code, attempt + 1)

        except Exception as e:
            logger.warning("Исключение при авторизации на %s: %s (попытка %d)",
                           ip, e, attempt + 1)

        # Пауза перед повторной попыткой (кроме последней)
        if attempt < retries - 1:
            time.sleep(delay)

    logger.error("Не удалось авторизоваться на %s после %d попыток", ip, retries)
    return None


##############################################################################
# Функция запроса данных с УМ-31
##############################################################################
def askue_read_data(ip, sessionid):
    """
    Запрашивает данные у УМ-31 с использованием sessionid (cookies).
    Формирует payload, включающий:
      - tags: список требуемых тегов
      - measures: ["aQual"]
      - time: [{"start": <текущий момент в ISO8601>, "end": <текущий момент+10 мин в ISO8601>}]
    Возвращает JSON-ответ как dict при успехе или None.
    """
    url = f"http://{ip}/meter/data"
    # Рассчитываем временной интервал: от текущего момента до +10 минут.
    now = datetime.now()
    end_time = now.isoformat()
    start_time = (now - timedelta(minutes=UM_INTERVAL_MIN)).isoformat()
    time_str = f'[{{"start":"{start_time}","end":"{end_time}"}}]'

    payload = (
            '{"tags":["UA","UB","UC","IA","IB","IC","PS","PA","PB","PC",'
            '"QS","QA","QB","QC","AngAB","AngBC","AngAC","kPS","kPA","kPB","kPC","Freq"],'
            '"measures":["aQual"],'
            '"ids":[],'
            '"time":' + time_str + ','
                                   '"logtime":{}}'
    )
    cookies = {"sessionid": sessionid}
    logger.info(payload)
    try:
        resp = requests.post(url, data=payload, cookies=cookies, timeout=5)
        if resp.status_code == 200:
            return resp.json()
        logger.error("Ошибка чтения данных: код %s", resp.status_code)
        return None
    except requests.exceptions.Timeout:
        logger.error("Таймаут соединения: сервер не ответил в течение 5 секунд")
        return None
    except requests.exceptions.ConnectionError:
        logger.error("Ошибка соединения: невозможно подключиться к серверу")
        return None
    except Exception as e:
        logger.error("Исключение при чтении данных: %s", e)
        return None


##############################################################################
# Вспомогательная функция для преобразования ISO8601 строки в datetime
##############################################################################
def iso_to_dt(iso_str):
    """
    Преобразует строку вида "2025-03-25T17:01:14+03:00" в объект datetime.
    """
    return datetime.fromisoformat(iso_str)


##############################################################################
# Функция парсинга JSON-ответа для нескольких устройств
##############################################################################
def parse_askue_json_multi(data_json):
    """
    Парсит JSON-ответ от УМ-31, в котором может быть несколько devices.
    Для каждого device:
      - Выбирает запись с максимально поздним значением ts.
      - Преобразует список тегов в словарь.
      - Извлекает нужные поля:
            "device_serial", "ts", "UA", "UB", "UC",
            "IA", "IB", "IC", "PS", "PA", "PB", "PC",
            "QS", "QA", "QB", "QC",
            "AngAB", "AngBC", "AngAC",
            "kPS", "kPA", "kPB", "kPC",
            "Freq"
    Возвращает список словарей, где каждый словарь соответствует одному device.
    """
    result = []
    try:
        measures = data_json.get("measures", [])
        if not measures:
            logger.error("No 'measures' in data_json")
            return result

        # Объединяем всех devices из всех мер
        all_devices = []
        for m in measures:
            devs = m.get("devices", [])
            all_devices.extend(devs)

        for dev in all_devices:
            dev_serial = dev.get("serial", "unknown")
            vals_list = dev.get("vals", [])
            if not vals_list:
                logger.info("Device %s has no vals", dev_serial)
                continue

            # Выбираем запись с максимальным ts
            freshest_val = max(vals_list, key=lambda v: iso_to_dt(v["ts"]))
            tags = freshest_val.get("tags", [])
            tags_dict = {t["tag"]: t["val"] for t in tags}

            parsed_dict = {
                "device_serial": dev_serial,
                "ts": freshest_val["ts"],
                "UA": float(tags_dict.get("UA") or 0),
                "UB": float(tags_dict.get("UB") or 0),
                "UC": float(tags_dict.get("UC") or 0),
                "IA": float(tags_dict.get("IA") or 0),
                "IB": float(tags_dict.get("IB") or 0),
                "IC": float(tags_dict.get("IC") or 0),
                "PS": float(tags_dict.get("PS") or 0),
                "PA": float(tags_dict.get("PA") or 0),
                "PB": float(tags_dict.get("PB") or 0),
                "PC": float(tags_dict.get("PC") or 0),
                "QS": float(tags_dict.get("QS") or 0),
                "QA": float(tags_dict.get("QA") or 0),
                "QB": float(tags_dict.get("QB") or 0),
                "QC": float(tags_dict.get("QC") or 0),
                "AngAB": float(tags_dict.get("AngAB") or 0),
                "AngBC": float(tags_dict.get("AngBC") or 0),
                "AngAC": float(tags_dict.get("AngAC") or 0),
                "kPS": float(tags_dict.get("kPS") or 0),
                "kPA": float(tags_dict.get("kPA") or 0),
                "kPB": float(tags_dict.get("kPB") or 0),
                "kPC": float(tags_dict.get("kPC") or 0),
                "Freq": float(tags_dict.get("Freq") or 0),
            }
            result.append(parsed_dict)

        return result

    except Exception as e:
        logger.error("Ошибка при парсинге JSON (multi-device): %s", e)
        return result


##############################################################################
# Функция обновления данных в таблице AskueData
##############################################################################
def update_askue_data(parsed):
    """
    Обновляет (или создаёт) запись в таблице askue_data по meter_serial.
    Перезаписывает показания (UA, IB, ...), а также обновляет last_update.
    Здесь last_update устанавливается из поля ts, полученного от устройства.
    """
    if not parsed:
        return

    with db_session() as session:
        row = session.query(AskueData).filter_by(meter_serial=parsed["device_serial"]).first()
        if not row:
            row = AskueData(meter_serial=parsed["device_serial"])
            session.add(row)
        row.UA = parsed["UA"]
        row.UB = parsed["UB"]
        row.UC = parsed["UC"]

        row.IA = parsed["IA"]
        row.IB = parsed["IB"]
        row.IC = parsed["IC"]

        row.PS = parsed["PS"]
        row.PA = parsed["PA"]
        row.PB = parsed["PB"]
        row.PC = parsed["PC"]

        row.QS = parsed["QS"]
        row.QA = parsed["QA"]
        row.QB = parsed["QB"]
        row.QC = parsed["QC"]

        row.AngAB = parsed["AngAB"]
        row.AngBC = parsed["AngBC"]
        row.AngAC = parsed["AngAC"]

        row.kPS = parsed["kPS"]
        row.kPA = parsed["kPA"]
        row.kPB = parsed["kPB"]
        row.kPC = parsed["kPC"]

        row.Freq = parsed["Freq"]

        # Используем ts из ответа, преобразуя его в datetime
        row.last_update = iso_to_dt(parsed["ts"])

        session.commit()


##############################################################################
# Функция одного цикла опроса
##############################################################################
def askue_poll(ip=UM_IP):
    """
    Один цикл опроса:
      1. Авторизация на устройстве (askue_auth)
      2. Запрос данных с временным интервалом (10 минут от текущего момента)
      3. Парсинг JSON-ответа с выбором самой свежей записи для каждого устройства
      4. Обновление данных в таблице askue_data для каждого устройства
    """
    sessionid = askue_auth(ip)
    if not sessionid:
        logger.error("Не удалось авторизоваться на %s", ip)
        return

    data_json = askue_read_data(ip, sessionid)
    logger.info("Полученные данные: %s", data_json)
    if not data_json:
        logger.error("Не удалось получить данные с %s", ip)
        return

    parsed_list = parse_askue_json_multi(data_json)
    if not parsed_list:
        logger.error("Ошибка парсинга данных с %s", ip)
        return

    # Обновляем данные для каждого устройства отдельно
    for p in parsed_list:
        update_askue_data(p)
        logger.info("Данные устройства обновлены (meter_serial=%s).", p.get("device_serial", "N/A"))


##############################################################################
# Основной цикл опроса (раз в UM_POLL_SEC)
##############################################################################
def main():
    logger.info("Запуск модуля АСКУЭ...")
    logger.info("Конфигурация: IP=%s, INTERVAL=%d мин, POLL=%d сек",
                UM_IP, UM_INTERVAL_MIN, UM_POLL_SEC)
    while True:
        askue_poll()
        time.sleep(UM_POLL_SEC)


if __name__ == "__main__":
    main()