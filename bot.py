import logging
import random
import json
import os
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from telegram import Update, InlineQueryResultCachedSticker, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    InlineQueryHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------- НАСТРОЙКИ ----------
TOKEN = "8891403100:AAGLU4dVDJWEsZFdmXGihyzbGUrGmUvDrcg"
MINI_APP_URL = "https://jalal-p7p9.onrender.com"

ADMIN_USERNAME = "xornid"

RANDOM_WORDS = [
    "кот", "привет", "чайник", "Владимир", "мандарин", "космос", "велосипед",
    "одуванчик", "банан", "дракон", "шлёпа", "мем", "бот", "пельмень",
    "капибара", "флекс", "вайб", "фолк", "долина", "сковорода", "сыр",
    "подушка", "кактус", "утюг", "закат", "шнурок", "лампочка", "кнопка",
    "огурец", "микрофон", "самокат", "трамвай", "облако", "одуван"
]

# ---------- ГЛОБАЛЬНЫЕ ДАННЫЕ ----------
ALL_STICKERS = []
litvin_stickers = []
bred_stickers = []          # бывший tihon

cooldowns_folk = {}
cooldowns_litvin = {}
cooldowns_bred = {}         # бывший tihon

chat_cooldowns = {}
pending_cooldown_input = {}

admin_state = {}

