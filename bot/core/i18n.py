"""Small localization helpers for Telegram UI and prompt selection."""

from __future__ import annotations

from typing import Any


DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = {"en", "ru"}
USER_DATA_LANGUAGE_KEY = "language_code"


def normalize_language_code(value: str | None) -> str:
    """Collapse Telegram/browser locale strings into the supported bot codes."""
    raw = (value or "").strip().lower()
    if raw.startswith("ru"):
        return "ru"
    if raw.startswith("en"):
        return "en"
    return DEFAULT_LANGUAGE


def language_name(language_code: str) -> str:
    return {
        "en": "English",
        "ru": "Русский",
    }.get(normalize_language_code(language_code), "English")


TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "welcome": (
            "👋 *GameCoach Bot*\n\n"
            "Pick a game below to get an AI coaching analysis of your gameplay."
        ),
        "help": (
            "🤖 *How it works*\n\n"
            "1. Pick a game with /games\n"
            "2. For video games — pick your hero, then upload an MP4 clip\n"
            "3. For Dota 2 — send your match ID, then pick which slot was you\n\n"
            "You get a structured analysis with timestamps, mistakes and a "
            "recommendation. Daily free limit applies.\n\n"
            "Commands:\n"
            "/start — start over\n"
            "/games — pick a game\n"
            "/language — choose language\n"
            "/limits — see your daily usage\n"
            "/cancel — cancel the current flow\n"
            "/help — this message"
        ),
        "choose_game": "Choose a game:",
        "choose_language": "Choose language:",
        "language_saved": "Language saved: {language}.",
        "pick_hero": "{emoji} *{game}*\n\nPick your hero:",
        "dota_match_prompt": (
            "{emoji} *{game}*\n\n"
            "Send your match ID (find it in Main Menu → Profile → Matches). "
            "After fetching the match you'll pick which slot was you."
        ),
        "upload_clip": "{emoji} *{game}* — {character}\n\nNow upload your gameplay clip (MP4, max {max_mb}MB).",
        "cancelled": "Cancelled. Send /games to start over.",
        "unknown_game": "Unknown game. Send /games to start over.",
        "invalid_selection": "Invalid selection. Send /games to start over.",
        "invalid_character": "Invalid character. Send /games to start over.",
        "limits_title": "📊 *Your usage*",
        "lifetime_analyses": "Lifetime analyses: {count}",
        "limit_remaining": "Analyses left today: {remaining}/{limit}.",
        "limit_admin": "Admin — unlimited analyses.",
        "daily_limit": "⛔️ Daily limit reached ({limit}/day). Try again tomorrow.",
        "send_games_first": "Send /games first, pick a game and a hero, then upload the clip.",
        "unknown_current_game": "Unknown game in current flow. Send /games.",
        "send_video": "Please send a video file (MP4).",
        "unsupported_attachment": (
            "Please send a video file (MP4). Photos, audio and other files "
            "aren't supported for analysis."
        ),
        "clip_too_large": "Your clip is {actual_mb} MB — too large. Please send a shorter clip (max {max_mb} MB).{hint}",
        "telegram_limit_hint": (
            "\n\nTelegram's Bot API limits file downloads to {limit_mb} MB. "
            "To process larger clips, run a Local Bot API server (see README)."
        ),
        "analyzing_video": "⏳ Analyzing... ~30-60 seconds. Please wait.",
        "download_timeout": "Downloading your video took too long. Please try a shorter clip or retry in a moment.",
        "telegram_file_too_big": (
            "This file is too big for Telegram's Bot API to deliver "
            "(limit ~{limit_mb} MB). Please send a shorter clip."
        ),
        "download_failed": "Couldn't download your video from Telegram. Please try again.",
        "analysis_timeout": "Analysis taking too long, please retry with a shorter clip.",
        "video_processing_failed": "Couldn't process the video. Try a different file or shorter clip.",
        "analysis_failed": "Analysis failed: {error}",
        "generic_analysis_failed": "Something went wrong while analyzing. Please try again.",
        "waiting_video": "I'm waiting for a video clip. Please upload an MP4 (or send /cancel to start over).",
        "waiting_hero": "Please pick a hero from the keyboard above (or send /cancel to start over).",
        "waiting_slot": "Please pick your slot from the keyboard above (or send /cancel to start over).",
        "idle_text": "Send /games to pick a game.",
        "fetching_match": "⏳ Fetching match data...",
        "match_found": "Match `{match_id}` found. Pick which slot was you:",
        "dota_unavailable": "Dota 2 plugin not available right now.",
        "dota_failed": "Failed to fetch match data, please try again later.",
        "analyzing_match": "⏳ Analyzing match... ~10-30 seconds",
        "footer": "— tokens: {tokens} · {seconds:.1f}s · source: {source}",
    },
    "ru": {
        "welcome": (
            "👋 *GameCoach Bot*\n\n"
            "Выбери игру ниже, чтобы получить AI-разбор своего геймплея."
        ),
        "help": (
            "🤖 *Как это работает*\n\n"
            "1. Выбери игру через /games\n"
            "2. Для видео-игр выбери героя и загрузи MP4-клип\n"
            "3. Для Dota 2 отправь match ID и выбери свой слот\n\n"
            "Бот вернет структурированный разбор: таймкоды, ошибки, сильные "
            "моменты и рекомендацию. Дневной бесплатный лимит сохраняется.\n\n"
            "Команды:\n"
            "/start — начать заново\n"
            "/games — выбрать игру\n"
            "/language — выбрать язык\n"
            "/limits — посмотреть лимиты\n"
            "/cancel — отменить текущий сценарий\n"
            "/help — эта справка"
        ),
        "choose_game": "Выбери игру:",
        "choose_language": "Выбери язык:",
        "language_saved": "Язык сохранен: {language}.",
        "pick_hero": "{emoji} *{game}*\n\nВыбери героя:",
        "dota_match_prompt": (
            "{emoji} *{game}*\n\n"
            "Отправь match ID (Main Menu → Profile → Matches). "
            "После загрузки матча выберешь свой слот."
        ),
        "upload_clip": "{emoji} *{game}* — {character}\n\nТеперь загрузи геймплейный клип (MP4, максимум {max_mb} МБ).",
        "cancelled": "Отменено. Отправь /games, чтобы начать заново.",
        "unknown_game": "Неизвестная игра. Отправь /games, чтобы начать заново.",
        "invalid_selection": "Некорректный выбор. Отправь /games, чтобы начать заново.",
        "invalid_character": "Некорректный герой. Отправь /games, чтобы начать заново.",
        "limits_title": "📊 *Твои лимиты*",
        "lifetime_analyses": "Всего анализов: {count}",
        "limit_remaining": "Осталось анализов сегодня: {remaining}/{limit}.",
        "limit_admin": "Админ — безлимитные анализы.",
        "daily_limit": "⛔️ Дневной лимит исчерпан ({limit}/день). Попробуй завтра.",
        "send_games_first": "Сначала отправь /games, выбери игру и героя, затем загрузи клип.",
        "unknown_current_game": "В текущем сценарии неизвестная игра. Отправь /games.",
        "send_video": "Пожалуйста, отправь видеофайл (MP4).",
        "unsupported_attachment": (
            "Пожалуйста, отправь видеофайл (MP4). Фото, аудио и другие файлы "
            "для анализа не поддерживаются."
        ),
        "clip_too_large": "Клип весит {actual_mb} МБ — это слишком много. Отправь более короткий клип (максимум {max_mb} МБ).{hint}",
        "telegram_limit_hint": (
            "\n\nСтандартный Telegram Bot API отдает файлы только до {limit_mb} МБ. "
            "Для больших клипов нужен Local Bot API server (см. README)."
        ),
        "analyzing_video": "⏳ Анализирую... примерно 30-60 секунд. Подожди немного.",
        "download_timeout": "Скачивание видео заняло слишком много времени. Попробуй клип короче или повтори позже.",
        "telegram_file_too_big": (
            "Этот файл слишком большой для выдачи через Telegram Bot API "
            "(лимит около {limit_mb} МБ). Отправь клип короче."
        ),
        "download_failed": "Не удалось скачать видео из Telegram. Попробуй еще раз.",
        "analysis_timeout": "Анализ идет слишком долго. Попробуй клип короче.",
        "video_processing_failed": "Не удалось обработать видео. Попробуй другой файл или клип короче.",
        "analysis_failed": "Анализ не удался: {error}",
        "generic_analysis_failed": "Что-то пошло не так во время анализа. Попробуй еще раз.",
        "waiting_video": "Я жду видеоклип. Загрузи MP4 или отправь /cancel, чтобы начать заново.",
        "waiting_hero": "Пожалуйста, выбери героя на клавиатуре выше или отправь /cancel.",
        "waiting_slot": "Пожалуйста, выбери свой слот на клавиатуре выше или отправь /cancel.",
        "idle_text": "Отправь /games, чтобы выбрать игру.",
        "fetching_match": "⏳ Загружаю данные матча...",
        "match_found": "Матч `{match_id}` найден. Выбери, какой слот был твоим:",
        "dota_unavailable": "Плагин Dota 2 сейчас недоступен.",
        "dota_failed": "Не удалось получить данные матча. Попробуй позже.",
        "analyzing_match": "⏳ Анализирую матч... примерно 10-30 секунд",
        "footer": "— токены: {tokens} · {seconds:.1f}с · источник: {source}",
    },
}


