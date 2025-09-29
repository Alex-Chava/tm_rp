#!/bin/bash
sudo systemctl start tm_sync@2.service
sudo systemctl start tm_sync@1.service
sudo systemctl start tm_askue.service
sudo systemctl start tm_web.service
echo "Все сервисы запущены"
