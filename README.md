# GameCoach Bot

Telegram-бот, который анализирует игровые клипы и матчи через Google Gemini
и выдаёт коучинг-разбор: тайминги ошибок, что сделано хорошо и одна
конкретная рекомендация на следующую игру.

MVP-игры:
- **Marvel Rivals** — анализ видео-клипа (MP4)
- **Dota 2** — анализ матча по ID через OpenDota API

Бот спроектирован как плагин-система: каждая игра — отдельный файл в
`bot/games/`. Чтобы добавить новую игру, не нужно править ядро.

## Возможности

- `/start`, `/games` — выбор игры через инлайн-клавиатуру
- Видео-игры: выбор героя из клавиатуры → загрузка MP4 → разбор
- API-игры (Dota 2): отправка ID матча → выбор слота 1–10 из клавиатуры → разбор
- Дневной лимит на пользователя (по умолчанию 2 анализа в сутки, общий
  на все игры)
- Команда `/limits` — показывает остаток на сегодня и всего сделано
- Админ обходит лимит (если задан `ADMIN_TELEGRAM_ID`)
- JSON-логи с ротацией (`logs/bot.log`)
- Автоудаление загруженных в Gemini файлов после анализа

## Стек

- Python 3.11+
- `python-telegram-bot` v21 (async)
- `google-generativeai` 0.8.x — Gemini 1.5 Pro для видео и текста
- `aiohttp` — клиент OpenDota
- `aiosqlite` — SQLite в асинхронном режиме
- Деплой: одиночный VPS + systemd

## Архитектура

```
bot/
├── main.py                  # Точка входа: собирает Application и запускает polling
├── config.py                # .env → Settings + настройка JSON-логирования
├── core/
│   ├── analyzer.py          # Оркестратор: plugin.analyze() → save → increment
│   ├── usage.py             # Дневной лимит (UsageGuard, UsageStatus)
│   └── formatter.py         # Разбиение длинного ответа под лимит Telegram
├── games/                   # ПЛАГИНЫ — по одному файлу на игру
│   ├── base.py              # Абстрактный класс BaseGamePlugin + GameConfig
│   ├── marvel_rivals.py     # Видео-плагин
│   └── dota2.py             # API-плагин (OpenDota + Gemini text)
├── handlers/
│   ├── start.py             # /start, /help, /games, /cancel, /limits
│   ├── game_select.py       # Callback'и инлайн-клавиатур (game / hero / slot)
│   ├── video.py             # Загрузка видео и отправка результата
│   ├── match_id.py          # Текстовый хэндлер для match-id флоу
│   ├── keyboards.py         # Конструкторы клавиатур
│   ├── state.py             # Машина состояний в context.user_data
│   └── error.py             # Глобальный обработчик ошибок PTB
├── services/
│   ├── gemini.py            # Async-обёртка над google-generativeai
│   ├── registry.py          # Авто-загрузка плагинов из bot/games/
│   └── container.py         # Контейнер шарящих сервисов (DI)
└── db/
    ├── database.py          # Async aiosqlite + WAL + миграции CREATE IF NOT EXISTS
    └── models.py            # Dataclass-модели User и Analysis
```

### Поток данных

**Видео-флоу (Marvel Rivals):**
```
/games → user picks Marvel Rivals → keyboard with 33 heroes
→ user picks hero → "загрузите клип, MP4 ≤ 200MB"
→ video upload → bytes → MarvelRivalsPlugin.analyze
→ Gemini upload → poll → generate_content → delete file
→ форматированный ответ + футер с лимитом
```

**API-флоу (Dota 2):**
```
/games → user picks Dota 2 → "пришли match ID"
→ user sends match_id → OpenDota /matches/{id} + /constants/heroes,items
→ keyboard со списком 10 слотов (Radiant/Dire + герой + KDA)
→ user picks slot → собранный JSON-стат → Gemini analyze_text
→ форматированный ответ + футер с лимитом
```

## Как добавить новую игру (это главное)

1. Создай файл `bot/games/my_game.py`.
2. Опиши класс, наследующийся от `BaseGamePlugin`:

```python
from bot.games.base import (
    BaseGamePlugin, GameConfig, AnalysisResult, InputType,
)
from bot.services import container


class MyGamePlugin(BaseGamePlugin):
    @property
    def config(self) -> GameConfig:
        return GameConfig(
            id="my_game",                 # стабильный ID, попадает в БД
            display_name="My Game",
            emoji="🎮",
            input_type=InputType.VIDEO,    # или MATCH_ID
            has_characters=True,           # False, если выбора героя нет
            characters=["Hero A", "Hero B"],
            max_video_mb=200,
            description="Загрузите клип (MP4, до 200MB).",
        )

    def get_prompt(self, character: str | None) -> str:
        return f"You are a coach for My Game. Hero: {character}..."

    async def analyze(self, user_input, character, user_id) -> AnalysisResult:
        self.validate_character(character)
        out = await container.get_gemini().analyze_video(
            bytes(user_input), self.get_prompt(character)
        )
        return AnalysisResult(
            game_id=self.config.id,
            character=character,
            raw_text=out.raw_text,
            tokens_used=out.tokens_used,
            processing_seconds=out.processing_seconds,
        )
```

3. Перезапусти бота. Реестр (`bot/services/registry.py`) сам найдёт класс,
   и игра появится в `/games`. Никаких правок в `main.py`, хэндлерах или БД.

Файлы с префиксом `_` и `base.py` игнорируются. При конфликте `id`
плагинов первый зарегистрированный выигрывает, в логе ошибка.

## Установка (локально)

