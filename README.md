# Adrobot

Сервис для трекера Keitaro (10.3.x): создание кампаний по шаблону и редактор офферов в существующих кампаниях.

Стек: FastAPI, SQLAlchemy 2.0, Alembic, фронт на HTML + jQuery.

> Статус: этап 0 (каркас). Создание кампаний и редактор появятся на следующих этапах.

## Требования
- Python 3.11+
- Доступ к Keitaro и API-ключ (Keitaro → Профиль → API ключи)

## Установка

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # затем заполните KEITARO_URL и KEITARO_API_KEY
```

## Миграции

```bash
alembic upgrade head      # создать/обновить схему БД
alembic downgrade base    # откатить все миграции
```

По умолчанию используется SQLite (`adrobot.db`); для Postgres задайте `DATABASE_URL`.

## Запуск

```bash
uvicorn app.main:app --reload
```

- Healthcheck: http://127.0.0.1:8000/health
- Swagger: http://127.0.0.1:8000/docs

## Тесты

```bash
pytest
```

## Переменные окружения

| Переменная | Описание |
|---|---|
| `KEITARO_URL` | адрес трекера |
| `KEITARO_API_KEY` | ключ Admin API |
| `KEITARO_DEFAULT_DOMAIN` / `_GROUP` / `_SOURCE` | домен, группа и источник для новых кампаний |
| `DATABASE_URL` | строка подключения SQLAlchemy |
| `LOG_LEVEL` | уровень логирования |
