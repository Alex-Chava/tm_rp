# app/views.py

from flask import Blueprint, render_template
from datetime import datetime, timedelta

from .database import db_session
from .models import HVCell, AskueData

main = Blueprint('main', __name__)

@main.route('/')
def index():
    # Получаем все записи из базы данных
    all_cells = db_session.query(HVCell).all()

    # Группируем записи по cell_number
    cells_dict = {}
    now_minus_5 = datetime.now() - timedelta(minutes=5)

    for cell in all_cells:
        cn = cell.cell_number
        if cn not in cells_dict:
            cells_dict[cn] = []
        # Можно сразу подготовить дополнительные флаги, например old_date_flag
        # Но пока складываем «как есть»
        cells_dict[cn].append(cell)

    askue_rows = db_session.query(AskueData).all()
    askue_data = {row.cell_number: row for row in askue_rows}

    return render_template('index.html', cells=cells_dict, now_minus_5=now_minus_5, timedelta=timedelta, askue_data=askue_data)


from flask import current_app, jsonify
import secrets

@main.route('/api/new_key', methods=['GET'])
def generate_new_key():
    """
    Генерирует новый случайный ключ и записывает его в конфиг приложения.
    Возвращает JSON: {"key": "..."}.
    """
    new_key = secrets.token_urlsafe(16)
    current_app.config['CURRENT_KEY'] = new_key
    return jsonify({"key": new_key})
