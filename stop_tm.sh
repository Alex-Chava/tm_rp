#!/bin/bash
sudo systemctl stop tm_sync@2.service
sudo systemctl stop tm_sync@1.service
sudo systemctl stop tm_askue.service
sudo systemctl stop tm_web.service
echo "Все сервисы остановлены"