USER_GROUPS_FILE = "user_groups.json"
CONFIG_FILE = "sticker_config.json"
user_groups = {}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ---------- ЗАГРУЗКА/СОХРАНЕНИЕ ГРУПП ----------
def load_user_groups():
    global user_groups
    if os.path.exists(USER_GROUPS_FILE):
        try:
            with open(USER_GROUPS_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                user_groups = {int(k): v for k, v in raw.items()}
            logging.info(f"Загружено групп пользователей: {sum(len(v) for v in user_groups.values())}")
        except Exception as e:
            logging.warning(f"Не удалось загрузить user_groups.json: {e}")
            user_groups = {}

def save_user_groups():
    try:
        with open(USER_GROUPS_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_groups, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Не удалось сохранить user_groups.json: {e}")

# ---------- КОНФИГУРАЦИЯ СТИКЕРОВ (с дефолтными паками) ----------
def load_config():
    default_config = {
        "commands": {
            "folk": [
                {"pack_name": "ByFolkValley", "remove_last": 0},
                {"pack_name": "AtlasScottishFold", "remove_last": 0},
                {"pack_name": "Vooocaaa_by_fStikBot", "remove_last": 2}
            ],
            "litvin": [
                {"pack_name": "pk_2746611_by_Ctikerubot", "remove_last": 2}
            ],
            "bred": [
                {"pack_name": "DouBlya", "remove_last": 0},
                {"pack_name": "Fartsmopington_by_MoiStikiBot", "remove_last": 0}
            ]
        }
    }
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)
        return default_config
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
            # Проверяем наличие ключа bred (для обратной совместимости)
            if "tihon" in loaded.get("commands", {}):
                loaded["commands"]["bred"] = loaded["commands"].pop("tihon")
            return loaded
    except Exception as e:
        logging.error(f"Ошибка загрузки конфига: {e}")
        return default_config

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения конфига: {e}")

async def load_stickers(app: Application):
    global ALL_STICKERS, litvin_stickers, bred_stickers
    config = load_config()
    commands_config = config.get("commands", {})

    # Собираем все имена паков
    all_packs = []
    for cmd_packs in commands_config.values():
        for entry in cmd_packs:
            all_packs.append(entry.get("pack_name"))

    # Знакомим бота с каждым паком
    me = await app.bot.get_me()
    for pack_name in set(all_packs):
        try:
            await app.bot.get_sticker_set(pack_name)
            logging.info(f"Пак {pack_name} уже известен боту")
        except Exception:
            logging.warning(f"Бот не знает пак {pack_name}, пробую добавить...")
            try:
                # Получаем пак по ссылке (это не требует предварительного знакомства)
                pack = await app.bot.get_sticker_set(pack_name)
                if pack.stickers:
                    # Отправляем первый стикер "в никуда" — бот знакомится с паком
                    # Отправляем в сохранённые сообщения (chat_id = user_id бота)
                    await app.bot.send_sticker(
                        chat_id=me.id,
                        sticker=pack.stickers[0].file_id
                    )
                    logging.info(f"Пак {pack_name} успешно добавлен (отправлен стикер в Избранное)")
                else:
                    logging.warning(f"Пак {pack_name} пустой")
            except Exception as e:
                logging.error(f"Не удалось добавить пак {pack_name}: {e}")
                continue

    # Теперь загружаем стикеры по конфигу
    all_folk = []
    all_litvin = []
    all_bred = []

    for command, packs in commands_config.items():
        stickers_list = []
        for entry in packs:
            pack_name = entry.get("pack_name")
            remove_last = int(entry.get("remove_last", 0))
            try:
                pack = await app.bot.get_sticker_set(pack_name)
                stickers = [s.file_id for s in pack.stickers]
                if remove_last > 0:
                    if len(stickers) > remove_last:
                        stickers = stickers[:-remove_last]
                    else:
                        logging.warning(f"В паке {pack_name} меньше {remove_last} стикеров, используется все доступные")
                stickers_list.extend(stickers)
                logging.info(f"Загружен пак {pack_name} для /{command}, стикеров добавлено: {len(stickers)}")
            except Exception as e:
                logging.error(f"Не удалось загрузить пак {pack_name}: {e}")

        if command == "folk":
            all_folk = stickers_list
        elif command == "litvin":
            all_litvin = stickers_list
        elif command == "bred":
            all_bred = stickers_list

    ALL_STICKERS = all_folk
    litvin_stickers = all_litvin
    bred_stickers = all_bred
    logging.info(f"Стикеры обновлены: folk={len(ALL_STICKERS)}, litvin={len(litvin_stickers)}, bred={len(bred_stickers)}")

def get_sticker_list_for_command(command):
    if command == "folk":
        return ALL_STICKERS
    elif command == "litvin":
        return litvin_stickers
    elif command == "bred":
        return bred_stickers
    return []

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ КУЛДАУНА ----------
def get_cd_duration(chat_id, command):
    if chat_id not in chat_cooldowns:
        chat_cooldowns[chat_id] = {'folk': 300, 'litvin': 300, 'bred': 300}
    return chat_cooldowns[chat_id].get(command, 300)

def get_cooldown_dict(command):
    if command == 'folk':
        return cooldowns_folk
    elif command == 'litvin':
        return cooldowns_litvin
    elif command == 'bred':
        return cooldowns_bred
    return {}

def is_cooling(chat_id, user_id, command):
    duration = get_cd_duration(chat_id, command)
    if duration == 0:
        return False, None
    cd_dict = get_cooldown_dict(command)
    key = (chat_id, user_id)
    now = datetime.now()
    if key in cd_dict and (now - cd_dict[key]) < timedelta(seconds=duration):
        remain = cd_dict[key] + timedelta(seconds=duration) - now
        return True, remain
    return False, None

def set_cooldown_used(chat_id, user_id, command):
    cd_dict = get_cooldown_dict(command)
    cd_dict[(chat_id, user_id)] = datetime.now()

# ---------- ОБРАБОТКА ДОБАВЛЕНИЯ В ГРУППУ ----------
async def on_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    bot_id = context.bot.id
    for member in update.message.new_chat_members:
        if member.id == bot_id:
            logging.info(f"Бот добавлен в чат: {chat.title} ({chat.id})")
            try:
                admins = await context.bot.get_chat_administrators(chat.id)
                creator_id = None
                for admin in admins:
                    if admin.status == ChatMemberStatus.OWNER:
                        creator_id = admin.user.id
                        break
                if creator_id:
                    group_info = {
                        "chat_id": chat.id,
                        "title": chat.title or "Без названия",
                        "member_count": await chat.get_member_count() if hasattr(chat, 'get_member_count') else 0,
                        "invite_link": None,
                        "photo_url": None
                    }
                    try:
                        chat_obj = await context.bot.get_chat(chat.id)
                        if chat_obj.photo:
                            photo_file = await context.bot.get_file(chat_obj.photo.big_file_id)
                            group_info["photo_url"] = photo_file.file_path
                    except:
                        pass
                    try:
                        invite = await context.bot.create_chat_invite_link(
                            chat.id, name="Folk Valley Bot", creates_join_request=False
                        )
                        group_info["invite_link"] = invite.invite_link
                    except:
                        pass
                    if creator_id not in user_groups:
                        user_groups[creator_id] = []
                    existing = [g for g in user_groups[creator_id] if g["chat_id"] == chat.id]
                    if not existing:
                        user_groups[creator_id].append(group_info)
                        save_user_groups()
                        logging.info(f"Группа '{chat.title}' сохранена для пользователя {creator_id}")
            except Exception as e:
                logging.error(f"Ошибка при сохранении группы: {e}")

async def update_group_info(context: ContextTypes.DEFAULT_TYPE):
    updated = False
    for uid, groups in list(user_groups.items()):
        for group in groups:
            try:
                chat = await context.bot.get_chat(group["chat_id"])
                new_title = chat.title or group["title"]
                new_count = await chat.get_member_count() if hasattr(chat, 'get_member_count') else group.get("member_count", 0)
                if new_title != group.get("title") or new_count != group.get("member_count"):
                    group["title"] = new_title
                    group["member_count"] = new_count
                    updated = True
                if chat.photo:
                    photo_file = await context.bot.get_file(chat.photo.big_file_id)
                    group["photo_url"] = photo_file.file_path
            except:
                continue
    if updated:
        save_user_groups()

# ---------- КОМАНДЫ ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        keyboard = [
            [InlineKeyboardButton("👤 Профиль", web_app=WebAppInfo(url=MINI_APP_URL))]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = (
            "👋 Привет! Я бот с мемными стикерами Folk Valley.\n\n"
            "Как использовать:\n"
            "• В любом чате введи @folkvalleybot и нажми на появившийся стикер — я отправлю его.\n"
            "  (Каждый раз стикер случайный!)\n"
            "• В группе работают команды:\n"
            "  /folk — случайный стикер\n"
            "  /litvin — случайный стикер\n"
            "  /bred — случайный стикер\n"
            "  /sosat — бессвязный бред\n"
            "  /cooldown — настройка кулдаунов (владелец)\n\n"
            "👤 Кнопка «Профиль» откроет Mini App с вашими группами.\n\n"
            "Наслаждайся вайбом!"
        )
        await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        text = (
            "Я в группе! Доступные команды:\n"
            "/folk — случайный стикер\n"
            "/litvin — стикер из Litvin пака\n"
            "/bred — стикер из Bred пака\n"
            "/sosat — рандомный бред\n"
            "/cooldown — настройка кулдаунов (владелец)"
        )
        await update.message.reply_text(text)

async def folk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    is_cool, remain = is_cooling(chat_id, user_id, 'folk')
    if is_cool:
        mins, secs = divmod(remain.seconds, 60)
        await update.message.reply_text(f"⏳ Подожди ещё {mins} мин. {secs} сек.", quote=True)
        return
    if not ALL_STICKERS:
        await update.message.reply_text("Стикеры для /folk пока не настроены.")
        return
    sticker_id = random.choice(ALL_STICKERS)
    await update.message.reply_sticker(sticker=sticker_id)
    set_cooldown_used(chat_id, user_id, 'folk')

async def litvin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    is_cool, remain = is_cooling(chat_id, user_id, 'litvin')
    if is_cool:
        mins, secs = divmod(remain.seconds, 60)
        await update.message.reply_text(f"⏳ Подожди ещё {mins} мин. {secs} сек.", quote=True)
        return
    if not litvin_stickers:
        await update.message.reply_text("Стикеры для /litvin пока не настроены.")
        return
    sticker_id = random.choice(litvin_stickers)
    await update.message.reply_sticker(sticker=sticker_id)
    set_cooldown_used(chat_id, user_id, 'litvin')

async def bred(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    is_cool, remain = is_cooling(chat_id, user_id, 'bred')
    if is_cool:
        mins, secs = divmod(remain.seconds, 60)
        await update.message.reply_text(f"⏳ Подожди ещё {mins} мин. {secs} сек.", quote=True)
        return
    if not bred_stickers:
        await update.message.reply_text("Стикеры для /bred пока не настроены.")
        return
    sticker_id = random.choice(bred_stickers)
    await update.message.reply_sticker(sticker=sticker_id)
    set_cooldown_used(chat_id, user_id, 'bred')

async def sosat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = random.randint(3, 6)
    words = random.choices(RANDOM_WORDS, k=count)
    phrase = " ".join(words)
    await update.message.reply_text(phrase)

# ---------- КУЛДАУНЫ ----------
async def cooldown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Эта команда только для групп.")
        return
    try:
        admins = await context.bot.get_chat_administrators(chat.id)
    except Exception:
        await update.message.reply_text("Не удалось проверить права. Бот должен быть администратором.")
        return
    creator_id = None
    for admin in admins:
        if admin.status == ChatMemberStatus.OWNER:
            creator_id = admin.user.id
            break
    if creator_id is None or user.id != creator_id:
        await update.message.reply_text("Только создатель группы может менять кулдаун.")
        return
    folk_cd = get_cd_duration(chat.id, 'folk')
    litvin_cd = get_cd_duration(chat.id, 'litvin')
    bred_cd = get_cd_duration(chat.id, 'bred')
    text = (
        f"⚙️ **Настройка кулдаунов**\n\n"
        f"• /folk: **{folk_cd} с.**\n"
        f"• /litvin: **{litvin_cd} с.**\n"
        f"• /bred: **{bred_cd} с.**\n\n"
        "Выбери команду для изменения:"
    )
    keyboard = [
        [InlineKeyboardButton(f"🔄 Folk ({folk_cd}с)", callback_data="cooldown_select:folk")],
        [InlineKeyboardButton(f"🔄 Litvin ({litvin_cd}с)", callback_data="cooldown_select:litvin")],
        [InlineKeyboardButton(f"🔄 Bred ({bred_cd}с)", callback_data="cooldown_select:bred")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def cooldown_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
    except Exception:
        await query.answer("Не удалось проверить права.", show_alert=True)
        return
    creator_id = None
    for admin in admins:
        if admin.status == ChatMemberStatus.OWNER:
            creator_id = admin.user.id
            break
    if creator_id is None or user.id != creator_id:
        await query.answer("Только создатель группы может менять кулдаун.", show_alert=True)
        return
    data = query.data
    if not data.startswith("cooldown_select:"):
        return
    command = data.split(":")[1]
    pending_cooldown_input[(chat_id, user.id)] = command
    await query.answer()
    await query.edit_message_text(
        text=f"Введи кулдаун для /{command} в секундах (0–3600):\n0 = без задержки, 3600 = 1 час."
    )

async def handle_cooldown_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    key = (chat_id, user.id)
    if key not in pending_cooldown_input:
        return
    command = pending_cooldown_input.pop(key)
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Нужно ввести число. Операция отменена.")
        return
    seconds = int(text)
    if not 0 <= seconds <= 3600:
        await update.message.reply_text("Допустимый диапазон: 0 – 3600 секунд. Операция отменена.")
        return
    if chat_id not in chat_cooldowns:
        chat_cooldowns[chat_id] = {}
    chat_cooldowns[chat_id][command] = seconds
    await update.message.reply_text(f"✅ Кулдаун для /{command} установлен: **{seconds} с.**", parse_mode="Markdown")

# ---------- ИНЛАЙН-РЕЖИМ ----------
async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ALL_STICKERS:
        await update.inline_query.answer([], cache_time=0)
        return
    sticker_id = random.choice(ALL_STICKERS)
    results = [
        InlineQueryResultCachedSticker(
            id=str(random.randint(100000, 999999)),
            sticker_file_id=sticker_id
        )
    ]
    await update.inline_query.answer(results, cache_time=0)

# ---------- ГЛОБАЛЬНАЯ АДМИН-ПАНЕЛЬ ----------
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.username != ADMIN_USERNAME:
        await update.message.reply_text("Недостаточно прав.")
        return
    if update.effective_chat.type != "private":
        await update.message.reply_text("Админка только в ЛС.")
        return

    config = load_config()
    folk_packs = config["commands"]["folk"]
    litvin_packs = config["commands"]["litvin"]
    bred_packs = config["commands"]["bred"]

    text = (
        "🔧 **Админ-панель управления стикерами**\n\n"
        f"/folk: {len(folk_packs)} пак(ов), стикеров: {len(ALL_STICKERS)}\n"
        f"/litvin: {len(litvin_packs)} пак(ов), стикеров: {len(litvin_stickers)}\n"
        f"/bred: {len(bred_packs)} пак(ов), стикеров: {len(bred_stickers)}\n\n"
        "Выберите действие:"
    )

    keyboard = [
        [InlineKeyboardButton("➕ Добавить стикерпак", callback_data="admin_add_pack")],
        [InlineKeyboardButton("📋 Показать конфигурацию", callback_data="admin_show_config")],
        [InlineKeyboardButton("🗑 Удалить стикерпак", callback_data="admin_remove_pack")],
        [InlineKeyboardButton("✏️ Изменить remove_last", callback_data="admin_edit_remove")],
        [InlineKeyboardButton("🔄 Перезагрузить стикеры", callback_data="admin_refresh_stickers")],
        [InlineKeyboardButton("🧹 Сбросить кулдауны", callback_data="admin_clear_cooldowns")],
        [InlineKeyboardButton("📊 Статистика групп", callback_data="admin_stats")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# ---------- ОБРАБОТКА КНОПОК АДМИНКИ ----------
async def admin_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    if user.username != ADMIN_USERNAME:
        await query.answer("Недостаточно прав.", show_alert=True)
        return

    data = query.data

    if data == "admin_add_pack":
        await query.edit_message_text(
            "📝 **Добавление стикерпака**\n\n"
            "Напишите в одном сообщении:\n"
            "`<номер команды> <название пака> <сколько удалить с конца>`\n\n"
            "Где номер команды:\n"
            "`1` — /folk\n"
            "`2` — /litvin\n"
            "`3` — /bred\n\n"
            "Пример:\n"
            "`2 FolkPack 2`\n"
            "(добавит пак FolkPack в /litvin и удалит 2 последних стикера)\n\n"
            "`1 MyPack 0`\n"
            "(добавит пак MyPack в /folk, ничего не удаляя)",
            parse_mode="Markdown"
        )

    elif data == "admin_show_config":
        config = load_config()
        text = "📋 **Текущая конфигурация:**\n\n"
        for cmd in ["folk", "litvin", "bred"]:
            packs = config["commands"][cmd]
            text += f"**/{cmd}**:\n"
            if not packs:
                text += "  — нет паков\n"
            else:
                for i, pack in enumerate(packs, 1):
                    text += f"  {i}. `{pack['pack_name']}` (remove_last: {pack.get('remove_last', 0)})\n"
            text += "\n"
        await query.edit_message_text(text, parse_mode="Markdown")

    elif data == "admin_remove_pack":
        config = load_config()
        keyboard = []
        for cmd in ["folk", "litvin", "bred"]:
            for idx, pack in enumerate(config["commands"][cmd]):
                label = f"/{cmd}: {pack['pack_name']} (remove: {pack.get('remove_last',0)})"
                callback = f"removepack:{cmd}:{idx}"
                keyboard.append([InlineKeyboardButton(label, callback_data=callback)])
        if not keyboard:
            await query.edit_message_text("Нет добавленных стикерпаков.")
            return
        await query.edit_message_text("Выберите стикерпак для удаления:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_edit_remove":
        config = load_config()
        keyboard = []
        for cmd in ["folk", "litvin", "bred"]:
            for idx, pack in enumerate(config["commands"][cmd]):
                label = f"/{cmd}: {pack['pack_name']} (remove: {pack.get('remove_last',0)})"
                callback = f"editremove:{cmd}:{idx}"
                keyboard.append([InlineKeyboardButton(label, callback_data=callback)])
        if not keyboard:
            await query.edit_message_text("Нет добавленных стикерпаков.")
            return
        await query.edit_message_text("Выберите стикерпак для изменения remove_last:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_refresh_stickers":
        await query.answer("Перезагружаю стикеры...")
        await load_stickers(context.application)
        await query.edit_message_text(
            f"✅ Стикеры перезагружены!\n\n"
            f"Folk: {len(ALL_STICKERS)}\n"
            f"Litvin: {len(litvin_stickers)}\n"
            f"Bred: {len(bred_stickers)}"
        )

    elif data == "admin_clear_cooldowns":
        count_folk = len(cooldowns_folk)
        count_litvin = len(cooldowns_litvin)
        count_bred = len(cooldowns_bred)
        cooldowns_folk.clear()
        cooldowns_litvin.clear()
        cooldowns_bred.clear()
        pending_cooldown_input.clear()
        total = count_folk + count_litvin + count_bred
        await query.answer(f"Сброшено кулдаунов: {total}")
        await query.edit_message_text(
            f"🧹 Кулдауны сброшены:\n"
            f"/folk: {count_folk}\n"
            f"/litvin: {count_litvin}\n"
            f"/bred: {count_bred}"
        )

    elif data == "admin_stats":
        total_groups = sum(len(groups) for groups in user_groups.values())
        total_users = len(user_groups)
        await query.edit_message_text(
            f"📊 **Статистика**\n\n"
            f"👥 Пользователей с группами: {total_users}\n"
            f"💬 Всего групп: {total_groups}\n"
            f"🎯 Стикеров Folk: {len(ALL_STICKERS)}\n"
            f"🎯 Стикеров Litvin: {len(litvin_stickers)}\n"
            f"🎯 Стикеров Bred: {len(bred_stickers)}",
            parse_mode="Markdown"
        )

# ---------- ОБРАБОТКА УДАЛЕНИЯ/РЕДАКТИРОВАНИЯ ПАКОВ ----------
async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if user.username != ADMIN_USERNAME:
        await query.answer("Недостаточно прав.", show_alert=True)
        return

    data = query.data

    if data.startswith("removepack:"):
        _, cmd, idx = data.split(":")
        idx = int(idx)
        config = load_config()
        try:
            removed = config["commands"][cmd].pop(idx)
            save_config(config)
            await load_stickers(context.application)
            await query.edit_message_text(f"🗑 Пак `{removed['pack_name']}` удалён из /{cmd}. Стикеры перезагружены.", parse_mode="Markdown")
        except Exception as e:
            await query.answer(f"Ошибка: {e}", show_alert=True)

    elif data.startswith("editremove:"):
        _, cmd, idx = data.split(":")
        idx = int(idx)
        admin_state[user.id] = {"state": "waiting_remove_last", "command": cmd, "index": idx}
        config = load_config()
        pack = config["commands"][cmd][idx]
        await query.edit_message_text(
            f"Введите новое число удаляемых с конца стикеров для пака `{pack['pack_name']}` (0 или больше):",
            parse_mode="Markdown"
        )

    await query.answer()

# ---------- ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ОТ АДМИНА ----------
async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.username != ADMIN_USERNAME:
        return

    text = update.message.text.strip()

    # Проверяем формат "номер имя_пака число" для добавления пака
    if update.effective_chat.type == "private" and user.id not in admin_state:
        parts = text.split()
        if len(parts) == 3 and parts[0] in ("1", "2", "3") and parts[2].isdigit():
            cmd_map = {"1": "folk", "2": "litvin", "3": "bred"}
            cmd = cmd_map[parts[0]]
            pack_name = parts[1]
            remove_last = int(parts[2])
            if remove_last < 0:
                await update.message.reply_text("Число удаляемых стикеров не может быть отрицательным.")
                return

            config = load_config()
            existing = [p for p in config["commands"][cmd] if p["pack_name"] == pack_name]
            if existing:
                await update.message.reply_text("Этот стикерпак уже привязан к данной команде.")
                return

            config["commands"][cmd].append({"pack_name": pack_name, "remove_last": remove_last})
            save_config(config)
            await load_stickers(context.application)
            await update.message.reply_text(
                f"✅ Пак `{pack_name}` добавлен к /{cmd} (удалено с конца: {remove_last}).\n"
                f"Стикеров в команде теперь: {len(get_sticker_list_for_command(cmd))}",
                parse_mode="Markdown"
            )
            return

    # Если админ в состоянии ожидания
    if user.id not in admin_state:
        return

    state = admin_state[user.id]

    if state["state"] == "waiting_remove_last":
        cmd = state["command"]
        idx = state["index"]
        try:
            remove_last = int(text)
            if remove_last < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("Введите целое неотрицательное число. Операция отменена.")
            del admin_state[user.id]
            return

        config = load_config()
        try:
            pack = config["commands"][cmd][idx]
            pack["remove_last"] = remove_last
            save_config(config)
            await load_stickers(context.application)
            await update.message.reply_text(
                f"✅ Для пака `{pack['pack_name']}` (/{cmd}) remove_last установлен на {remove_last}.\n"
                f"Стикеры перезагружены.",
                parse_mode="Markdown"
            )
        except IndexError:
            await update.message.reply_text("Пак не найден. Операция отменена.")
        del admin_state[user.id]

# ---------- FLASK ДЛЯ MINI APP ----------
flask_app = Flask(__name__)

@flask_app.route('/getUserGroups')
def get_user_groups():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "no user_id"})
    try:
        uid = int(user_id)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid user_id"})
    groups = user_groups.get(uid, [])
    return jsonify({"ok": True, "result": groups})

@flask_app.route('/health')
def health():
    return jsonify({"status": "ok", "groups_stored": sum(len(v) for v in user_groups.values())})

def run_flask():
    flask_app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

# ---------- ЗАПУСК ----------
def main():
    load_user_groups()
    # Создаём конфиг с дефолтными паками, если его нет
    if not os.path.exists(CONFIG_FILE):
        default_config = load_config()  # эта функция уже возвращает дефолтный с паками
        save_config(default_config)

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("folk", folk))
    app.add_handler(CommandHandler("litvin", litvin))
    app.add_handler(CommandHandler("bred", bred))
    app.add_handler(CommandHandler("sosat", sosat))
    app.add_handler(CommandHandler("cooldown", cooldown_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(InlineQueryHandler(inline_query))

    app.add_handler(CallbackQueryHandler(cooldown_button_handler, pattern="^cooldown_select:"))
    app.add_handler(CallbackQueryHandler(handle_admin_callback, pattern="^(removepack|editremove):"))
    app.add_handler(CallbackQueryHandler(admin_button_handler, pattern="^admin_"))

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_chat_members))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_cooldown_input), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text), group=2)

    app.job_queue.run_repeating(update_group_info, interval=1800, first=60)

    import asyncio
    loop = asyncio.get_event_loop()
    loop.run_until_complete(load_stickers(app))

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logging.info("Flask API запущен на порту 5000")

    logging.info("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
