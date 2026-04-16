# 🤖 assistant_tg_message

> Telegram-бот, который отвечает клиентам в вашей личке **от вашего имени** через AI, имитируя живое общение.

Подключается к вашему Telegram-аккаунту через **Telegram Business** и автоматически отвечает на сообщения клиентов, используя Claude (или DeepSeek). Буферизирует несколько подряд идущих сообщений в один ответ, добавляет случайную задержку, показывает «печатает...» и напоминает о себе через follow-up, если клиент не отвечает.

Построен на **aiogram v3**, PostgreSQL, Redis и Docker.

---

## ✨ Что умеет

- 🔌 **Telegram Business integration** — подключается к вашему Business-аккаунту через Settings → Business → Chatbots и обрабатывает события `business_connection`, `business_message`, `edited_business_message`, `deleted_business_messages`.
- 🧠 **AI-ответы от Claude / DeepSeek** — абстракция провайдера с фабрикой по префиксу модели (`claude-*` → Claude, `deepseek-*` → DeepSeek с автоматическим fallback на Claude, если ключ не задан).
- 🧩 **Prompt caching Claude** — статичная часть системного промпта (base + knowledge) помечается `cache_control: ephemeral`, динамическая (кастомные инструкции владельца) идёт последним блоком.
- 💬 **Имитация живого человека** — буферизирует входящие сообщения клиента, ждёт 15–25 секунд после последнего, потом показывает typing-индикатор (обновляется каждые 4 сек) пропорционально длине ответа и отправляет **одно** сообщение.
- 🤐 **Автопауза при ручном ответе владельца** — если вы сами пишете клиенту в чат, бот молчит. Следующее сообщение клиента снова активирует AI.
- 📬 **Follow-up напоминания** — если клиент не отвечает в течение `FOLLOWUP_DELAY_MINUTES`, бот аккуратно напоминает о себе. Ограничено `FOLLOWUP_MAX_COUNT` попытками.
- 📚 **Кастомный системный промпт и база знаний на пользователя** — поля `User.system_prompt`, `User.ai_model`, `User.max_history_messages` и таблица `user_knowledge_texts` (плейсхолдер под будущий админ-UI).
- 💸 **Token-budget-aware context manager** — обрезает историю попарно, уважая `MAX_CONTEXT_TOKENS`, `MAX_KNOWLEDGE_TOKENS`, `MAX_HISTORY_MESSAGES`, считает токены через `tiktoken` (offline).
- 🐳 **Docker-стэк** — PostgreSQL 15, Redis 7, асинхронный SQLAlchemy 2.0, кастомная система миграций, запуск от непривилегированного пользователя.
- 👨‍💼 **Админ-панель** — `/admin` для рассылок и базовой статистики (наследство от базового шаблона).
- 🗂️ **Local Bot API (опционально)** — поддержка файлов до 2 ГБ при включении `USE_LOCAL_API=true`.

---

## 🔄 Как это работает

```
 ┌─────────┐   business_message   ┌──────────────────┐
 │ Клиент  ├─────────────────────▶│ Telegram Bot API │
 └─────────┘                      └────────┬─────────┘
                                           │
                                           ▼
                                 ┌──────────────────┐
                                 │ BusinessMiddleware│  ← инъекция repo / AI / ctx / buffer
                                 └────────┬─────────┘
                                          │
                                          ▼
                               ┌────────────────────┐
                               │ handlers/business/ │  ← различаем owner vs client
                               └────────┬───────────┘
                       клиент           │           владелец
               ┌──────────────┘         │            └───────────┐
               ▼                        ▼                        ▼
     HumanResponseService        save assistant         НИЧЕГО НЕ ОТПРАВЛЯЕМ
     (буфер 15–25 сек,           + reset followup       (владелец сам пишет)
      потом callback)
               │
               ▼
     ContextManager ── trim history by tokens ──▶  AI Provider (Claude / DeepSeek)
                                                          │
                                                          ▼
                                                  typing_loop + send_message
                                                  (от имени владельца!)
                                                          │
                                                          ▼
                                             save assistant + schedule followup
```

Параллельно работает `FollowupScheduler` — фоновая корутина, которая раз в минуту проверяет диалоги, в которых бот писал последним и клиент долго не отвечает, и отправляет ненавязчивое напоминание.

---

## 📋 Требования

- Docker + Docker Compose v2
- Python 3.11+ (только для скриптов `scripts/init_project.py`, `scripts/deploy.py`)
- `just` или `make` для удобного управления командами
- Telegram-аккаунт с включённым **Telegram Business** (требует Telegram Premium)
- API-ключ Anthropic (`ANTHROPIC_API_KEY`) — обязательно
- API-ключ DeepSeek (`DEEPSEEK_API_KEY`) — опционально

