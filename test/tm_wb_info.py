import serial
import struct
import time
import argparse
from typing import Optional, List, Tuple
from sqlalchemy import create_engine, text


def calculate_crc(data: bytes) -> int:
    """
    Расчет CRC16 для Modbus RTU
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc


def create_modbus_request(unit_id: int, function_code: int, start_address: int, quantity: int) -> bytes:
    """
    Создание Modbus RTU запроса
    """
    req = struct.pack('>BBHH', unit_id, function_code, start_address, quantity)
    crc_val = calculate_crc(req)
    req += struct.pack('<H', crc_val)
    return req


def send_modbus_request(ser: serial.Serial, request: bytes, use_echo: bool = True) -> bytes:
    """
    Отправка Modbus запроса и чтение ответа
    """
    ser.write(request)

    # Если есть эхо, читаем его
    if use_echo:
        echo = ser.read(len(request))  # читаем эхо
        time.sleep(0.02)

    response = ser.read(256)
    return response


def parse_modbus_response(response: bytes) -> Optional[List[int]]:
    """
    Парсинг Modbus ответа и проверка CRC
    """
    if len(response) < 5:
        return None

    # Проверяем CRC
    data_without_crc = response[:-2]
    received_crc = struct.unpack('<H', response[-2:])[0]
    calculated_crc = calculate_crc(data_without_crc)

    if received_crc != calculated_crc:
        return None

    function_code = response[1]
    if function_code & 0x80:
        return None

    if function_code == 0x03:
        byte_count = response[2]
        if len(response) != 3 + byte_count + 2:
            return None

        data_bytes = response[3:3 + byte_count]
        registers = []
        for i in range(0, len(data_bytes), 2):
            if i + 1 < len(data_bytes):
                register = (data_bytes[i] << 8) | data_bytes[i + 1]
                registers.append(register)
        return registers

    return None


def read_string_from_registers(ser: serial.Serial, unit_id: int, start_address: int, num_registers: int,
                               use_echo: bool = True) -> Optional[
    str]:
    """
    Чтение строки из регистров (точно как в app.py)
    """
    try:
        request = create_modbus_request(unit_id, 0x03, start_address, num_registers)
        response = send_modbus_request(ser, request, use_echo)

        if len(response) == 0:
            return None

        registers = parse_modbus_response(response)

        if registers:
            # Преобразуем регистры в строку (каждый регистр = 2 байта)
            string = ""
            for reg in registers:
                char1 = chr((reg >> 8) & 0xFF)
                char2 = chr(reg & 0xFF)
                if char1 != '\x00':
                    string += char1
                if char2 != '\x00':
                    string += char2

            # Удаление нулевых символов и пробелов по краям
            return string.strip()

        return None

    except Exception as e:
        print(f"Ошибка чтения строки из регистра {start_address}: {e}")
        return None


def read_u32_from_registers(ser: serial.Serial, unit_id: int, start_address: int, use_echo: bool = True) -> Optional[
    int]:
    """
    Чтение 32-битного числа (u32) из двух регистров (точно как в app.py)
    """
    try:
        request = create_modbus_request(unit_id, 0x03, start_address, 2)
        response = send_modbus_request(ser, request, use_echo)

        if len(response) == 0:
            return None

        registers = parse_modbus_response(response)

        if registers and len(registers) >= 2:
            # Преобразование регистров в u32 (big-endian) как в app.py
            u32_value = struct.unpack(">I", struct.pack(">HH", registers[0], registers[1]))[0]
            return u32_value

        return None

    except Exception as e:
        print(f"Ошибка чтения u32 из регистра {start_address}: {e}")
        return None


def read_u16_from_register(ser: serial.Serial, unit_id: int, address: int, use_echo: bool = True) -> Optional[int]:
    """
    Чтение 16-битного числа (u16) из одного регистра
    """
    try:
        request = create_modbus_request(unit_id, 0x03, address, 1)
        response = send_modbus_request(ser, request, use_echo)

        if len(response) == 0:
            return None

        registers = parse_modbus_response(response)

        if registers and len(registers) >= 1:
            return registers[0]

        return None

    except Exception as e:
        print(f"Ошибка чтения u16 из регистра {address}: {e}")
        return None


def read_wb_mio_info(ser: serial.Serial, unit_id: int, use_echo: bool = True) -> dict:
    """
    Чтение информации об устройстве WB-MIO с использованием адресов из app.py
    """
    info = {
        'model': None,
        'firmware': None,
        'serial': None,
        'voltage': None
    }

    # Модель устройства - адрес 200, 10 регистров (строка)
    info['model'] = read_string_from_registers(ser, unit_id, 200, 10, use_echo)

    # Версия прошивки - адрес 250, 10 регистров (строка)
    info['firmware'] = read_string_from_registers(ser, unit_id, 250, 10, use_echo)

    # Серийный номер - адрес 270, 2 регистра (u32)
    serial_u32 = read_u32_from_registers(ser, unit_id, 270, use_echo)
    if serial_u32:
        info['serial'] = str(serial_u32)  # Преобразуем в строку

    # Напряжение - адрес 121, 1 регистр (u16)
    voltage_raw = read_u16_from_register(ser, unit_id, 121, use_echo)
    if voltage_raw:
        info['voltage'] = f"{voltage_raw / 1000:.2f} V"  # Форматируем как в app.py

    return info


def get_unique_devices(db_url: str) -> List[Tuple[int, str]]:
    """
    Получение уникальных устройств из базы данных
    """
    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT DISTINCT unit_id, com 
                FROM hv_cells 
                WHERE unit_id IS NOT NULL AND com IS NOT NULL
                ORDER BY unit_id
            """))
            devices = result.fetchall()
        return devices

    except Exception as e:
        print(f"Ошибка работы с базой данных: {e}")
        return []


