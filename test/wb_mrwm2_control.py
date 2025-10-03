import serial
import struct
import time
import sys
import argparse
from typing import Optional, List


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


def create_modbus_request(unit_id: int, function_code: int, start_address: int, data: List[int] = None) -> bytes:
    """
    Создание Modbus RTU запроса
    """
    if function_code == 0x05:  # Write Single Coil
        value = data[0] if data else 0x0000
        req = struct.pack('>BBHH', unit_id, function_code, start_address, value)
    else:
        quantity = data[0] if data else 1
        req = struct.pack('>BBHH', unit_id, function_code, start_address, quantity)

    crc_val = calculate_crc(req)
    req += struct.pack('<H', crc_val)
    return req


def send_modbus_request(ser: serial.Serial, request: bytes, debug: bool = False, use_echo: bool = True) -> bytes:
    """
    Отправка Modbus запроса и чтение ответа с обработкой эхо
    """
    if debug:
        print(f"Отправка запроса: {request.hex()}")

    ser.write(request)

    # Читаем эхо (если включено)
    if use_echo:
        echo = ser.read(len(request))
        if debug and echo:
            print(f"Получено эхо: {echo.hex()}")
    else:
        if debug:
            print("Эхо отключено")

    time.sleep(0.02)
    response = ser.read(256)

    if debug:
        print(f"Получен ответ: {response.hex() if response else 'Нет ответа'}")

    return response


def parse_modbus_response(response: bytes, debug: bool = False) -> bool:
    """
    Парсинг Modbus ответа для операций записи
    """
    if len(response) < 5:
        if debug:
            print(f"Слишком короткий ответ: {len(response)} байт")
        return False

    # Проверяем CRC
    data_without_crc = response[:-2]
    received_crc = struct.unpack('<H', response[-2:])[0]
    calculated_crc = calculate_crc(data_without_crc)

    if received_crc != calculated_crc:
        if debug:
            print(f"Ошибка CRC: получено {received_crc:04X}, вычислено {calculated_crc:04X}")
        return False

    function_code = response[1]
    if function_code & 0x80:
        error_code = response[2]
        if debug:
            print(f"Modbus ошибка: код {error_code}")
        return False

    return True


def write_single_coil(ser: serial.Serial, unit_id: int, coil_address: int, state: bool, debug: bool = False,
                      use_echo: bool = True) -> bool:
    """
    Запись одного coil (функция 0x05) - адреса 0-5 для управления реле
    """
    try:
        if debug:
            print(f"Запись coil: адрес={coil_address}, состояние={state}")

        value = 0xFF00 if state else 0x0000
        request = create_modbus_request(unit_id, 0x05, coil_address, [value])
        response = send_modbus_request(ser, request, debug, use_echo)

        if len(response) == 0:
            if debug:
                print("Нет ответа от устройства")
            return False

        return parse_modbus_response(response, debug)

    except Exception as e:
        if debug:
            print(f"Ошибка записи coil {coil_address}: {e}")
        return False


def write_single_relay(ser: serial.Serial, unit_id: int, relay_num: int, state: bool, debug: bool = False,
                       use_echo: bool = True) -> bool:
    """
    Управление одним реле через Coils (адреса 0-5 для реле 1-6)
    """
    try:
        coil_address = relay_num  # Реле 1 = адрес 0, реле 2 = адрес 1, и т.д.
        return write_single_coil(ser, unit_id, coil_address, state, debug, use_echo)

    except Exception as e:
        if debug:
            print(f"Ошибка управления реле {relay_num + 1}: {e}")
        return False


def write_all_relays(ser: serial.Serial, unit_id: int, relay_states: List[bool], debug: bool = False,
                     use_echo: bool = True) -> bool:
    """
    Управление всеми реле одновременно через отдельные команды
    """
    try:
        success = True
        for i, state in enumerate(relay_states):
            if not write_single_coil(ser, unit_id, i, state, debug, use_echo):
                success = False
        return success

    except Exception as e:
        if debug:
            print(f"Ошибка управления всеми реле: {e}")
        return False