---

## 🚀 Быстрый старт

### 1. Клонируем и конфигурируем

```bash
git clone git@github.com:aislam23/assistant_tg_message.git
cd assistant_tg_message
cp .env.example .env
```

Откройте `.env` и заполните минимум:

```env
BOT_TOKEN=123456:AAA...           # от @BotFather
BOT_USERNAME=my_assistant_bot     # username бота без @
ADMIN_USER_IDS=[123456789]        # ваш Telegram ID

POSTGRES_PASSWORD=<сильный_пароль>

ANTHROPIC_API_KEY=sk-ant-...      # обязательно
CLAUDE_MODEL=claude-sonnet-4-5-20250929
```

### 2. Запускаем сервисы

```bash
just dev-d       # или: make dev-d
just logs-bot    # смотрим логи бота
```

Миграции применяются автоматически при старте.

### 3. Подключаем бота к Business-аккаунту

1. В Telegram (мобильный или desktop) откройте **Settings → Business → Chatbots**.
2. Введите username бота (тот, что в `BOT_USERNAME`), **выдайте полные права на чтение и отправку сообщений**.
3. Бот пришлёт вам приветственное сообщение в приват — это подтверждение, что связка работает.

Теперь любое сообщение от клиента в вашей личке будет обрабатываться ботом.

### 4. Проверяем

1. С другого аккаунта (клиент) отправьте вам 2–3 сообщения подряд.
2. Подождите 15–25 секунд → появится индикатор «печатает...» → придёт **одно** объединённое сообщение от вашего имени.
3. Если вы сами напишете клиенту в этот чат, бот замолчит.

---

## ⚙️ Конфигурация

Все настройки — в `.env`. Полный список с дефолтами см. в `.env.example`. Ключевые группы:

### AI

| Переменная | Описание |
|---|---|
| `ANTHROPIC_API_KEY` | API-ключ Claude. Обязателен. |
| `CLAUDE_MODEL` | Модель Claude по умолчанию (`claude-sonnet-4-5-20250929`). |
| `DEEPSEEK_API_KEY` | API-ключ DeepSeek. Опционально. Если пусто, фабрика откатится на Claude. |
| `DEEPSEEK_BASE_URL` | Базовый URL DeepSeek API. |
| `ENABLE_PROMPT_CACHE` | Включить prompt caching Claude для стабильного system-контента (`True`). |

### Контекст

| Переменная | Описание |
|---|---|
| `MAX_CONTEXT_TOKENS` | Верхний потолок на весь контекст (`100000`). |
| `MAX_KNOWLEDGE_TOKENS` | Бюджет под `user_knowledge_texts` в system-блоке (`50000`). |
| `MAX_HISTORY_MESSAGES` | Максимум сообщений истории, которые идут в LLM (`20`). |
| `CONTEXT_RESERVE_TOKENS` | Зарезервировано под ответ модели (`4096`). |

### Имитация человеческого ответа

| Переменная | Описание |
|---|---|
| `HUMAN_RESPONSE_ENABLED` | Включить буферизацию + typing-loop (`True`). При `False` бот отвечает сразу. |
| `MIN_RESPONSE_DELAY` / `MAX_RESPONSE_DELAY` | Диапазон случайной задержки перед ответом (`15.0` / `25.0` сек). |
| `TYPING_CHARS_PER_SECOND` | Скорость «печати» для расчёта длины typing-индикатора (`40`). |
| `TYPING_MIN_DURATION` / `TYPING_MAX_DURATION` | Clamp на длительность typing (`3.0` / `60.0` сек). |

### Follow-up

| Переменная | Описание |
|---|---|
| `FOLLOWUP_ENABLED` | Включить планировщик напоминаний (`True`). |
| `FOLLOWUP_CHECK_INTERVAL` | Как часто опрашивать БД, сек (`60`). |
| `FOLLOWUP_DELAY_MINUTES` | Через сколько минут после ответа бота слать напоминание (`60`). |
| `FOLLOWUP_MAX_COUNT` | Сколько follow-up-ов на один диалог (`1`). |

### Настройки per-user

В таблице `users` можно задать индивидуальные настройки (пока без админ-UI, правьте через SQL):

- `system_prompt TEXT` — кастомные инструкции для AI от владельца (стиль, тон, что говорить/не говорить).
- `ai_model VARCHAR(64)` — переопределить модель для конкретного владельца (например, `deepseek-chat`).
- `max_history_messages INTEGER` — локальный override `MAX_HISTORY_MESSAGES`.

