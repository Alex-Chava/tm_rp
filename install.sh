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

# Создание сервисного файла
echo "Создание сервисного файла..."
sudo tee /etc/systemd/system/tm_web.service > /dev/null <<EOF
[Unit]
Description=tm_rp Web
After=network.target

[Service]
User=root
WorkingDirectory=/home/tm_rp
Environment=PATH=/home/tm_rp/venv/bin:\$PATH
ExecStart=/home/tm_rp/venv/bin/waitress-serve --listen=0.0.0.0:5555 app_instance:app

[Install]
WantedBy=multi-user.target
EOF

echo "Сервисный файл создан: /etc/systemd/system/tm_web.service"

# Создание сервисного файла
echo "Создание сервисного файла..."
sudo tee /etc/systemd/system/tm_sync@.service > /dev/null <<EOF
[Unit]
Description=tm_rp Sync Module side %I
After=network.target

[Service]
User=root
WorkingDirectory=/home/tm_rp
Environment=PATH=/home/tm_rp/venv/bin:$PATH
ExecStart=/home/tm_rp/venv/bin/python3 /home/tm_rp/tm_syncmodule.py -s %I

[Install]
WantedBy=multi-user.target
EOF

echo "Сервисный файл создан: /etc/systemd/system/tm_sync@.service"

# Создание сервисного файла
echo "Создание сервисного файла..."
sudo tee /etc/systemd/system/tm_askue.service > /dev/null <<EOF
[Unit]
Description=tm_rp ASKUE
After=network.target

[Service]
User=root
WorkingDirectory=/home/tm_rp
Environment=PATH=/home/tm_rp/venv/bin:$PATH
ExecStart=/home/tm_rp/venv/bin/python3 /home/tm_rp/askue_module.py

[Install]
WantedBy=multi-user.target
EOF

echo "Сервисный файл создан: /etc/systemd/system/tm_askue.service"

sudo systemctl enable tm_web.service
sudo systemctl enable tm_sync@1.service
sudo systemctl enable tm_sync@2.service
sudo systemctl enable tm_askue.service

echo "Установка завершена!"