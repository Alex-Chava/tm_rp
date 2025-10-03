# Сохранить текущие версии файлов
# Остановить ТМ

./stop_tm.sh
cp config.json config.json.backup
cp database.db database.db.backup

# Выполнить pull
git pull origin master

# Восстановить свои версии файлов
cp config.json.backup config.json
cp database.db.backup database.db