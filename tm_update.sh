# Сохранить текущие версии файлов
# Остановить ТМ

./stop_tm.sh
cp config.json config.json.backup
cp database.db database.db.backup

# Выполнить обновление
git checkout master
git fetch origin
git reset --hard origin/master

# Делаем все файлы в папке ./test исполняемыми
echo "Предоставление прав на выполнение для всех файлов в папке ./test..."
find ./test -type f -exec chmod +x {} \;

# Делаем все .sh файлы в папке исполняемыми
echo "Предоставление прав на выполнение для всех .sh файлов..."
find /home/tm_rp -name "*.sh" -type f -exec chmod +x {} \;

# Восстановить свои версии файлов
cp config.json.backup config.json
cp database.db.backup database.db