def setup_serial_port(com_port: str, baudrate: int = 115200) -> Optional[serial.Serial]:
    """
    Настройка последовательного порта
    """
    try:
        print(f"Открытие порта {com_port} со скоростью {baudrate}...")

        ser = serial.Serial(
            port=com_port,
            baudrate=baudrate,
            bytesize=8,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0,
            write_timeout=1.0
        )

        ser.reset_input_buffer()
        ser.reset_output_buffer()
        time.sleep(0.2)

        print(f"✓ Порт {com_port} успешно открыт")
        return ser

    except serial.SerialException as e:
        print(f"✗ Ошибка открытия порта {com_port}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description='Управление реле WB-MRWM2')
    parser.add_argument('--port', required=True, help='COM порт (например: COM1 или /dev/ttyUSB0)')
    parser.add_argument('--id', type=int, required=True, help='Modbus ID устройства')
    parser.add_argument('--baudrate', type=int, default=115200, help='Скорость обмена (по умолчанию: 115200)')
    parser.add_argument('--action', choices=['on', 'off', 'pulse', 'all_on', 'all_off'],
                        required=True, help='Действие')
    parser.add_argument('--relay', type=int, choices=range(1, 7), help='Номер реле (1-6)')
    parser.add_argument('--time', type=float, default=1.0, help='Время импульса в секундах (для pulse)')
    parser.add_argument('--debug', action='store_true', help='Включить отладочный вывод')
    parser.add_argument('--no-echo', action='store_true', help='Отключить обработку эхо')

    args = parser.parse_args()

    use_echo = not args.no_echo

    print("=== Управление реле WB-MRWM2 ===")
    print(f"Порт: {args.port}, ID: {args.id}, Скорость: {args.baudrate}")
    print(f"Обработка эхо: {'ВКЛЮЧЕНА' if use_echo else 'ОТКЛЮЧЕНА'}")
    print("Управление: Coils 0-5 (реле 1-6)")
    if args.debug:
        print("Режим отладки: ВКЛЮЧЕН")
    print("=" * 50)

    # Настройка последовательного порта
    ser = setup_serial_port(args.port, args.baudrate)
    if not ser:
        sys.exit(1)

    try:
        if args.action in ['on', 'off', 'pulse']:
            if not args.relay:
                print("Ошибка: для этого действия требуется указать --relay")
                sys.exit(1)

            relay_num = args.relay - 1  # Преобразуем в 0-based индекс

            if args.action == 'on':
                print(f"Включение реле {args.relay}...")
                if write_single_relay(ser, args.id, relay_num, True, args.debug, use_echo):
                    print("✓ Успешно")
                else:
                    print("✗ Ошибка")

            elif args.action == 'off':
                print(f"Выключение реле {args.relay}...")
                if write_single_relay(ser, args.id, relay_num, False, args.debug, use_echo):
                    print("✓ Успешно")
                else:
                    print("✗ Ошибка")

            elif args.action == 'pulse':
                print(f"Импульс реле {args.relay} на {args.time} сек...")
                # Включаем реле
                if write_single_relay(ser, args.id, relay_num, True, args.debug, use_echo):
                    print(f"✓ Реле {args.relay} включено")
                    time.sleep(args.time)
                    # Выключаем реле
                    if write_single_relay(ser, args.id, relay_num, False, args.debug, use_echo):
                        print("✓ Импульс выполнен успешно")
                    else:
                        print("✗ Ошибка выключения реле")
                else:
                    print("✗ Ошибка включения реле")

        elif args.action in ['all_on', 'all_off']:
            state = True if args.action == 'all_on' else False
            state_str = "включены" if state else "выключены"
            print(f"{'Включение' if state else 'Выключение'} всех реле...")

            relay_states = [state] * 6  # 6 реле
            if write_all_relays(ser, args.id, relay_states, args.debug, use_echo):
                print(f"✓ Все реле {state_str}")
            else:
                print("✗ Ошибка при управлении некоторыми реле")

    except Exception as e:
        print(f"Ошибка: {e}")

    finally:
        ser.close()
        print("\nПорт закрыт")


if __name__ == "__main__":
    main()