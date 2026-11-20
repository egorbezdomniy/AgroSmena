# AgroSmena CRM: production-конфигурация и измерения, этап 1

Изменения подготовлены и проверены локально 16 октября 2026 года. Прочитан
`docs/CODEX_HANDOFF.md`, описание сверено с исходниками и текущим diff; применимых
`AGENTS.md` не найдено. При первоначальной подготовке дерево было чистым; при проверке
сохранены все подготовленные изменения. Действующий `.env`, реальные секреты,
пользовательские данные и существующий кластер проекта не использовались.

Проверки выполнялись с искусственной конфигурацией, временной статикой и отдельным
одноразовым PostgreSQL 16.2 на loopback. Разделы результатов ниже отличают настоящие
HTTP/SQL-проверки от unit-тестов с mock cursor. Хостинг, production PostgreSQL,
применённые там миграции и reverse proxy не проверены. Desktop UI, установщик и
нагрузочные испытания не запускались.

## Что подтверждено и изменено

- В `crmserver/crmserver/settings.py` действительно было `DEBUG = True` вопреки README.
  Теперь `DJANGO_DEBUG` разбирается строго, по умолчанию `false`. Неизвестное значение
  вызывает ошибку конфигурации без вывода значения. Допустимы `true/false`, `1/0`,
  `yes/no`, `on/off`, без учёта регистра и пробелов по краям.
- `SECRET_KEY` уже требовал переменную без fallback. Это сохранено; при `DEBUG=false`
  дополнительно запрещены короткий ключ (<50 символов), менее пяти разных символов,
  префиксы `django-insecure-` и `replace-with-`. Это минимальный барьер, не проверка
  случайности: production-ключ нужно сгенерировать независимо и хранить как секрет.
- Удалено автоматическое добавление домена хостинга. Production требует непустой
  `DJANGO_ALLOWED_HOSTS` без `*`; домен Render/custom domain задаётся явно. Loopback
  по умолчанию разрешён только при debug. Значения hosts задаются без схемы/пути.
- Параметризованы TLS, cookies, CSRF, proxy и PostgreSQL. Безусловное доверие
  proxy-заголовкам, HTTPS redirect и HSTS не включены. Сессионные/CSRF cookies
  по умолчанию secure в production; HttpOnly сессии и SameSite сохраняют defaults Django.
- WhiteNoise уже был в middleware и корневых зависимостях, но отсутствовал в
  `crmserver/requirements.txt`. Добавлен WhiteNoise 6.12.0 (эта версия также найдена
  в локальной установленной метаинформации), настроен compressed manifest storage.
  Загрузка зависимостей и установка не выполнялись.
- Существовали WSGI/ASGI entrypoints и Gunicorn в зависимостях; конфигурация
  production-запуска и health endpoint в исходниках не найдены. Добавлены явный
  необязательный `crmserver/gunicorn.conf.py` и `/healthz/` (GET/HEAD, только liveness,
  без обращения к БД, `Cache-Control: no-store`). Это не проверка готовности PostgreSQL.
- Компактные JSON-события направляются отдельным logger `crm.diagnostics` в stdout,
  без propagation. Предыдущие прикладные error loggers не перенастроены.
- В sync добавлены только диагностические обёртки. Исходный `@transaction.atomic`,
  `select_for_update`, порядок применения, проверки доступа, фильтрация задач,
  формат ответа и разрешение конфликтов сохранены. Схема БД не изменялась.
- `.gitignore` исключает `.env`/`.env.*`, сохраняя `.env.example`. Это не удаляет
  секреты, которые могли ранее попасть в историю Git.

Изменённые файлы:

| Файлы от корня репозитория | Назначение |
| --- | --- |
| `crmserver/crmserver/settings.py`, `env.py` | Production-настройки и строгий разбор переменных |
| `crmserver/crmserver/observability.py` | HTTP/SQL/sync diagnostics, JSON logger и request ID |
| `crmserver/synchronization/{views,services,urls}.py` | Замеры прежнего обмена и стабильное имя маршрута |
| `crmserver/crmserver/{health,urls}.py` | Liveness endpoint |
| `crmserver/gunicorn.conf.py`, `crmserver/requirements.txt` | Явный вариант WSGI-запуска, недостающий WhiteNoise |
| `crmserver/.env.example`, `.gitignore`, `crmserver/README.md` | Шаблон конфигурации, исключение секретных файлов, локальный debug |
| `crmserver/crmserver/test_observability.py` | Целевые тесты без реальных DB/server |
| `crmserver/crmserver/test_stage1.py`, `test_stage1_urls.py` | Проверки через Django middleware, ASGI и реальную PostgreSQL |
| `crmserver/crmserver/verification_settings.py` | Искусственные настройки с исключением `.env` и фиксированным loopback DB host |
| `crmserver/tools/verify_stage1_http.py` | Кратковременный WSGI HTTP smoke со статикой и автоматической остановкой |
| `crmserver/accounts/{tests,test_http}.py`, `crmserver/synchronization/tests.py` | Актуализация старых ожиданий и явные cookies для loopback HTTP-теста |
| `docs/scaling-stage-1.md` | Эксплуатация, агрегация, ограничения, откат и план проверок |

