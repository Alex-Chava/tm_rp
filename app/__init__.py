# app/__init__.py

import secrets
from flask import Flask, request, abort
from .config import Config
from .database import init_db, db_session
from .views import main

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Инициализация БД (создание движка, scoped_session, если нужно — create_all)
    init_db(app.config['DATABASE_URL'])

    # Сгенерируем начальный "разовый" ключ (после перезапуска)
    # app.config['CURRENT_KEY'] = secrets.token_urlsafe(16)

    # Временно ставим статический ключ
    app.config['CURRENT_KEY'] = "12345"

    # Регистрируем blueprints
    app.register_blueprint(main)
    # app.register_blueprint(sse_bp)

    @app.before_request
    def check_access_key():
        """
        Проверяем, что у пользователя в GET-параметре ?key=...
        передан корректный ключ. Иначе 403.
        Пропускаем /static, /stream и favicon.ico при необходимости.
        """
        # Можно добавить ещё роуты, которые не требуют проверки
        exempt_endpoints = ('static', 'sse_bp.stream', 'favicon.ico', 'main.generate_new_key')
        if request.endpoint in exempt_endpoints:
            return  # пропускаем

        user_key = request.args.get('key')
        if user_key != app.config.get('CURRENT_KEY'):
            return abort(403, description="Неверный или отсутствующий ключ доступа")

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        """ Закрываем сессию после запроса """
        db_session.remove()

    return app
