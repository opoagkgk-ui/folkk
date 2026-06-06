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
bred_stickers = []

cooldowns_folk = {}
cooldowns_litvin = {}
cooldowns_bred = {}

chat_cooldowns = {}
pending_cooldown_input = {}

admin_state = {}

USER_GROUPS_FILE = "user_groups.json"
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
        except:
            user_groups = {}

def save_user_groups():
    try:
        with open(USER_GROUPS_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_groups, f, ensure_ascii=False, indent=2)
    except:
        pass

# ---------- ЗАГРУЗКА СТИКЕРОВ (ПРОСТАЯ ВЕРСИЯ) ----------
STICKER_PACKS = {
    "folk": [
        ("ByFolkValley", 0),
        ("AtlasScottishFold", 0),
        ("Vooocaaa_by_fStikBot", 2),
    ],
    "litvin": [
        ("pk_2746611_by_Ctikerubot", 2),
    ],
    "bred": [
        ("DouBlya", 0),
        ("Fartsmopington_by_MoiStikiBot", 0),
    ],
}

async def load_stickers(app: Application):
    global ALL_STICKERS, litvin_stickers, bred_stickers

    all_folk = []
    all_litvin = []
    all_bred = []

    for command, packs in STICKER_PACKS.items():
        for pack_name, remove_last in packs:
            try:
                pack = await app.bot.get_sticker_set(pack_name)
                stickers = [s.file_id for s in pack.stickers]
                if remove_last > 0 and len(stickers) > remove_last:
                    stickers = stickers[:-remove_last]
                
                if command == "folk":
                    all_folk.extend(stickers)
                elif command == "litvin":
                    all_litvin.extend(stickers)
                elif command == "bred":
                    all_bred.extend(stickers)
                
                logging.info(f"Пак {pack_name} -> /{command}, +{len(stickers)} стикеров")
            except Exception as e:
                logging.error(f"Не удалось загрузить {pack_name}: {e}")

    ALL_STICKERS = all_folk
    litvin_stickers = all_litvin
    bred_stickers = all_bred
    logging.info(f"Готово: folk={len(ALL_STICKERS)} litvin={len(litvin_stickers)} bred={len(bred_stickers)}")

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ КУЛДАУНА ----------
def get_cd_duration(chat_id, command):
    if chat_id not in chat_cooldowns:
        chat_cooldowns[chat_id] = {'folk': 300, 'litvin': 300, 'bred': 300}
    return chat_cooldowns[chat_id].get(command, 300)

def get_cooldown_dict(command):
    if command == 'folk': return cooldowns_folk
    elif command == 'litvin': return cooldowns_litvin
    elif command == 'bred': return cooldowns_bred
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
                        "member_count": 0,
                        "invite_link": None,
                        "photo_url": None
                    }
                    if creator_id not in user_groups:
                        user_groups[creator_id] = []
                    existing = [g for g in user_groups[creator_id] if g["chat_id"] == chat.id]
                    if not existing:
                        user_groups[creator_id].append(group_info)
                        save_user_groups()
                        logging.info(f"Группа '{chat.title}' сохранена для {creator_id}")
            except Exception as e:
                logging.error(f"Ошибка сохранения группы: {e}")

# ---------- КОМАНДЫ ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        keyboard = [[InlineKeyboardButton("👤 Профиль", web_app=WebAppInfo(url=MINI_APP_URL))]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = (
            "👋 Привет! Я бот с мемными стикерами Folk Valley.\n\n"
            "• В любом чате введи @folkvalleybot — я отправлю случайный стикер.\n"
            "• В группе: /folk, /litvin, /bred, /sosat, /cooldown\n\n"
            "👤 Кнопка «Профиль» — Mini App с группами."
        )
        await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        text = "Я в группе! /folk, /litvin, /bred, /sosat, /cooldown"
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
        await update.message.reply_text("Стикеры пока не загружены. Попробуй позже.")
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
        await update.message.reply_text("Стикеры пока не загружены.")
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
        await update.message.reply_text("Стикеры пока не загружены.")
        return
    sticker_id = random.choice(bred_stickers)
    await update.message.reply_sticker(sticker=sticker_id)
    set_cooldown_used(chat_id, user_id, 'bred')