Также таблица `user_knowledge_texts` — база знаний владельца (куски текста, которые подгружаются в system-блок Claude). Пока заполняется через SQL, в будущем появится админ-UI.

---

## 🏗️ Архитектура

```
app/
├── main.py                          # Bot, Dispatcher, on_startup/on_shutdown
├── config.py                        # Pydantic Settings
├── handlers/
│   ├── __init__.py                  # setup_routers() — business_router первым!
│   ├── business/                    # 🔥 Telegram Business mode
│   │   ├── __init__.py              # экспортирует business_router
│   │   ├── connection.py            # @router.business_connection()
│   │   └── messages.py              # @router.business_message() + edited/deleted + AI-генерация
│   ├── admin/                       # админ-панель (рассылки, статус)
│   ├── start.py, help.py            # базовые команды
├── middlewares/
│   ├── __init__.py                  # registers business middleware on business_* events
│   ├── business.py                  # injects repo, ai factory, context manager, human_response
│   ├── user.py                      # автосохранение пользователей (только для обычных апдейтов)
│   └── logging.py
├── repositories/
│   └── business_repo.py             # CRUD для business_connections/conversations/messages
├── services/
│   ├── ai/
│   │   ├── base.py                  # BaseAIService, DEFAULT_BASE_PROMPT, tiktoken encoder
│   │   ├── claude_provider.py       # ClaudeService (anthropic.AsyncAnthropic)
│   │   ├── deepseek_provider.py     # DeepSeekService (openai.AsyncOpenAI с base_url)
│   │   └── factory.py               # get_ai_service(model) с fallback
│   ├── context_manager.py           # prepare_context_with_cache() — блоки Claude, обрезка истории
│   ├── human_response.py            # буфер 15–25 сек + typing loop (singleton human_response)
│   ├── followup_scheduler.py        # фоновая корутина, отправляет напоминания
│   └── broadcast.py                 # рассылки (из базового шаблона)
├── database/
│   ├── models.py                    # User (+3 поля), BusinessConnection, Conversation, Message, UserKnowledgeText
│   ├── database.py                  # db singleton, session_maker, create_tables()
│   └── migrations/                  # custom migration system
│       ├── base.py / manager.py
│       └── versions/
│           └── 20260416_000001_business_tables.py
├── states/ + keyboards/ + utils/    # FSM, кнопки, утилиты
```

**Порядок роутеров имеет значение.** `business_router` подключается **первым** в `setup_routers()`, чтобы `business_message` не перехватывался общим `dp.message` до того, как дойдёт до нашего handler-а.

**UserMiddleware НЕ вешается на business-события** — иначе клиенты владельца попадут в таблицу `users`, что семантически некорректно (мы храним там только владельцев бизнес-аккаунтов).

---

## 🗄️ Схема БД (Business-режим)

| Таблица | Назначение |
|---|---|
| `users` | Владельцы бизнес-аккаунтов (+ поля AI). |
| `business_connections` | Подключения бота к Business-аккаунтам. `connection_id` — unique из Telegram. |
| `conversations` | Диалоги владельца с конкретными клиентами. UNIQUE `(business_connection_id, client_chat_id)`. Хранит `last_message_at/role`, `next_followup_at`, `followup_count`. |
| `messages` | История: `role ∈ {user, assistant}`, `content`, `telegram_message_id`, `token_count`. |
| `user_knowledge_texts` | Куски знаний владельца, уходят в system-промпт AI. |

Ключевые правила:
- Сообщение от **клиента** → `role='user'`. Запускает буферизацию и AI.
- Сообщение от **владельца** (вручную или из AI-ответа бота) → `role='assistant'`. Планирует follow-up. На владельца AI не реагирует.
- Когда клиент отвечает — `next_followup_at` и `followup_count` сбрасываются.

---

## 📦 Команды разработки

Используйте `just` (или эквивалентный `make`).

### Запуск

```bash
just dev           # старт с логами на переднем плане
just dev-d         # старт в фоне
just stop          # остановить
just restart-bot   # перезапустить только bot
just logs-bot      # живые логи бота
just status        # статус контейнеров
```

### База данных

```bash
just db-shell                                # psql в контейнер
just db-migrate                              # применить миграции вручную
just db-migration-status                     # показать применённые
just db-backup                               # pg_dump в backup_YYYYMMDD.sql
just create-migration add_something "desc"   # создать новый файл миграции
```

### Отладка