def t(language_code: str, key: str, **kwargs: Any) -> str:
    """Return a localized text by key, falling back to English."""
    lang = normalize_language_code(language_code)
    template = TEXTS.get(lang, TEXTS[DEFAULT_LANGUAGE]).get(
        key,
        TEXTS[DEFAULT_LANGUAGE].get(key, key),
    )
    return template.format(**kwargs) if kwargs else template


async def get_user_language(context: Any, telegram_user: Any | None) -> str:
    """Read language from user_data/DB, initializing it from Telegram locale."""
    user_data = getattr(context, "user_data", None)
    if user_data and user_data.get(USER_DATA_LANGUAGE_KEY):
        return normalize_language_code(user_data[USER_DATA_LANGUAGE_KEY])

    guessed = normalize_language_code(getattr(telegram_user, "language_code", None))
    db = getattr(getattr(context, "application", None), "bot_data", {}).get("db")
    if db is not None and telegram_user is not None:
        user = await db.get_or_create_user(
            telegram_user.id,
            getattr(telegram_user, "username", None),
            language_code=guessed,
        )
        guessed = normalize_language_code(user.language_code)

    if user_data is not None:
        user_data[USER_DATA_LANGUAGE_KEY] = guessed
    return guessed


async def set_user_language(
    context: Any,
    telegram_user: Any | None,
    language_code: str,
) -> str:
    """Persist selected language and update user_data cache."""
    lang = normalize_language_code(language_code)
    user_data = getattr(context, "user_data", None)
    if user_data is not None:
        user_data[USER_DATA_LANGUAGE_KEY] = lang

    db = getattr(getattr(context, "application", None), "bot_data", {}).get("db")
    if db is not None and telegram_user is not None:
        await db.get_or_create_user(
            telegram_user.id,
            getattr(telegram_user, "username", None),
            language_code=lang,
        )
        await db.set_user_language(telegram_user.id, lang)
    return lang