async def sosat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = random.randint(3, 6)
    words = random.choices(RANDOM_WORDS, k=count)
    await update.message.reply_text(" ".join(words))

# ---------- КУЛДАУНЫ ----------
async def cooldown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Только для групп.")
        return
    try:
        admins = await context.bot.get_chat_administrators(chat.id)
    except:
        await update.message.reply_text("Бот должен быть админом.")
        return
    creator_id = None
    for admin in admins:
        if admin.status == ChatMemberStatus.OWNER:
            creator_id = admin.user.id
            break
    if user.id != creator_id:
        await update.message.reply_text("Только создатель группы.")
        return

    folk_cd = get_cd_duration(chat.id, 'folk')
    litvin_cd = get_cd_duration(chat.id, 'litvin')
    bred_cd = get_cd_duration(chat.id, 'bred')
    text = f"⚙️ Кулдауны:\n/folk: {folk_cd}с\n/litvin: {litvin_cd}с\n/bred: {bred_cd}с\n\nВыбери команду:"
    keyboard = [
        [InlineKeyboardButton(f"Folk ({folk_cd}с)", callback_data="cd:folk")],
        [InlineKeyboardButton(f"Litvin ({litvin_cd}с)", callback_data="cd:litvin")],
        [InlineKeyboardButton(f"Bred ({bred_cd}с)", callback_data="cd:bred")],
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def cooldown_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
    except:
        await query.answer("Бот должен быть админом.", show_alert=True)
        return
    creator_id = None
    for admin in admins:
        if admin.status == ChatMemberStatus.OWNER:
            creator_id = admin.user.id
            break
    if user.id != creator_id:
        await query.answer("Только создатель.", show_alert=True)
        return
    command = query.data.split(":")[1]
    pending_cooldown_input[(chat_id, user.id)] = command
    await query.answer()
    await query.edit_message_text(f"Введи кулдаун для /{command} в секундах (0-3600):")

async def handle_cooldown_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    key = (chat_id, user.id)
    if key not in pending_cooldown_input:
        return
    command = pending_cooldown_input.pop(key)
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Нужно число. Отмена.")
        return
    seconds = int(text)
    if not 0 <= seconds <= 3600:
        await update.message.reply_text("0-3600. Отмена.")
        return
    if chat_id not in chat_cooldowns:
        chat_cooldowns[chat_id] = {}
    chat_cooldowns[chat_id][command] = seconds
    await update.message.reply_text(f"✅ /{command}: {seconds}с")

# ---------- ИНЛАЙН ----------
async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ALL_STICKERS:
        await update.inline_query.answer([], cache_time=0)
        return
    sticker_id = random.choice(ALL_STICKERS)
    results = [InlineQueryResultCachedSticker(id=str(random.randint(100000, 999999)), sticker_file_id=sticker_id)]
    await update.inline_query.answer(results, cache_time=0)

# ---------- FLASK ----------
flask_app = Flask(__name__)

@flask_app.route('/getUserGroups')
def get_user_groups():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"ok": False})
    groups = user_groups.get(int(user_id), [])
    return jsonify({"ok": True, "result": groups})

def run_flask():
    flask_app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

# ---------- ЗАПУСК ----------
def main():
    load_user_groups()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("folk", folk))
    app.add_handler(CommandHandler("litvin", litvin))
    app.add_handler(CommandHandler("bred", bred))
    app.add_handler(CommandHandler("sosat", sosat))
    app.add_handler(CommandHandler("cooldown", cooldown_command))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(CallbackQueryHandler(cooldown_button, pattern="^cd:"))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_chat_members))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_cooldown_input))

    import asyncio
    loop = asyncio.get_event_loop()
    loop.run_until_complete(load_stickers(app))

    threading.Thread(target=run_flask, daemon=True).start()
    logging.info("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