В таблице короткие имена `env.py` и `observability.py` относятся к тому же каталогу
`crmserver/crmserver/`. Серверный requirements сохранён в исходной кодировке UTF-16;
Git показывает его как binary diff, добавлена только строка `whitenoise==6.12.0`.

## Переменные окружения

Шаблон: `crmserver/.env.example`. Переменные процесса имеют приоритет над `.env`.
Для полного исключения чтения файла установить `DJANGO_LOAD_DOTENV=false` **в окружении
процесса до импорта settings**; запись этого флага внутри `.env` не исключает само чтение.
Не перезаписывать действующий `.env` шаблоном.

| Переменная | Default | Назначение |
| --- | --- | --- |
| `DJANGO_DEBUG` | `false` | Только для локальной разработки явно `true` |
| `DJANGO_LOAD_DOTENV` | `true` | При `false` вообще не вызывает load_dotenv; нужен в процессе для изолированных проверок |
| `DJANGO_SECRET_KEY` | нет | Обязателен всегда; production-проверка описана выше |
| `DJANGO_ALLOWED_HOSTS` | пусто в production; `127.0.0.1,localhost` в debug | Разрешённые hosts через запятую |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | пустой список | При необходимости доверенные origins со схемой, например `https://crm.example.test`; не отключает CSRF |
| `DJANGO_SESSION_COOKIE_SECURE` | `not DEBUG` | Cookie сессии только через HTTPS |
| `DJANGO_CSRF_COOKIE_SECURE` | `not DEBUG` | CSRF cookie только через HTTPS |
| `DJANGO_TRUST_PROXY_SSL_HEADER` | `false` | При явном включении доверяет `X-Forwarded-Proto: https` |
| `DJANGO_THROTTLE_NUM_PROXIES` | `0` | DRF игнорирует X-Forwarded-For; положительное целое — точное число доверенных hops после проверки инфраструктуры |
| `DJANGO_SECURE_SSL_REDIRECT` | `false` | HTTPS redirect после проверки инфраструктуры |
| `DJANGO_SECURE_HSTS_SECONDS` | `0` | HSTS отключён; целое >=0 |
| `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` | `false` | Только когда HTTPS работает на всех поддоменах |
| `DJANGO_SECURE_HSTS_PRELOAD` | `false` | Отдельное осознанное решение после проверки требований preload |
| `POSTGRES_DB/USER/PASSWORD/HOST/PORT` | `crmserver/crmserver/пусто/127.0.0.1/5432` | Существующие параметры PostgreSQL; реальные значения задаёт окружение |
| `POSTGRES_CONNECT_TIMEOUT` | `5` | Таймаут подключения в секундах, целое >=1 |
| `POSTGRES_CONN_MAX_AGE` | `0` | Секунды переиспользования соединения, целое >=0; это не pool |
| `POSTGRES_CONN_HEALTH_CHECKS` | `true` | Проверка пригодности переиспользуемого соединения |
| `POSTGRES_SSLMODE` | пусто, default libpq | `disable/allow/prefer/require/verify-ca/verify-full`; выбрать по требованиям провайдера |
| `POSTGRES_SSLROOTCERT` | пусто | Путь к доверенному CA для TLS PostgreSQL |
| `OBSERVABILITY_ENABLED` | `true` | Все диагностические события и SQL wrappers; request ID остаётся даже при `false` |
| `OBSERVABILITY_HTTP_SAMPLE_RATE` | `1` | Независимая вероятность HTTP-события, число 0..1 |
| `OBSERVABILITY_SQL_ENABLED` | `false` | Сбор SQL без DEBUG; отдельно от HTTP sampling |
| `OBSERVABILITY_SQL_SAMPLE_RATE` | `0.1` | Вероятность SQL-сбора для запроса при SQL_ENABLED, 0..1 |
| `OBSERVABILITY_SYNC_ENABLED` | `true` | Sync-событие для каждого обмена независимо от HTTP sampling |
| `OBSERVABILITY_EXCLUDE_ROUTES` | `healthz,app-update,static` | Имена маршрутов через запятую; подавляет только успешные HTTP-события |
| `GUNICORN_BIND` | `127.0.0.1:8000` | Bind, только при использовании добавленного Gunicorn config |
| `WEB_CONCURRENCY` | `1` | Консервативный один процесс из-за локального throttle; не проверенная рекомендация по производительности |
| `GUNICORN_TIMEOUT` | `30` | Таймаут worker в секундах; согласовать с proxy и временем sync |

Gunicorn читает свои переменные из окружения процесса до загрузки Django: задавать
их в панели хостинга/службе, а не только в Django `.env`. Существующие
`APP_UPDATE_CATALOG` и `APP_INSTALLER_DIR` и их defaults не менялись.

Для локального HTTP явно установить `DJANGO_DEBUG=true` и собственный ключ.
Cookie flags в шаблоне закомментированы, чтобы автоматически получить локальные defaults.
Для production оставить debug выключенным и проверить HTTPS перед переключением cookies.

