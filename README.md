# Adrobot

[![tests](https://github.com/viktorzdamarov/company_creator/actions/workflows/tests.yml/badge.svg)](https://github.com/viktorzdamarov/company_creator/actions/workflows/tests.yml)

Сервис для трекера Keitaro: создаёт кампании по шаблону и редактирует офферы в существующих кампаниях.
Стек: FastAPI, SQLAlchemy 2.0, Alembic, фронт на HTML + jQuery. Python 3.11+.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # см. «Настройка» ниже
alembic upgrade head             # создать таблицы в БД (миграции)
uvicorn app.main:app --port 8000
```

Откройте http://127.0.0.1:8000.

## Настройка (`.env`)

Выберите один из вариантов.

**С настоящим Keitaro:** впишите `KEITARO_URL` (адрес трекера) и `KEITARO_API_KEY`
(Keitaro → Профиль → API ключи). У роли ключа должны быть права на офферы. Домен, группа и источник для новых
кампаний задаются в `KEITARO_DEFAULT_DOMAIN`, `KEITARO_DEFAULT_GROUP`, `KEITARO_DEFAULT_SOURCE`.

**Без Keitaro (демо):** поставьте `DEMO_MODE=true`. Появятся вымышленные офферы и кампании, ключ не нужен.
Подробнее: [docs/demo.md](docs/demo.md).

База данных: SQLite, файл `adrobot.db` создаётся рядом с проектом при `alembic upgrade head`. Ничего ставить не нужно.

## Как пользоваться

**New campaign** (`/create`): введите название, GEO (`AU` или `MX,AU,RO`), выберите оффер из подсказок и нажмите Create.
Будут созданы два потока: страна из GEO уходит на google.com, весь остальной трафик на выбранный оффер.
Галочка «Предпросмотр» показывает, что будет создано, ничего не отправляя в Keitaro.

**Editor** (`/edit`): найдите кампанию по ID или названию.

| Кнопка | Что делает |
|---|---|
| Fetch streams | загрузить потоки из Keitaro заново |
| Добавить / × | добавить или убрать оффер. Это только черновик: поток становится жёлтым, в Keitaro ничего не уходит |
| Push | отправить черновик потока в Keitaro |
| Cancel | отменить неопубликованные изменения |
| Bring back | вернуть удалённый (серый) оффер |
| 📌 | закрепить долю оффера; остальные офферы делят остаток поровну |

Доли делятся поровну: 3 оффера → 34 / 33 / 33.

## Тесты

```bash
pytest
```

Настоящий Keitaro для тестов не нужен.

## Подробнее

- [docs/api.md](docs/api.md): все эндпоинты и правила редактора
- [docs/demo.md](docs/demo.md): демо-режим
- [docs/testing.md](docs/testing.md): тесты и проверка в браузере
- [docs/keitaro_api_notes.md](docs/keitaro_api_notes.md): форматы запросов и ответов Keitaro
- Swagger на запущенном сервере: http://127.0.0.1:8000/docs
