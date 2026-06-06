import logging
import random
import json
import os
import asyncio
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from telegram import Update, InlineQueryResultCachedSticker, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application,
    CommandHandler,
    InlineQueryHandler,
    CallbackQueryHandler,
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

# ---------- ЛОГИ ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ---------- ГЛОБАЛЬНЫЕ ДАННЫЕ ----------
ALL_STICKERS = []
litvin_stickers = []
bred_stickers = []

cooldowns_folk = {}
cooldowns_litvin = {}
cooldowns_bred = {}

chat_cooldowns = {}
pending_cooldown_input = {}

USER_GROUPS_FILE = "user_groups.json"
user_groups = {}

# ---------- ЗАГРУЗКА/СОХРАНЕНИЕ ГРУПП ----------
def load_user_groups():
    global user_groups
    if os.path.exists(USER_GROUPS_FILE):
        try:
            with open(USER_GROUPS_FILE, 'r', encoding='utf-8') as f:
                user_groups = {int(k): v for k, v in json.load(f).items()}
        except:
            user_groups = {}

def save_user_groups():
    try:
        with open(USER_GROUPS_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_groups, f, ensure_ascii=False, indent=2)
    except:
        pass

# ---------- СТИКЕРПАКИ ----------
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

# ---------- ЗАГРУЗКА СТИКЕРОВ (ПРОВЕРЕННАЯ ВЕРСИЯ) ----------
async def load_stickers(app: Application):
    global ALL_STICKERS, litvin_stickers, bred_stickers

    all_folk, all_litvin, all_bred = [], [], []

    for command, packs in STICKER_PACKS.items():
        for pack_name, remove_last in packs:
            try:
                pack = await app.bot.get_sticker_set(pack_name)
                stickers = [s.file_id for s in pack.stickers]

                if remove_last > 0 and len(stickers) > remove_last:
                    stickers = stickers[:-remove_last]
                    logging.info(f"Пак {pack_name}: удалено {remove_last} с конца")

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
    logging.info(f"Всего: folk={len(ALL_STICKERS)} litvin={len(litvin_stickers)} bred={len(bred_stickers)}")

# ---------- КУЛДАУНЫ ----------
def get_cd(chat_id, command):
    if chat_id not in chat_cooldowns:
        chat_cooldowns[chat_id] = {'folk': 300, 'litvin': 300, 'bred': 300}
    return chat_cooldowns[chat_id].get(command, 300)

def get_cd_dict(command):
    if command == 'folk': return cooldowns_folk
    elif command == 'litvin': return cooldowns_litvin
    return cooldowns_bred

def check_cd(chat_id, user_id, command):
    duration = get_cd(chat_id, command)
    if duration == 0:
        return False, None
    cd = get_cd_dict(command)
    key = (chat_id, user_id)
    now = datetime.now()
    if key in cd and (now - cd[key]) < timedelta(seconds=duration):
        remain = cd[key] + timedelta(seconds=duration) - now
        return True, remain
    return False, None

def use_cd(chat_id, user_id, command):
    get_cd_dict(command)[(chat_id, user_id)] = datetime.now()

# ---------- КОМАНДЫ ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        keyboard = [[InlineKeyboardButton("👤 Профиль", web_app=WebAppInfo(url=MINI_APP_URL))]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = (
            "👋 Привет! Я бот Folk Valley.\n\n"
            "• @folkvalleybot в любом чате — случайный стикер\n"
            "• /folk, /litvin, /bred — стикеры\n"
            "• /sosat — бессвязный бред\n"
            "• /cooldown — настройка кулдаунов (владелец группы)"
        )
        await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text("Я в группе! /folk /litvin /bred /sosat /cooldown")

async def folk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id, user_id = update.effective_chat.id, update.effective_user.id
    cool, remain = check_cd(chat_id, user_id, 'folk')
    if cool:
        m, s = divmod(remain.seconds, 60)
        await update.message.reply_text(f"⏳ {m} мин {s} сек", quote=True)
        return
    if not ALL_STICKERS:
        await update.message.reply_text("Стикеры не загружены.")
        return
    await update.message.reply_sticker(sticker=random.choice(ALL_STICKERS))
    use_cd(chat_id, user_id, 'folk')