## Условия безопасного деплоя

1. Проверить фактическую конфигурацию у владельца окружения. Задать сильный секрет,
   production hosts и параметры отдельной production PostgreSQL через secret storage.
   Сохранить действующий корректный SECRET_KEY: его смена инвалидирует сессии и sync-токены.
2. Проверить TLS termination. `DJANGO_TRUST_PROXY_SSL_HEADER=true` допустим только если
   приложение доступно исключительно через доверенный proxy, который удаляет клиентский
   `X-Forwarded-Proto` и выставляет собственный. `USE_X_FORWARDED_HOST` остаётся false.
   При прямом доступе клиента к приложению этот флаг оставлять false. Знать только имя
   провайдера недостаточно. Проверить CSRF, login, абсолютные HTTPS URLs и отсутствие
   redirect loops. HTTPS redirect включать после этого, если его ещё не обеспечивает edge.
3. HSTS включать постепенно только после проверки HTTPS, сроков сертификатов и поддоменов.
   Preload не включать автоматически. CSRF origins нужны только для фактических
   доверенных origins; не задавать wildcard для обхода ошибок.
4. Установить зависимости из серверного requirements и собрать статику `collectstatic`
   в окружении релиза до переключения трафика. Локальный collectstatic во временный
   каталог выполнен; это не проверка сборки статики на хостинге.
   Manifest storage при отсутствующем manifest/файле может выдавать ошибку; проверить
   все страницы и CSS/JS при DEBUG=false, а не маскировать проблему debug-режимом.
5. Для Linux WSGI можно явно использовать из каталога `crmserver`:
   `gunicorn -c gunicorn.conf.py crmserver.wsgi:application`.
   Linux-запуск не проверен: доступная Windows не имеет `fcntl`. Container hosting
   может требовать `GUNICORN_BIND=0.0.0.0:<port>`; универсального порта у проекта нет.
   Сначала сверить текущую launch command, число workers, память и лимиты соединений.
   Gunicorn не является Windows-сервером. ASGI entrypoint оставлен без смены сервера.
6. Настроить health check на `/healthz/` с разрешённым Host и корректной схемой HTTPS.
   Health не подтверждает работоспособность БД. Readiness БД проверять отдельно в
   закрытом эксплуатационном контуре; публичный endpoint внутренних метрик не добавлен.
7. У провайдера PostgreSQL выбрать TLS: `require` шифрует, `verify-full` также проверяет
   CA и имя сервера при корректном сертификате. Не выбирать режим вслепую. Начать с
   CONN_MAX_AGE=0; для WSGI менять по измерениям и лимиту подключений, учитывая все
   workers/threads/aliases/службы. Для ASGI сохранять 0. Данный этап pool не добавляет.
8. Настроить сбор stdout JSON, срок хранения и доступ операторов. Request ID использовать
   для поиска событий, не как метку метрики. Проверить отдельно логи edge/Gunicorn/Django:
   новые диагностические события не содержат данных, но прежние error/access logs
   не становятся автоматически обезличенными. В добавленном Gunicorn config access log
   отключён, чтобы не дублировать raw URLs и query strings.

## HTTP и SQL: смысл измерений

Middleware стоит первым: охватывает downstream middleware, auth, view, рендеринг DRF/
Templates, сессию и формирование ответа. Время считается `perf_counter`, timestamp
события — UTC wall clock. Длительности не включают очередь proxy/Gunicorn, получение
тела до входа в middleware и передачу ответа клиенту. Метод ограничен набором HTTP
methods (`OTHER` для остальных), маршрут — `resolver_match.view_name` либо шаблон,
а до разрешения маршрута — `unresolved`. WhiteNoise-ответы имеют фиксированный маршрут
`static` по STATIC_URL, чтобы исключать их успешные события без потери ошибок.
ID/slug из пути, query string не записываются.

`X-Request-ID` возвращается в ответе. Входной ID принимается только в UUID-формате
длиной 32 или 36, нормализуется в 32 hex; иначе создаётся новый UUID. Он недоверенный
и не служит доказательством идентичности/уникальности операции.

`duration_scope=response_ready` означает готовность обычного ответа.
`stream_response_ready` — только создание streaming-ответа; итератор не оборачивается,
его SQL, исключения и полная передача не измеряются. Незавершённые из-за аварийного
завершения worker запросы могут не оставить события; их ошибки искать на edge/хостинге.

SQL wrappers установлены на все настроенные aliases в текущем потоке, даже если
соединение впервые открывается во view. Счётчики создаются на каждый запрос, не
делятся между конкурентными запросами. Входят `CursorWrapper.execute/executemany`
в пределах middleware, включая неуспешные попытки, SQL auth и рендеринга.
`executemany` считается одним вызовом, его параметры не перебираются для статистики.
Суммарное SQL-время включает ожидание БД и блокировок внутри execute, но не отдельно
fetch, commit/rollback через драйвер, время подключения, прямой psycopg/callproc,
другие потоки/процессы и будущую итерацию streaming. Это не серверное CPU-время SQL.
SQL-текст, параметры, имена пользователей/организаций, UUID сущностей, cookies,
Authorization и тексты исключений не сохраняются. `DEBUG`/`force_debug_cursor`
ради измерения не включаются.