Требуется Python 3.11+ и созданное виртуальное окружение в `.venv`.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# заполни TELEGRAM_BOT_TOKEN и GEMINI_API_KEY в .env
.venv/bin/python -m bot.main
```

## Конфигурация (.env)

| Переменная              | По умолчанию  | Описание                                 |
|-------------------------|---------------|------------------------------------------|
| `TELEGRAM_BOT_TOKEN`    | —             | Токен бота от @BotFather                 |
| `GEMINI_API_KEY`        | —             | Ключ Google AI Studio                    |
| `FREE_ANALYSES_PER_DAY` | `2`           | Дневной лимит на пользователя            |
| `MAX_VIDEO_SIZE_MB`     | `200`         | Желаемый потолок (ограничен Telegram, см. ниже) |
| `TELEGRAM_FILE_LIMIT_MB`| `20`          | Реальный лимит Telegram Bot API на скачивание   |
| `ADMIN_TELEGRAM_ID`     | —             | Telegram ID, у которого нет лимита       |
| `LOG_LEVEL`             | `INFO`        | `DEBUG` / `INFO` / `WARNING` / `ERROR`   |
| `DB_PATH`               | `data/bot.db` | Путь к SQLite-файлу                      |
| `LOG_FILE`              | `logs/bot.log`| Файл-лога, ротируется по 10MB × 5        |

## Команды бота

- `/start` — приветствие и список игр
- `/games` — выбор игры (то же, что `/start`)
- `/limits` — текущая дневная и пожизненная статистика
- `/cancel` — сбросить текущий флоу
- `/help` — короткая справка

## Деплой через systemd

```bash
# 1. Системный пользователь и каталог
sudo useradd --system --home /opt/game_bot --shell /usr/sbin/nologin gamebot
sudo mkdir -p /opt/game_bot/{data,logs}
sudo cp -r bot requirements.txt /opt/game_bot/
sudo cp .env /opt/game_bot/.env
sudo chmod 600 /opt/game_bot/.env
sudo chown -R gamebot:gamebot /opt/game_bot

# 2. Virtualenv внутри /opt/game_bot
sudo -u gamebot python3 -m venv /opt/game_bot/.venv
sudo -u gamebot /opt/game_bot/.venv/bin/pip install -r /opt/game_bot/requirements.txt

# 3. Юнит
sudo cp systemd/game_coach.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now game_coach.service

# 4. Проверка
sudo systemctl status game_coach
sudo journalctl -u game_coach -f
```

Юнит ограничен hardening-флагами: `ProtectSystem=strict`, `PrivateTmp`,
`NoNewPrivileges`, доступ на запись только к `data/` и `logs/`.

## Лимит на размер видео (важно)

Стандартный Telegram Bot API режет загрузки через `getFile` на **20 МБ**, не
зависимо от того, что разрешает сама игра. Если пользователь отправит
74-мегабайтный клип — Telegram вернёт `BadRequest: File is too big`.

Бот учитывает это автоматически: эффективный лимит =
`min(GameConfig.max_video_mb, TELEGRAM_FILE_LIMIT_MB)`. Юзер увидит
дружественное сообщение **до** попытки скачать, плюс есть ловушка на
`BadRequest` в самом обработчике.

**Чтобы поднять лимит до 2 ГБ** — нужно поднять
[Local Bot API server](https://core.telegram.org/bots/api#using-a-local-bot-api-server)
рядом с ботом и указать `base_url` в PTB. После этого выставь
`TELEGRAM_FILE_LIMIT_MB=2000`. Для MVP проще запросить у пользователей
короткие клипы 15–30 сек (≤ 20 МБ при разумном битрейте).

## База данных

SQLite, две таблицы: `users` и `analyses`. Миграции выполняются автоматически
при старте через `CREATE TABLE IF NOT EXISTS`. Включён WAL и foreign keys.

```sql
users:    id, telegram_id, username, analyses_today, last_analysis_date,
          total_analyses, created_at
analyses: id, user_id (FK → users.id, ON DELETE CASCADE),
          game_id, character, input_type, result, tokens_used,
          processing_seconds, created_at
```

## Логирование

Каждое сообщение лога — JSON-строка вида:

```json
{"ts":"2026-05-08 18:39:24,294","level":"INFO","logger":"...","msg":"..."}
```

На каждый анализ пишутся структурированные строки `analysis_saved` или
`analysis_failed` с полями `user_id`, `game_id`, `character`, `input_type`,
`tokens`, `seconds` (или `error_type`, `msg` для ошибок).

## Обработка ошибок

| Сценарий                       | Что увидит пользователь                                         |
|--------------------------------|------------------------------------------------------------------|
| Видео > лимита                 | "Please send a shorter clip (max NMB)"                           |
| Match ID не найден             | "Match {id} not found. Check the ID and try again."              |
| OpenDota недоступна / 5xx      | "Dota 2 stats unavailable, try again later."                     |
| Gemini не уложился в 120с      | "Analysis taking too long, please retry with a shorter clip."    |
| Gemini вернул пусто / FAILED   | "Couldn't process the video. Try a different file..."            |
| Дневной лимит исчерпан         | "⛔️ Daily limit reached (N/day). Try again tomorrow."           |
| Любая необработанная ошибка    | Дружелюбное сообщение + полный traceback в логе                  |

## Roadmap (после MVP)

- Кэш разобранных Dota-матчей в БД (избежать повторных запросов в OpenDota)
- Платные тиры (увеличенный лимит, более длинные клипы)
- Webhook-режим вместо long polling
- Статус-команда `/admin` с метриками по играм и токенам
- Поддержка ещё одной видео-игры для проверки расширяемости плагинов
