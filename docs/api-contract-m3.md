# Контракт API модуля 3 — каталог услуг, цены, посты, запчасти

Префикс `/api/v1`. Ошибки и авторизация — как в модуле 1. Деньги и часы — **строки-десятичные** (`"1500.00"`, `"1.50"`), числа JSON не используются.

## Права
| Ресурс | director | manager | mechanic |
|---|---|---|---|
| Категории, услуги, запчасти: чтение | ✓ | ✓ (цена — своей точки, см. ниже) | 403 |
| Категории, услуги, запчасти, цены: запись | ✓ | 403 | 403 |
| Посты: чтение | все точки | свои точки | свои точки |
| Посты: запись | ✓ | 403 | 403 |

## Типы
- `Department` = `"service"|"detailing"`
- `Category` = `{id, name, department, sort_order: int, is_active}`
- `Service` = `{id, category_id, code, name, description: str|null, department, unit: "pcs"|"hour"|"set"|"sqm", base_price, norm_hours, duration_minutes: int, is_active, price: str}` — `price` = эффективная цена для точки из параметра `location_id` (цена точки, иначе `base_price`); без `location_id` равна `base_price`. Менеджер обязан передавать `location_id` из своих точек, иначе 422; для чужой точки — 404.
- `ServicePrice` = `{service_id, location_id, price, updated_at}`
- `Post` = `{id, location_id, name, post_type: "lift"|"diagnostics"|"detailing_box"|"wash"|"other", department: "service"|"detailing", sort_order, is_active}`
- `Part` = `{id, sku, name, brand: str|null, barcode: str|null, unit: "pcs"|"l"|"ml"|"kg"|"g"|"m"|"set", department: "service"|"detailing"|"both", sale_price, is_active}`
- `Page<T>` = `{items: T[], total: int}`

## Категории
- `GET /service-categories?department=&is_active=` → `Category[]`
- `POST /service-categories` `{name, department, sort_order?}` → 201; дубль `(department,name)` → 409 `unique_violation`
- `PATCH /service-categories/{id}` `{name?, sort_order?, is_active?}` → `Category` (department не меняется)

## Услуги
- `GET /services?search=&category_id=&department=&is_active=&location_id=&limit=50&offset=0` → `Page<Service>`
- `POST /services` `{category_id, code, name, description?, unit, base_price, norm_hours?, duration_minutes}` → 201 `Service`; дубль code → 409 `unique_violation`; `department` берётся из категории
- `GET /services/{id}?location_id=` → `Service`
- `PATCH /services/{id}` — любые поля создания кроме `code` и `category_id` + `is_active` → `Service`

## Цены по точкам (director)
- `GET /service-prices?location_id=` → `ServicePrice[]` (все переопределения точки)
- `GET /services/{id}/prices` → `ServicePrice[]` (по всем точкам)
- `PUT /services/{id}/prices/{location_id}` `{price}` → `ServicePrice` (создаёт или обновляет)
- `DELETE /services/{id}/prices/{location_id}` → 204 (возврат к базовой цене)

## Посты
- `GET /locations/{location_id}/posts?is_active=` → `Post[]` (чужая точка → 404)
- `POST /locations/{location_id}/posts` `{name, post_type, department, sort_order?}` → 201 `Post`; дубль имени в точке → 409 `unique_violation`
- `PATCH /posts/{id}` `{name?, post_type?, department?, sort_order?, is_active?}` → `Post`

## Запчасти и материалы (справочник без остатков)
- `GET /parts?search=&department=&is_active=&limit=50&offset=0` → `Page<Part>`
- `POST /parts` `{sku, name, brand?, barcode?, unit, department, sale_price}` → 201 `Part`; дубль sku/barcode → 409 `unique_violation`
- `PATCH /parts/{id}` — поля создания кроме `sku` + `is_active` → `Part`

Текстовые поля — `SafeText`; поиск — с экранированием `%` и `_`.