Текущие views синхронные. Middleware явно sync-only; при ASGI Django адаптирует цепочку
в thread-sensitive контексте текущего запроса, где выполняется синхронный ORM.
Новый async view, ORM в выделенном executor или параллельные задачи требуют отдельного
пересмотра границ сбора. Адаптация и полная middleware-цепочка проверены через
asyncio/AsyncClient с конкурентными запросами; отдельный ASGI-сервер не запускался.

При выключенном/не выбранном SQL-сборе `sql_sampled=false`, SQL-поля отсутствуют:
это не ноль запросов. При сбое установки wrapper `sql_collection_complete=false`:
такие частичные результаты исключать из SQL-агрегации. Ошибка диагностического sink
или сборщика не должна подменять ответ или бизнес-исключение; сообщение ошибки sink
специально не переписывается другим логгером с потенциальными данными.

## Sync: фазы и ограничения

Sync-событие создаётся для именованного `sync-exchange` до DRF auth/permissions.
Поэтому видны также отказы авторизации и ошибки парсинга/валидации. `duration_ms`
имеет те же серверные границы, что HTTP, включает auth, JSON parse/render и rollback;
это не полное сетевое время обмена и не desktop apply.

| Поле | Значение |
| --- | --- |
| `input_validation_ms` | Чтение `request.data`, парсинг и ExchangeSerializer; не поэлементная модельная валидация |
| `exchange_service_ms` | Вызов сервиса с прежней atomic-транзакцией, включая commit/rollback |
| `organization_lock_acquire_ms` | Весь ORM SELECT FOR UPDATE до возврата; включает ожидание, DB round-trip, decode |
| `organization_lock_observed_hold_ms` | От возврата SELECT FOR UPDATE до выхода atomic, включая commit/rollback |
| `lock_release_at_service_exit` | true при отсутствии внешней atomic; false означает отсутствие гарантии из-за внешней atomic; null при неизвестном контексте |
| `apply_ms` | Сортировка, проверки версий/связей, модельная валидация и применение входящих записей |
| `response_prepare_ms` | Выборка полного снимка, tombstones, участников и подготовка Python-ответа; без JSON render |
| `incoming_records/incoming_deletions` | Записи и подмножество tombstones в валидном входящем списке |
| `outgoing_records/outgoing_deletions` | Записи и подмножество tombstones в возвращаемом снимке; не число удалений за один обмен |
| `request_declared_bytes` | Доступный валидный Content-Length; null если нет/некорректен; не фактически прочитанный объём |
| `response_body_bytes` | Длина уже rendered content; без заголовков, framing, последующего сжатия proxy/TLS; null для streaming |
| `outcome` | success, validation_error, conflict (если уже возник HTTP409), database_error, authentication_error, permission_denied, throttled, client_error, server_error, other_error |

Отсутствие фазы/счётчика означает, что выполнение до неё не дошло. На невалидном
входе число записей не извлекается повторным чтением тела. Длительности завершённых
ошибкой фаз — время до ошибки; это не успешное применение. Счётчики описывают пакет,
а не число committed insert/update/delete. Каскадные удаления и пропуски старых версий
не названы фактическими удалениями/конфликтами. Прежний алгоритм newer-wins не изменён.

Чистое время ожидания блокировки недоступно из одного ORM-вызова: точной метрики
`lock_wait_ms` нет. `organization_lock_observed_hold_ms` немного короче реального
удержания из-за момента возврата SELECT. При внешней atomic это лишь наблюдаемая
часть: после успешного сервиса блокировка продолжится до внешнего commit. При ошибке
и rollback внутреннего savepoint приобретённая в нём блокировка может освободиться
раньше; false не доказывает, что она всё ещё удерживается. Не использовать значение
как точный hold при `lock_release_at_service_exit=false/null`. Текущий settings не включает
ATOMIC_REQUESTS. Новая обёртка стоит снаружи прежнего atomic и не перемещает его границы.

## Примеры обезличенных событий

Примеры иллюстративные, не результаты измерений окружения:

```json
{"timestamp":"2026-10-16T09:00:00+00:00","event":"http_request","request_id":"0123456789abcdef0123456789abcdef","method":"GET","route":"web:dashboard","status_code":200,"duration_ms":42.1,"duration_scope":"response_ready","sql_sampled":true,"sql_count":8,"sql_duration_ms":18.5,"sql_executemany_count":0,"sql_error_count":0,"sql_collection_complete":true,"sql_sample_rate":0.1,"sample_rate":1.0}
```

