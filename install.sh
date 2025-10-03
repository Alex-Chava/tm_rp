#!/bin/bash

echo "Начало установки..."

# Обновление пакетов
sudo apt-get update

# Установка Python
sudo apt-get install -y python3 python3-pip python3-venv

# Обновление pip
pip3 install --upgrade pip

# Создание виртуального окружения
python3 -m venv /home/tm_rp/venv

# Активация и установка зависимостей
source /home/tm_rp/venv/bin/activate
cd /home/tm_rp

# Установка пакетов из requirements.txt (если файл существует)
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    echo "Зависимости установлены!"
else
    echo "Файл requirements.txt не найден. Создайте его и добавьте зависимости."
fi

# Делаем все файлы в папке ./test исполняемыми
echo "Предоставление прав на выполнение для всех файлов в папке ./test..."
find ./test -type f -exec chmod +x {} \;

# Делаем все .sh файлы в папке исполняемыми
echo "Предоставление прав на выполнение для всех .sh файлов..."
find /home/tm_rp -name "*.sh" -type f -exec chmod +x {} \;

echo "Установка завершена!"