def setup_serial_port(com_port: str, baudrate: int = 115200) -> Optional[serial.Serial]:
    """
    Настройка последовательного порта для WB-MIO
    """
    try:
        ser = serial.Serial(
            port=com_port,
            baudrate=baudrate,  # Используем переданную скорость
            bytesize=8,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=2.0
        )

        ser.reset_input_buffer()
        ser.reset_output_buffer()
        time.sleep(0.1)

        return ser

    except serial.SerialException as e:
        print(f"Ошибка открытия порта {com_port}: {e}")
        return None


def main():
    # Парсинг аргументов командной строки
    parser = argparse.ArgumentParser(description='Опрос устройств WB-MIO')
    parser.add_argument('--baudrate', '-b', type=int, default=115200,
                        help='Скорость обмена (по умолчанию: 115200)')
    parser.add_argument('--no-echo', action='store_true',
                        help='Работать без эха (по умолчанию: с эхом)')
    args = parser.parse_args()

    db_path = 'database.db'
    db_url = f'sqlite:///{db_path}'

    use_echo = not args.no_echo  # Инвертируем, так как флаг называется "no-echo"

    print("=== Программа опроса устройств WB-MIO ===")
    print(f"Параметры связи: {args.baudrate} 8N1")
    print(f"Режим работы: {'с эхом' if use_echo else 'без эха'}")
    print("Адреса регистров из app.py:")
    print("  Модель: 200, Прошивка: 250, Серийный: 270, Напряжение: 121")
    print("=" * 50)

    devices = get_unique_devices(db_url)

    if not devices:
        print("В базе данных не найдено устройств для опроса")
        return

    print(f"Найдено {len(devices)} уникальных устройств для опроса")

    devices_by_com = {}
    for device in devices:
        unit_id, com_port = device
        if com_port not in devices_by_com:
            devices_by_com[com_port] = []
        devices_by_com[com_port].append(unit_id)

    results = []

    for com_port, unit_ids in devices_by_com.items():
        print(
            f"\n--- Опрос устройств на порту {com_port} (скорость: {args.baudrate}, режим: {'с эхом' if use_echo else 'без эха'}) ---")

        ser = setup_serial_port(com_port, args.baudrate)
        if not ser:
            print(f"Пропускаем порт {com_port} из-за ошибки подключения")
            continue

        try:
            for unit_id in unit_ids:
                print(f"\nОпрашиваем устройство ID {unit_id}:")

                device_info = read_wb_mio_info(ser, unit_id, use_echo)

                # Формируем строку с результатами
                model = device_info['model'] or "не прочитана"
                firmware = device_info['firmware'] or "не прочитана"
                voltage = device_info['voltage'] or "не прочитано"

                result_line = f"ID {unit_id} Модель: {model} Прошивка: {firmware} Напряжение: {voltage}"

                if device_info['serial']:
                    print(f"✓ {result_line}")
                    results.append(f"ID {unit_id} SN {device_info['serial']}")
                else:
                    print(f"✗ {result_line}")
                    results.append(f"ID {unit_id} - серийный номер не найден")

                time.sleep(0.2)

        except Exception as e:
            print(f"Ошибка при опросе порта {com_port}: {e}")

        finally:
            ser.close()

    print("\n" + "=" * 50)
    print("ИТОГОВЫЕ РЕЗУЛЬТАТЫ:")
    print("=" * 50)
    for result in results:
        print(result)


if __name__ == "__main__":
    main()