```json
{"timestamp":"2026-10-16T09:00:01+00:00","event":"sync_exchange","request_id":"fedcba9876543210fedcba9876543210","method":"POST","route":"sync-exchange","status_code":200,"duration_ms":320.0,"duration_scope":"response_ready","sql_sampled":false,"input_validation_ms":11.0,"exchange_service_ms":280.0,"organization_lock_acquire_ms":35.0,"organization_lock_observed_hold_ms":242.0,"lock_release_at_service_exit":true,"apply_ms":155.0,"response_prepare_ms":76.0,"incoming_records":120,"incoming_deletions":5,"outgoing_records":180,"outgoing_deletions":8,"request_declared_bytes":34000,"response_body_bytes":48000,"outcome":"success"}
```

## Как агрегировать и найти узкие места

Новый monitoring stack не разворачивается. Существующего стека метрик в просмотренном
коде не найдено; stdout собирает провайдер или существующий log collector оператора.
Общий поток нескольких workers/реплик объединять по времени/схеме события. Для каждой
рекомендации ниже сначала проверить доступные права/сервисы у провайдера.

**Приложение.** Взять индивидуальные `http_request` события в одинаковом окне времени,
группировать по method, route, duration_scope (при необходимости status class/release).
Считать p50/p95/p99 непосредственно из duration_ms или объединяемых histogram buckets.
Не усреднять локальные перцентили/средние workers. Для ошибки 5xx: количество HTTP
status>=500 / число HTTP-событий той же группы; 4xx считать отдельно.
HTTP sampling случайный, одинаковый для ошибок и успехов; при rate<1 оценка шумная,
особенно p99 и редкие ошибки. При смене rate разделять интервалы; для точной частоты
временно держать rate=1. Исключённые health/update успехи дают неполный denominator
этих маршрутов: удалить их из исключений или не рассчитывать их error rate по логам.
Не складывать HTTP и sync события как два запроса.

Из `sync_exchange` отдельно получать распределения фаз, duration, размеров и outcome,
частоту ошибок sync. Sync-события не сэмплируются, пока включены. Сопоставлять рост
lock acquire с apply/response prepare, SQL и размером снимков. Для SQL использовать
только sql_sampled=true AND sql_collection_complete=true; рассчитывать распределения
sql_count и sql_duration_ms, долю SQL во времени запроса с учётом их границ, а не
выдавать выборку за полный объём SQL. Нулевые и отсутствующие значения не смешивать.
При HTTP sampling<1 SQL-выборка в HTTP-событиях дополнительно прорежена HTTP sampling;
для sync это ограничение отсутствует.

Labels метрик ограничить event/method/route/status class/outcome/scope; значения
request_id, user/organization IDs, usernames, UUID, произвольные пути и exception
messages labels не становятся. Request ID — только поле трассировки с ограниченным
доступом. Публичный metrics endpoint не создан.

**PostgreSQL.** Через разрешённую консоль/метрики провайдера собирать:

- Число соединений и их states из агрегатов `pg_stat_activity`, лимит max_connections,
  lock waits по `wait_event_type='Lock'` и `pg_locks`; sampling активности показывает
  присутствие ожидания, не точную длительность отдельного lock в приложении.
- `pg_database_size(current_database())` — размер БД. `pg_stat_wal.wal_bytes` с delta
  по времени/учётом сброса статистики — генерация WAL; это не размер WAL на диске.
  Занятый WAL storage, replication lag/retention/slots — через метрики провайдера либо
  доступные администратору представления/функции. Права и версия БД неизвестны.
- Если провайдер поддерживает `pg_stat_statements`, оператор отдельно согласует
  preload/extension и возможный restart. Сравнивать calls, total/mean_exec_time,
  rows и I/O на одном интервале; это агрегаты statements, из них нельзя получить
  p95/p99 HTTP. Query text не отправлять в диагностический logger: даже нормализованный
  текст и ручной SQL могут раскрывать данные. Для дорогих statements анализировать
  планы на разрешённой копии; EXPLAIN ANALYZE исполняет запрос и отдельно согласуется.

**Хостинг.** CPU, RSS/пиковая память каждого worker и контейнера, OOM/restarts, диск,
I/O, очередь/edge latency и network bytes брать из метрик платформы/ОС. Приложение
не добавляет псевдо CPU/RAM из HTTP времени. Сопоставлять одинаковые интервалы:
большое lock acquire без CPU может указывать на конкуренцию; большой response prepare
с ростом записей — на полные снимки; разница edge и app latency — на очередь/сеть.
Это гипотезы для проверки, а не установленные причины проблем production.

## Накладные расходы и выключение

На запрос создаются небольшой state и request ID; HTTP-событие даёт одну JSON-строку.
Sync добавляет таймеры фаз и линейный подсчёт deletion flags в уже готовых списках,
без дополнительного ORM, повторного JSON render или чтения request.body.
SQL wrapper делает измерение и обновляет несколько чисел на execute; список запросов
не хранится. Sampling выбирается до обработки запроса и не зависит от его результата.
Нет полного профилирования или обещания нулевого overhead. Объём логов, CPU и latency
нужно сравнить разрешённым экспериментом на отдельном окружении.

