# Keitaro Admin API — проверенные форматы

Проверено на реальном трекере (Keitaro 10.3.x) запросами только на чтение, 2026-11-19.
Документация API доступна в админке: Профиль → API ключи → «Документация».

## Общее

- База: `<KEITARO_URL>/admin_api/v1`
- Авторизация: заголовок `Api-Key: <ключ>`
- Списки возвращаются JSON-массивом, без пагинации.
- Ошибки:
  - неверный ключ → `401 {"error":"Invalid API key"}`
  - несуществующая сущность → `404` с **HTML-страницей nginx**, а не JSON
  - клиент превращает это в `KeitaroAuthError` / `KeitaroNotFoundError` (см. `app/keitaro/errors.py`)

## Справочники

| Запрос | Нужные поля |
|---|---|
| `GET /domains` | `id`, `name` (`kylovoa.com`), `is_ssl` |
| `GET /groups?type=campaigns` | `id`, `name` (`FORTESTS` → id 10332) |
| `GET /traffic_sources` | `id`, `name` (`FORTESTS` → id 836) |
| `GET /offers` | `id`, `name`, `state`, `country[]` |
| `GET /offers/{id}` | один оффер, 404 если нет |

Серверного поиска по офферам нет — автокомплит фильтрует список локально (`KeitaroClient.search_offers`).

## Кампания

`GET /campaigns/{id}`:
```json
{
  "id": 215521, "alias": "test_freefaint_editor_demo", "name": "...",
  "type": "position", "state": "active",
  "domain_id": 1813, "domain": "https://kylovoa.com/",
  "group_id": 10332, "group": "FORTESTS",
  "traffic_source_id": 836,
  "cost_type": "CPC", "cost_value": 0, "cost_currency": "USD"
}
```
Tracking URL = `domain` + `alias` → `https://kylovoa.com/test_freefaint_editor_demo`.

## Потоки (streams = flows в UI)

`GET /campaigns/{id}/streams` — массив, порядок по `position`.

Поток 1 — гео на Google:
```json
{
  "id": 1326840, "type": "regular", "position": 1, "state": "active",
  "schema": "redirect", "action_type": "http", "action_payload": "https://www.google.com/",
  "filters": [{"name": "country", "mode": "accept", "payload": ["AU"]}],
  "offers": []
}
```

Поток 2 — офферы:
```json
{
  "id": 1326841, "type": "default", "position": 2, "state": "active",
  "schema": "landings", "action_type": "do_nothing",
  "filters": [],
  "offers": [{"id": 2081195, "offer_id": 18813, "share": 100, "state": "active"}]
}
```
`share` — процент оффера в потоке (в редакторе — равномерно 100/N).

## Статистика по потокам

`POST /report/build`:
```json
{
  "range": {"interval": "all_time", "timezone": "Europe/Moscow"},
  "dimensions": ["stream_id"],
  "measures": ["clicks", "campaign_unique_clicks", "bots"],
  "filters": [{"name": "campaign_id", "operator": "EQUALS", "expression": 215521}]
}
```
Ответ: `{"rows": [{"stream_id": .., "clicks": .., "campaign_unique_clicks": .., "bots": ..}], "total": N}`.
Соответствует колонкам «Клики / Уник. / Боты».

## Создание кампании (проверено на этапе 3)

Кампания `adrobot-test-au-1` (id 215534) создана этими запросами; Keitaro не создаёт потоки
автоматически — после создания у кампании ровно 2 наших потока.

`POST /campaigns`:
```json
{"name": "adrobot-test-au-1", "alias": "Xiw4ra31", "type": "position", "state": "active",
 "domain_id": 1813, "group_id": 10332, "traffic_source_id": 836,
 "cost_type": "CPC", "cost_value": 0, "cost_currency": "USD", "cost_auto": true}
```
`alias` генерируем сами (8 символов `[A-Za-z0-9]`); ответ — объект кампании.

`POST /streams` (поток 1):
```json
{"campaign_id": 215534, "type": "regular", "name": "AU → Google", "position": 1, "state": "active",
 "schema": "redirect", "action_type": "http", "action_payload": "https://google.com",
 "collect_clicks": true, "filter_or": false,
 "filters": [{"name": "country", "mode": "accept", "payload": ["AU"]}]}
```

`POST /streams` (поток 2):
```json
{"campaign_id": 215534, "type": "regular", "name": "Офферы", "position": 2, "state": "active",
 "schema": "landings", "action_type": "do_nothing", "collect_clicks": true, "filter_or": false,
 "filters": [], "offers": [{"offer_id": 18813, "share": 100, "state": "active"}]}
```

Время: `POST /campaigns` ≈ 2.5 с, каждый `POST /streams` ≈ 0.3–0.4 с.

## Ещё не проверено (этап 4)

`PUT /streams/{id}` (обновление `offers[].share`). `DELETE /campaigns/{id}` (откат при сбое) в коде есть,
вживую не вызывался — проверено только на моках.

## Особенности трекера

- Трекер общий: в нём есть кампании других пользователей. Изменять можно только свои тестовые кампании.
- Домен со скриншотов ТЗ (`in.posdk.xyz`) здесь отсутствует; единственный домен — `kylovoa.com`.
- API-ключу виден 1 оффер (`18813`).
