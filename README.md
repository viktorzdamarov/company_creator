# Adrobot

Сервис для трекера Keitaro (10.3.x): создание кампаний по шаблону и редактор офферов в существующих кампаниях.

Стек: FastAPI, SQLAlchemy 2.0, Alembic, фронт на HTML + jQuery.

> Статус: этап 3 — создание кампаний через API готово. Редактор и веб-интерфейс — на следующих этапах.

## API

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/offers?q=` | поиск офферов по ID или части названия (автокомплит) |
| `POST` | `/api/campaigns` | создать кампанию: `{"name": "...", "geo": "MX,AU,RO", "offer_id": 18813}` |
| `POST` | `/api/campaigns?dry_run=true` | то же без создания: показывает, что будет отправлено в Keitaro |

Создаваемая кампания:
- **Flow 1** — фильтр «Страны принимать = GEO» → редирект на https://google.com
- **Flow 2** — весь остальной трафик → выбранный оффер (100%)
- домен, группа и источник — из `KEITARO_DEFAULT_*` в `.env`; ротация «По позиции», CPC

Ответ содержит ID кампании, tracking URL и созданные потоки. Ошибки:
`422` — неверный GEO/имя или Keitaro отклонил данные; `404` — оффер не найден; `409` — кампания с таким именем уже есть;
`502/503/504` — проблемы с Keitaro (ключ, недоступность, таймаут). Если поток не создался, кампания удаляется (откат).
Все операции пишутся в таблицу `operation_logs`.

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

Проверка подключения к реальному Keitaro (только чтение, ничего не меняет):

```bash
python -m scripts.keitaro_smoke            # справочники, офферы, дефолты из .env
python -m scripts.keitaro_smoke 215521     # + потоки и статистика кампании
```

Форматы запросов/ответов Keitaro API: [docs/keitaro_api_notes.md](docs/keitaro_api_notes.md).

## Переменные окружения

| Переменная | Описание |
|---|---|
| `KEITARO_URL` | адрес трекера |
| `KEITARO_API_KEY` | ключ Admin API |
| `KEITARO_DEFAULT_DOMAIN` / `_GROUP` / `_SOURCE` | домен, группа и источник для новых кампаний |
| `KEITARO_TIMEOUT` / `KEITARO_MAX_RETRIES` / `KEITARO_RETRY_BACKOFF` | таймаут запроса, число повторов при 429/5xx/сетевых ошибках, начальная пауза |
| `DATABASE_URL` | строка подключения SQLAlchemy |
| `LOG_LEVEL` | уровень логирования |