Включить SQL: `OBSERVABILITY_SQL_ENABLED=true`, начать с `OBSERVABILITY_SQL_SAMPLE_RATE=0.1`,
для короткого контролируемого окна — 1.
Выключить только SQL: `OBSERVABILITY_SQL_ENABLED=false`. HTTP rate=0 отключает
HTTP-события; sync выключается отдельно. `OBSERVABILITY_ENABLED=false` отключает
оба вида событий и SQL wrappers, сохраняя заголовок request ID. Изменения окружения
требуют перезапуска workers.

## Откат

Сначала выключить диагностику флагом, перезапустить workers и проверить операционные
показатели. При проблеме конкретного TLS/cookie/proxy параметра вернуть его ранее
согласованное значение: proxy trust=false, redirects=false, HSTS=0 по умолчанию;
не включать DEBUG для диагностики production. Secure cookies выключать только для
согласованного локального HTTP, а не как обход неправильного TLS в production.
Выключение HSTS на сервере не снимает уже закэшированную политику у браузеров;
preload имеет отдельный длительный процесс удаления.

При необходимости откатить код релизом к сохранённой версии и соответствующему
артефакту статики/зависимостей/launch config. Сохранить действующие секреты и hosts;
не возвращать прежний DEBUG=True при таком откате — оставить отдельную безопасную
настройку. Новых миграций в этом этапе нет, откат схемы не требуется. Не менять
существующие данные или журнал tombstones ради отката диагностики.

## Фактически выполненные проверки

Среда: Python 3.13.2 / Windows; Django 6.0.7, DRF 3.17.1, psycopg 3.3.5,
WhiteNoise 6.12.0, asgiref 3.12.1, python-dotenv 1.2.3. Установлен Gunicorn 26.2.0,
но его runtime на этой ОС недоступен. Зависимости при проверке не переустанавливались.

`crmserver.verification_settings` до импорта основных settings удаляет унаследованные
application/PG-параметры, задаёт искусственный ключ, DEBUG=false, тестовые hosts,
DJANGO_LOAD_DOTENV=false, временные STATIC_ROOT/MEDIA_ROOT/пути обновлений и профиль
тестовых SQLite-сервисов. Пользовательский `.env` исключён из пути загрузки,
а не просто перекрыт. Отдельный тест запрещает вызов load_dotenv при выключенном флаге.

Для DB-тестов создан **новый кластер**, не база внутри пользовательского сервера:
initdb PostgreSQL 16.2, отдельный каталог, свободный 127.0.0.1-порт, искусственный
пользователь stage1_test. Бинарные файлы взяты из установленного ПО; его службы и
каталоги данных не использовались. Trust auth был только у этого временного loopback
кластера, не production. Django runner создаёт/мигрирует/удаляет только
`test_stage1_disposable`; новые данные исключительно синтетические.
После проверок сервер остановлен (pg_ctl exit 0), оба созданных временных каталога
кластера удалены. Логи результатов и собранная статика сохранены в отдельном каталоге
артефактов задания; ни PostgreSQL-сервер, ни HTTP smoke не оставлены работающими.

| Проверка | Фактический результат |
| --- | --- |
| Первые целевые unit-тесты | 18/18 успешно; здесь SQL cursor mock, это не подтверждение БД |
| Расширенный целевой прогон с PostgreSQL и двумя исправленными регрессионными кейсами | 36/36 успешно |
| Финальная полная регрессия accounts/web/crmserver/synchronization | **80/80 успешно**, 182.770 с, exit 0; тестовая БД удалена runner |
| `manage.py check --deploy` | Exit 0; ровно security.W004 и security.W008, ошибок нет |
| `collectstatic --noinput` | 167 файлов скопировано, 479 post-processed; временный каталог |
| Manifest и используемые шаблонами assets | Manifest содержит 167 mappings и hash; ссылки web/accounts/catalog проверяются отдельным тестом |
| Настоящий временный WSGI HTTP | /healthz/ 200, чужой Host 400, лендинг 200, X-Request-ID корректен |
| Настоящий HTTP/WhiteNoise | Обе CSS/JS-ссылки лендинга 200, immutable caching; gzip CSS декодируется |
| Django ASGI chain | AsyncClient и конкурентный thread-sensitive сценарий пройдены, без отдельного ASGI-сервера |

W004 означает отсутствие HSTS: его можно включать только после проверки реального
HTTPS и сертификатов, иначе браузеры могут надолго потерять доступ. W008 означает
отсутствие Django HTTPS redirect: владелец должен подтвердить redirect на edge либо
после проверки схемы настроить его в Django. Warnings не скрыты и настройки не
включались ради зелёного check. Cookie flags при DEBUG=false действительно secure;
их выдача, явная proxy scheme trust и redirect проверены через настоящую middleware
цепочку с синтетическими заголовками, без утверждения о реальном HTTPS.

Целевые проверки утверждают наблюдаемые ответы и события: 500 после исключения,
request ID в ответе, отсутствие текстов SQL/параметров/тестовых приватных значений,
нулевые утечки состояния между последовательными/конкурентными запросами,
отсутствие SQL-полей при sampling miss, работу отключения и отказа logger.
Реальная PostgreSQL отдельно проверяет SELECT и division-by-zero, следующий успешный
запрос после ошибки, конкурентные HTTP со счётчиками 1 и 3 и очищенные execute_wrappers.
Mock-тесты дополнительно покрывают aliases/executemany без чтения параметров.

