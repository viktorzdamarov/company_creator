# Тестирование

## Автотесты

```bash
pytest
```

Keitaro в тестах имитируется, настоящий трекер не нужен. Покрыто: создание кампании, редактор (добавление, Push,
Cancel, Bring back, Pin, повторный Fetch), расчёт долей, ошибки Keitaro (403, 404, таймауты), DEMO-режим.

## Проверка подключения к настоящему Keitaro

Только чтение, ничего не меняет:

```bash
python -m scripts.keitaro_smoke            # справочники, офферы, дефолты из .env
python -m scripts.keitaro_smoke 215521     # + потоки и статистика кампании (укажите свой ID)
```

## Браузерные сценарии

Нужны Node.js 18+ и Edge/Chrome. Сервер запускается отдельно.

```bash
cd tests/e2e && npm install
ADROBOT_URL=http://127.0.0.1:8000 npm test       # общий smoke: форма, автокомплит, dry-run, редактор без Push
ADROBOT_URL=http://127.0.0.1:8000 npm run demo   # полный сценарий редактора, только для DEMO-режима
```

Для `npm test` нужна кампания с потоком офферов. Её имя задаётся в `ADROBOT_CAMPAIGN`, оффер для автокомплита
в `ADROBOT_OFFER_QUERY` и `ADROBOT_OFFER_ID`. Для Chrome укажите `BROWSER_PATH=...`.
Пример для DEMO: `ADROBOT_CAMPAIGN=demo_campaign_001 ADROBOT_OFFER_QUERY=aurora ADROBOT_OFFER_ID=9001`.