async def litvin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id, user_id = update.effective_chat.id, update.effective_user.id
    cool, remain = check_cd(chat_id, user_id, 'litvin')
    if cool:
        m, s = divmod(remain.seconds, 60)
        await update.message.reply_text(f"⏳ {m} мин {s} сек", quote=True)
        return
    if not litvin_stickers:
        await update.message.reply_text("Стикеры не загружены.")
        return
    await update.message.reply_sticker(sticker=random.choice(litvin_stickers))
    use_cd(chat_id, user_id, 'litvin')

async def bred(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id, user_id = update.effective_chat.id, update.effective_user.id
    cool, remain = check_cd(chat_id, user_id, 'bred')
    if cool:
        m, s = divmod(remain.seconds, 60)
        await update.message.reply_text(f"⏳ {m} мин {s} сек", quote=True)
        return
    if not bred_stickers:
        await update.message.reply_text("Стикеры не загружены.")
        return
    await update.message.reply_sticker(sticker=random.choice(bred_stickers))
    use_cd(chat_id, user_id, 'bred')

async def sosat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    words = random.choices(RANDOM_WORDS, k=random.randint(3, 6))
    await update.message.reply_text(" ".join(words))

# ---------- КУЛДАУН КОМАНДА ----------
async def cooldown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Только в группах.")
        return
    try:
        admins = await context.bot.get_chat_administrators(chat.id)
        owner = next((a for a in admins if a.status == "creator"), None)
        if not owner or user.id != owner.user.id:
            await update.message.reply_text("Только создатель группы.")
            return
    except:
        await update.message.reply_text("Бот должен быть администратором.")
        return

    f, l, b = get_cd(chat.id, 'folk'), get_cd(chat.id, 'litvin'), get_cd(chat.id, 'bred')
    kb = [
        [InlineKeyboardButton(f"Folk ({f}с)", callback_data="cd:folk")],
        [InlineKeyboardButton(f"Litvin ({l}с)", callback_data="cd:litvin")],
        [InlineKeyboardButton(f"Bred ({b}с)", callback_data="cd:bred")],
    ]
    await update.message.reply_text(
        f"⚙️ Кулдауны:\n/fold: {f}с\n/litvin: {l}с\n/bred: {b}с\n\nВыбери команду:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def cd_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    chat_id, user = q.message.chat_id, q.from_user
    cmd = q.data.split(":")[1]
    pending_cooldown_input[(chat_id, user.id)] = cmd
    await q.answer()
    await q.edit_message_text(f"Введи новый кулдаун для /{cmd} (0-3600 секунд):")

async def cd_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = (update.effective_chat.id, update.effective_user.id)
    if key not in pending_cooldown_input:
        return
    cmd = pending_cooldown_input.pop(key)
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Нужно число. Отмена.")
        return
    sec = int(text)
    if not 0 <= sec <= 3600:
        await update.message.reply_text("0-3600. Отмена.")
        return
    if update.effective_chat.id not in chat_cooldowns:
        chat_cooldowns[update.effective_chat.id] = {}
    chat_cooldowns[update.effective_chat.id][cmd] = sec
    await update.message.reply_text(f"✅ /{cmd}: {sec}с")

# ---------- ИНЛАЙН ----------
async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ALL_STICKERS:
        await update.inline_query.answer([], cache_time=0)
        return
    sid = random.choice(ALL_STICKERS)
    await update.inline_query.answer([
        InlineQueryResultCachedSticker(id=str(random.randint(100000, 999999)), sticker_file_id=sid)
    ], cache_time=0)

# ---------- FLASK ----------
flask_app = Flask(__name__)

@flask_app.route('/getUserGroups')
def get_user_groups():
    uid = request.args.get('user_id')
    if not uid:
        return jsonify({"ok": False})
    return jsonify({"ok": True, "result": user_groups.get(int(uid), [])})

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
    app.add_handler(CommandHandler("cooldown", cooldown_cmd))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(CallbackQueryHandler(cd_button, pattern="^cd:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cd_input))

    loop = asyncio.get_event_loop()
    loop.run_until_complete(load_stickers(app))

    threading.Thread(target=run_flask, daemon=True).start()
    logging.info("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main() 