Реальный sync проверен через HTTP/DRF: прежние ключи ответа и записей, размеры уже
rendered content, counts, rollback ранее применённой записи при ошибке следующей.
Задачи общие/свои/назначенные коллеге и другой организации проверены на API, сайте
и в sync. В двух конкурирующих обменах одной организации PostgreSQL
`pg_stat_activity.wait_event_type='Lock'` подтвердил настоящее ожидание второго,
пока успешный первый обмен уже вернулся, но внешняя atomic ещё не завершилась.
После её завершения второй обмен прошёл; флаги внешней/самостоятельной atomic и
границы наблюдаемого hold проверены. Чистое lock wait из ORM по-прежнему не заявляется.

## Найденные и исправленные дефекты

- Нет способа исключить `.env` до его чтения: добавлен DJANGO_LOAD_DOTENV и отдельный
  verification settings; ни один исполняемый прогон не использовал действующий файл.
- Default DRF NUM_PROXIES=None доверял произвольному X-Forwarded-For при throttle.
  Теперь default 0, положительное число hops задаётся явно. Одиннадцать запросов
  с разными поддельными XFF в тесте дают десять validation errors и затем 429:
  подмена заголовка не сбрасывает корзину.
- WhiteNoise-события ранее попадали в unresolved и создавали шум: добавлен фиксированный
  static route и исключение его успешных событий, с сохранением ошибок статики.
- Default Gunicorn workers=2 не учитывал процессный throttle. Default снижен до одного
  sync worker как консервативный вариант; это не измеренная конфигурация мощности.
  Workers/timeout теперь разбираются как положительные числа с безопасным текстом ошибок.
- Старый regression test ожидал logout на /login/, хотя исходный settings уже задавал
  web:landing. Исправлено ожидание на / с дополнительной проверкой выхода из сессии.
- Старый sync test обращался к token у уже удалённого клиента. Теперь проверяются и
  self.sync.client is None, и очищенный token ранее сохранённого объекта. Бизнес-код
  logout, sync access, конфликты и транзакции не менялись.
- Настройки SecurityMiddleware кешируются при создании цепочки. Proxy/redirect тест
  исправлен на создание нового Client внутри override_settings; первая попытка
  выявила дефект тестового harness, а не production redirect.
- Реальный HTTP-тест авторизации теперь явно выключает secure cookies только в своей
  loopback test class. Production defaults не ослаблялись ради cleartext тестирования.

## Заблокированные и не выполнявшиеся проверки

- В Windows-сетевой песочнице asyncio зависал в создании socketpair до ASGI-кода,
  а initdb — на пробном backend. Stack trace подтвердил точное место. С разрешённым
  выполнением вне песочницы оба сценария прошли. Первое размещение во временном
  каталоге sandbox также оказалось недоступно дочерним процессам; артефакты перенесены
  в отдельный разрешённый каталог задания. Эти неуспешные попытки не засчитаны как pass.
- `python -m gunicorn --check-config ...` завершился до загрузки приложения:
  `ModuleNotFoundError: No module named 'fcntl'`. Конфигурация проверена статически и
  отдельным тестом значений, но это не Linux/Gunicorn runtime check.
- Не проверены реальные HTTPS termination, sanitization proxy headers, TLS PostgreSQL,
  production limits/секреты/миграции, расширения pg_stat_statements и метрики хостинга.
- Не выполнялись нагрузка, сравнение overhead on/off, проверка больших реальных
  снимков и принудительное убийство Gunicorn worker. Малые функциональные тесты не
  доказывают пригодность timeout=30 и числа workers для production.

## Throttle и timeout: условия первого деплоя

По исходникам Django default cache — LocMemCache, DRF ScopedRateThrottle читает и
записывает историю через неатомарные get/set. Поэтому 10/min не является единым
строгим лимитом нескольких workers/реплик; перезапуск очищает историю, конкурентные
запросы могут проходить сверх лимита. Один sync worker сокращает проблему разделения
памяти, но не заменяет защиту на периметре и не делает throttle распределённым.
Для пробного окружения допустим один worker/одна реплика с ограниченным доступом.
До публичного production владелец должен подтвердить общую защиту login endpoints
на доверенном edge или отдельно спроектировать общий limiter. Redis в этом этапе нет.

NUM_PROXIES=0 не доверяет XFF, но за proxy все пользователи могут попасть в корзину
REMOTE_ADDR самого proxy. Для production установить **точное** число hops только
после подтверждения, что путь до приложения закрыт от прямого доступа и XFF
перезаписывается/нормализуется доверенной инфраструктурой. Это отдельная настройка
от доверия X-Forwarded-Proto; безопасное значение невозможно угадать по домену хостинга.