```bash
just shell         # bash в контейнере бота
just logs          # все сервисы
just logs-db       # postgres
just test          # pytest внутри контейнера (если тесты есть)
```

### Продакшен

```bash
just setup-prod    # создать .env.prod из .env.prod.example
just prod          # запуск prod-стэка (требует .env.prod)
just prod-stop
just prod-deploy   # scripts/deploy.py
```

### Local Bot API (файлы до 2 ГБ)

```bash
just dev-local     # старт с Local Bot API Server
just api-status    # проверить, жив ли сервер
just api-logs
just stop-local
```

Полный список: `just --list`.

---

## 🗃️ Миграции

Своя минималистичная система миграций (без Alembic).

- Файлы: `app/database/migrations/versions/YYYYMMDD_NNNNNN_*.py`
- Каждый файл — класс, наследующий `Migration`, с методами `get_version()`, `get_description()`, `check_can_apply()`, `upgrade()`, `downgrade()`.
- `MigrationManager` обнаруживает их автоматически и применяет по возрастанию версии.
- История ведётся в таблице `migration_history`.

Создать новую миграцию:

```bash
just create-migration add_client_tags "Add tags column to conversations"
```

Подробности: [docs/MIGRATIONS.md](docs/MIGRATIONS.md).

---

## 🧩 Настройка персонального поведения

Пока без UI — прямо через SQL:

```sql
-- задать кастомный промпт владельцу
UPDATE users
SET system_prompt = 'Ты — владелец студии Foo. Отвечай коротко, предлагай созвон при сложных вопросах.'
WHERE id = 123456789;

-- переключить на DeepSeek
UPDATE users SET ai_model = 'deepseek-chat' WHERE id = 123456789;

-- добавить тексты в базу знаний владельца
INSERT INTO user_knowledge_texts (user_id, content, order_index)
VALUES
  (123456789, 'Прайс: консультация 5000₽, проект от 50 000₽.', 1),
  (123456789, 'Мы не работаем с криптой и играми.',              2);
```

---

## 🛠️ Основной стэк

- [aiogram v3.20](https://docs.aiogram.dev/) — Telegram Bot framework
- [anthropic](https://github.com/anthropics/anthropic-sdk-python) — Claude API клиент
- [openai](https://github.com/openai/openai-python) — используется для DeepSeek через `base_url`
- [tiktoken](https://github.com/openai/tiktoken) — offline подсчёт токенов
- [SQLAlchemy 2.0](https://docs.sqlalchemy.org/) (async) + asyncpg + PostgreSQL 15
- [Redis 7](https://redis.io/) — FSM-хранилище aiogram
- [pydantic 2](https://docs.pydantic.dev/) + [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — конфигурация
- [loguru](https://github.com/Delgan/loguru) — логирование

---

## 🧪 Сценарий ручной проверки

1. `just dev-d`, `just logs-bot` — увидеть `✅ Follow-up scheduler started`.
2. Подключить бота в Business-настройках Telegram с полными правами — в логах появится `✅ Business подключение включено: ...`, в чате с ботом — приветственное сообщение.
3. С клиентского аккаунта отправить 3 сообщения подряд с интервалом ~1 сек.
4. Через 15–25 сек → индикатор «печатает...» → одно объединённое сообщение от имени владельца.
5. Посмотреть в БД:
   ```bash
   just db-shell
   SELECT role, content FROM messages ORDER BY created_at;
   SELECT * FROM conversations;
   ```
6. Отвечать клиентом самостоятельно из владельческого аккаунта → в `conversations` появится запись с `last_message_role='assistant'`, followup запланирован.
7. Клиент отвечает → followup сброшен, AI снова включается.
8. Для проверки follow-up: `FOLLOWUP_DELAY_MINUTES=2`, `FOLLOWUP_CHECK_INTERVAL=30`, `just restart-bot` → через пару минут прилетает напоминание.

---

## 🔐 Безопасность

- `.env` и `.env.prod` всегда в `.gitignore`. Проверяется при каждом коммите.
- Docker-контейнер бота запускается от непривилегированного пользователя.
- Токены Telegram, ключи AI и пароли БД живут только в `.env*`, в репозиторий попадают только `*.example` с плейсхолдерами.
- Prompt caching Claude хранит только system-контент (не диалоги клиентов).

---

## 📄 Лицензия

MIT.

---

Основано на шаблоне [aiogram_starter_kit](https://github.com/aislam23/aiogram_starter_kit). Telegram Business mode, AI-провайдеры, буферизация и follow-up-планировщик — дополнительный слой поверх этой базы.