В установленном Gunicorn 26.2.0 timeout=30 — срок молчания worker; sync worker не
посылает heartbeat во время обработки одного запроса. Полный sync с lock wait,
apply, подготовкой снимка и JSON может превысить его. Входной лимит 10 000 записей
не ограничивает размер исходящего снимка и бессрочных tombstones. Убийство worker
может оставить 5xx/потерянный ответ без итогового app event. До commit PostgreSQL
откатит незавершённую транзакцию при закрытии подключения, но если commit уже прошёл,
потерянный ответ не означает rollback — это нужно учитывать при повторном обмене.

Timeout оставлен 30, произвольно не увеличен и не отключён. До production нужны
измерения репрезентативного полного sync и конкуренции на отдельном окружении,
бюджет очереди/ожидания/ответа, согласование timeout клиента, edge и Gunicorn и
наблюдение за worker kills/5xx на платформе. Единственный worker также может задержать
health check за длинным sync: согласовать политику health/restart по этим измерениям.
Пока таких измерений нет, большой/неограниченный production sync не считается проверенным.

## Повторение проверок и действия владельца production

Для повторения создать новый временный каталог артефактов, задать в процессе
STAGE1_VERIFY_ROOT и DJANGO_SETTINGS_MODULE=crmserver.verification_settings.
Для DB-тестов отдельно поднять **новый одноразовый** PostgreSQL с пользователем
stage1_test на свободном loopback-порту и передать STAGE1_VERIFY_PGPORT.
По умолчанию порт равен 1: случайного подключения к рабочей PostgreSQL нет.
Не подставлять порт существующего/production сервера. Выполненные команды из crmserver:

```text
python manage.py check --deploy
python manage.py collectstatic --noinput --verbosity 1
python manage.py test accounts web crmserver synchronization --noinput -v 1
python tools/verify_stage1_http.py
```

Для standalone tools/verify_stage1_http.py добавить каталог crmserver в PYTHONPATH.
HTTP smoke сам поднимает/останавливает loopback WSGI и не обращается к БД. После
DB-прогона остановить только свой кластер; временные артефакты можно убрать отдельно.
Не запускать test_stage1 без собранной статики в том же STATIC_ROOT: её отсутствие
должно дать ошибку проверки manifest, а не скрытый skip.

До production владелец выполняет Linux/Gunicorn runtime check, проверяет TLS/proxy
headers и NUM_PROXIES, задаёт секрет/hosts/DB TLS, собирает статику на релизе, обеспечивает
общую защиту входа, подтверждает соединения/память/timeout репрезентативными измерениями,
настраивает сбор обезличенных логов и откат. Миграции production проверяются отдельно,
автоматическое применение к существующим базам этой работой не выполнялось.

## Кандидаты следующего этапа

- `synchronization/services.py:exchange` и `app/services/sync_service.py`: полные
  снимки и бессрочные tombstones увеличивают apply/response/размеры с ростом данных.
  Обосновать delta sync метриками, сохраняя отдельный дизайн конфликтов/удалений.
- `synchronization/services.py`, `crmserver/models.py`, `synchronization/signals.py`:
  общий lock организации охватывает применение и подготовку снимка; обычные записи
  конкурируют с sync. Сначала оценить acquire/hold и wait events PostgreSQL.
- `synchronization/services.py`: поиск obj/tomb/связей, сериализация отдельных записей
  и повторная модельная валидация могут давать много SQL. Это кандидат по структуре
  цикла; профиля репрезентативной production-нагрузки пока нет, индексы и bulk changes не добавлялись.
- `synchronization/views.py:LoginView`/settings: throttle использует локальный cache
  процесса; несколько workers не дают общего лимита. Убрано неявное доверие XFF,
  распределённый limiter остаётся вне этапа.
- `catalog/models.py` и `catalog/views.py`: изображения хранятся в PostgreSQL — оценить
  влияние на размер БД, WAL и выдачу по метрикам перед изменением хранения.
- `crmserver/requirements.txt`: общий набор desktop/build зависимостей и неприкреплённый
  Gunicorn увеличивают deploy surface; выделение минимальных server requirements
  отдельно согласовать. В этом этапе добавлена лишь уже используемая зависимость WhiteNoise.

## Основания выбора механизмов

- [Django 6: execute_wrapper, thread-local scope](https://docs.djangoproject.com/en/6.0/topics/db/instrumentation/).
- [Django: deployment checklist](https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/).
- [WhiteNoise: Django и manifest storage](https://whitenoise.readthedocs.io/en/stable/django.html).

Механизмы wrapper, sync/async adaptation, DRF throttle и Gunicorn timeout также
сверены с установленными исходниками; выполненные запуски перечислены выше.

## Вердикт

Этап готов к **пробному деплою на отдельное ограниченное окружение** после проверки
Linux/Gunicorn startup на нём. Локально подтверждены конфигурация, диагностика без DEBUG,
реальные HTTP/SQL и регрессии доступа/sync. Production-ready runtime не объявляется:
для production обязательны перечисленные выше проверки TLS/proxy и IP chain, общая
защита входа, бюджет timeout полного sync, лимиты ресурсов и release smoke на хостинге.
