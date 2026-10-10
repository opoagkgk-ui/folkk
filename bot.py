import os
import logging
import requests
import urllib.parse
import asyncio
import random
import json
import io
import threading
import base64
import aiohttp
import psutil
import time
import shutil
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    InlineQueryResultCachedSticker, WebAppInfo, PreCheckoutQuery,
)
from aiogram.exceptions import TelegramBadRequest

from deep_translator import GoogleTranslator
from gtts import gTTS
from io import BytesIO

# ==================== ТОКЕН ИЗ ОКРУЖЕНИЯ ====================
TOKEN = os.environ.get("API_TOKEN")
if not TOKEN:
    raise ValueError("Переменная окружения API_TOKEN не установлена!")

ADMIN_ID = 8371473442
MINI_APP_URL = "https://jalal-p7p9.onrender.com"

IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY", "")
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")

# ==================== МОНИТОРИНГ ====================
MONITOR_CHAT_ID = -1003805849851
MONITOR_INTERVAL = 25 * 60
START_TIME = datetime.now()

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
log = logging.getLogger("folkvalley")

router = Router()
bot: Bot = None

# ==================== ПУТИ ====================
CHATS_DB_FILE = "/app/shared/all_chats.json"
DONATIONS_FILE = "/app/shared/donations.json"
USER_STATS_FILE = "/app/shared/user_stats.json"
USER_GROUPS_FILE = "/app/shared/user_groups.json"
OFFER_RULES_URL = "https://telegra.ph/Pravila-otpravki-predlozhenij-08-22"

CARDS_DATA_FILE = "/app/shared/cards_data.json"
USER_CARDS_FILE = "/app/shared/user_cards.json"
AUCTION_FILE = "/app/shared/auction_lots.json"
card_cooldowns = {}

# ==================== ВРЕМЕННЫЕ ДАННЫЕ ====================
temp_donation_amounts = {}
pending_broadcast_all = {}
pending_cooldown_input = {}
user_stats = {}
games = {}
game_timers = {}
user_groups = {}

cooldowns_folk = {}
cooldowns_litvin = {}
cooldowns_bred = {}
cooldowns_search = {}
cooldowns_voice = {}
chat_cooldowns = {}


# ==================== УТИЛИТЫ ====================
def get_args(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    return parts[1].split() if len(parts) > 1 else []


def escape_markdown(text):
    for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
        text = text.replace(ch, f'\\{ch}')
    return text


# ==================== МИГРАЦИЯ ====================
def migrate_files():
    os.makedirs("/app/shared", exist_ok=True)
    for src, dst in [("all_chats.json", CHATS_DB_FILE), ("donations.json", DONATIONS_FILE),
                     ("user_stats.json", USER_STATS_FILE), ("user_groups.json", USER_GROUPS_FILE)]:
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                shutil.copy2(src, dst)
                print(f"✅ Перенесён {src} -> {dst}")
            except Exception as e:
                print(f"⚠️ Не удалось перенести {src}: {e}")


# ==================== МОНИТОРИНГ ====================
def get_system_info():
    uptime_str = str(datetime.now() - START_TIME).split('.')[0]
    try:
        start = time.time()
        requests.get("https://api.telegram.org", timeout=5)
        ping = round((time.time() - start) * 1000, 2)
    except Exception:
        ping = "Ошибка"
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    return {
        "uptime": uptime_str, "ping": ping, "cpu": cpu,
        "ram_used": round(ram.used / (1024**3), 2),
        "ram_total": round(ram.total / (1024**3), 2),
        "ram_percent": ram.percent,
    }


async def monitor_loop():
    await asyncio.sleep(10)
    while True:
        try:
            info = await asyncio.to_thread(get_system_info)
            cpu_s = "🟢" if info["cpu"] < 70 else "🟡" if info["cpu"] < 90 else "🔴"
            ram_s = "🟢" if info["ram_percent"] < 70 else "🟡" if info["ram_percent"] < 90 else "🔴"
            ping_s = "🟢" if info["ping"] != "Ошибка" and info["ping"] < 200 else "🟡" if info["ping"] != "Ошибка" and info["ping"] < 500 else "🔴"
            text = (
                f"📊 **Статус бота**\n\n"
                f"⏱ **Аптайм:** {info['uptime']}\n"
                f"{ping_s} **Пинг:** {info['ping']} мс\n\n"
                f"💻 **Нагруженность:**\n"
                f"  {cpu_s} CPU: {info['cpu']}%\n"
                f"  {ram_s} RAM: {info['ram_used']} ГБ / {info['ram_total']} ГБ ({info['ram_percent']}%)\n\n"
                f"🕐 Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
            )
            await bot.send_message(MONITOR_CHAT_ID, text, parse_mode="Markdown")
        except Exception as e:
            log.error(f"Ошибка мониторинга: {e}")
        await asyncio.sleep(MONITOR_INTERVAL)


# ==================== ЧАТЫ ====================
def save_chat_id(chat_id):
    try:
        with open(CHATS_DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = []
    if chat_id not in data:
        data.append(chat_id)
        with open(CHATS_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ==================== ДОНАТЫ ====================
def load_donations():
    try:
        with open(DONATIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_donations(d):
    with open(DONATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def add_donation(user_id, amount):
    d = load_donations()
    uid = str(user_id)
    d.setdefault(uid, {"total": 0, "count": 0, "last": None})
    d[uid]["total"] += amount
    d[uid]["count"] += 1
    d[uid]["last"] = datetime.now().isoformat()
    save_donations(d)


# ==================== РЕЙТИНГ ====================
def load_stats():
    global user_stats
    if os.path.exists(USER_STATS_FILE):
        try:
            with open(USER_STATS_FILE, 'r', encoding='utf-8') as f:
                user_stats = {int(k): {int(u): c for u, c in v.items()} for k, v in json.load(f).items()}
        except Exception:
            user_stats = {}


def save_stats():
    try:
        with open(USER_STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def add_activity(chat_id, user_id):
    chat_id, user_id = int(chat_id), int(user_id)
    user_stats.setdefault(chat_id, {})
    user_stats[chat_id][user_id] = user_stats[chat_id].get(user_id, 0) + 1
    save_stats()


# ==================== КАРТОЧКИ ====================
def load_cards_data():
    os.makedirs("/app/shared", exist_ok=True)
    default_cards = {
        "common_1": {"name": "Атлас", "rarity": "обычная",
                     "file_id": "AgACAgIAAxkBAAInf2qWul0Ge41cc-qr_grWPmHgtWhNAAKsH2sbFcKwSN8vUM89f1BZAQADAgADeQADPQQ"},
        "common_2": {"name": "Лысый Атлас", "rarity": "обычная",
                     "file_id": "AgACAgIAAxkBAAInmGqWyDv-LxsJ5KfarMoXlN0ijBz7AAKKImsbi6m4SJ-2JgTQoZWcAQADAgADeQADPQQ"},
        "rare_1": {"name": "Кудрявый Атлас", "rarity": "редкая",
                   "file_id": "AgACAgIAAxkBAAInn2qWyUEww97gD1i8ZPSKTK-lkdBlAAKfImsbi6m4SPniHV4q3992AQADAgADeQADPQQ"},
        "rare_2": {"name": "Проказник", "rarity": "редкая",
                   "file_id": "AgACAgIAAxkBAAIoG2qXBuXziyDulVfs7ONvLwhFVOAmAAIpJGsbi6m4SHsGTJ8d0BS8AQADAgADeAADPQQ"},
        "epic_1": {"name": "Атлас Мафиози", "rarity": "эпическая",
                   "file_id": "AgACAgIAAxkBAAIoJGqXCDyox3KSUQ65lYsR99KKhnzvAAItJGsbi6m4SAi6CPAL5tCEAQADAgADeAADPQQ"},
        "epic_2": {"name": "Атлас Мудрец", "rarity": "эпическая",
                   "file_id": "AgACAgIAAxkBAAIoLWqXCUrJ8JWLtemYZjUezwRxqI75AAI1JGsbi6m4SOxGxQPxb07SAQADAgADeQADPQQ"},
        "mythic_1": {"name": "Атлас Эмо", "rarity": "мифическая",
                     "file_id": "AgACAgIAAxkBAAIoOWqXC8587-jtnoR2skOlkHvIJRoGAAJAJGsbi6m4SNk7Vco6Q0lKAQADAgADeQADPQQ"},
        "mythic_2": {"name": "4К Атлас", "rarity": "мифическая",
                     "file_id": "AgACAgIAAxkBAAIoQGqXD_wj6z3DWGzbrNM90qP-1axxAAJZJGsbi6m4SMOzON2frSMqAQADAgADeQADPQQ"},
        "legendary_1": {"name": "Атлас Б.", "rarity": "легендарная",
                        "file_id": "AgACAgIAAxkBAAIoR2qXEQAB3zVKIo88pnXl9Bz9FBBiyQACXyRrG4upuEgbwoClJyOkxAEAAwIAA3kAAz0E"},
        "legendary_2": {"name": "Легендарная карточка 2", "rarity": "легендарная", "file_id": "1111111111"},
        "secret_1": {"name": "Секретная карточка", "rarity": "секретная", "file_id": "1111111111"},
    }
    try:
        with open(CARDS_DATA_FILE, "r", encoding="utf-8") as f:
            cards = json.load(f)
        if not isinstance(cards, dict):
            cards = {}
    except FileNotFoundError:
        cards = {}
    except json.JSONDecodeError:
        log.exception("cards_data.json битый")
        cards = {}
    cards.update(default_cards)
    return cards


def save_cards_data(cards):
    with open(CARDS_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)


def load_user_cards():
    os.makedirs("/app/shared", exist_ok=True)
    try:
        with open(USER_CARDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_user_cards(data):
    with open(USER_CARDS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_auction():
    os.makedirs("/app/shared", exist_ok=True)
    try:
        with open(AUCTION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_auction(data):
    with open(AUCTION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user_card_data(user_id):
    data = load_user_cards()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {"cards": [], "balance": 0, "total_cards": 0, "first_card": False}
        save_user_cards(data)
    return data[uid]


def save_user_card_data(user_id, user_data):
    data = load_user_cards()
    data[str(user_id)] = user_data
    save_user_cards(data)


def generate_card_instance_id():
    return f"card_{int(time.time()*1000)}_{random.randint(1000,9999)}"


def roll_rarity(is_premium=False):
    rarities = ({"обычная": 5, "редкая": 20, "эпическая": 30, "мифическая": 25, "легендарная": 18, "секретная": 2}
                if is_premium else
                {"обычная": 40, "редкая": 25, "эпическая": 20, "мифическая": 10, "легендарная": 4, "секретная": 1})
    total = sum(rarities.values())
    roll = random.randint(1, total)
    cum = 0
    for r, c in rarities.items():
        cum += c
        if roll <= cum:
            return r
    return "обычная"


def get_card_by_rarity(rarity):
    cards = load_cards_data()
    available = [cid for cid, c in cards.items() if c["rarity"] == rarity]
    if not available:
        return None, None
    cid = random.choice(available)
    return cid, cards[cid]


def add_card_to_user(user_id, card_id, card_data):
    ud = get_user_card_data(user_id)
    new_card = {
        "instance_id": generate_card_instance_id(),
        "card_id": card_id,
        "name": card_data["name"],
        "rarity": card_data["rarity"],
        "file_id": card_data["file_id"],
    }
    ud["cards"].append(new_card)
    ud["total_cards"] += 1
    if not ud.get("first_card", False):
        ud["first_card"] = True
        ud["balance"] = 100
    save_user_card_data(user_id, ud)
    return new_card


def get_user_balance(user_id):
    return get_user_card_data(user_id).get("balance", 0)


def update_user_balance(user_id, amount):
    ud = get_user_card_data(user_id)
    ud["balance"] = ud.get("balance", 0) + amount
    save_user_card_data(user_id, ud)
    return ud["balance"]


# ==================== IMGBB ====================
def upload_to_imgbb(image_bytes):
    url = "https://api.imgbb.com/1/upload"
    encoded = base64.b64encode(image_bytes).decode('utf-8')
    payload = {"key": IMGBB_API_KEY, "image": encoded, "name": "meme.jpg", "expiration": 86400}
    try:
        resp = requests.post(url, data=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["data"]["url"] if data.get("success") else None
    except Exception as e:
        log.error(f"ImgBB: {e}")
        return None


# ==================== ПЕРЕВОД ====================
def translate_text(text, target_lang='en'):
    try:
        return GoogleTranslator(source='auto', target=target_lang).translate(text)
    except Exception as e:
        log.error(f"Перевод: {e}")
        return text


# ==================== КУЛДАУНЫ ====================
def load_user_groups():
    global user_groups
    if os.path.exists(USER_GROUPS_FILE):
        try:
            with open(USER_GROUPS_FILE, 'r', encoding='utf-8') as f:
                user_groups = {int(k): v for k, v in json.load(f).items()}
        except Exception:
            user_groups = {}


def save_user_groups():
    try:
        with open(USER_GROUPS_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_groups, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_cd(chat_id, command):
    if chat_id not in chat_cooldowns:
        chat_cooldowns[chat_id] = {'folk': 60, 'litvin': 60, 'bred': 60, 'search': 600, 'voice': 30}
    return chat_cooldowns[chat_id].get(command, 60 if command != 'search' else 600)


def get_cd_dict(command):
    return {'folk': cooldowns_folk, 'litvin': cooldowns_litvin, 'bred': cooldowns_bred,
            'search': cooldowns_search, 'voice': cooldowns_voice}.get(command, {})


def check_cd(chat_id, user_id, command):
    duration = get_cd(chat_id, command)
    if duration == 0:
        return False, None
    cd = get_cd_dict(command)
    key = (chat_id, user_id)
    now = datetime.now()
    if key in cd and (now - cd[key]) < timedelta(seconds=duration):
        return True, cd[key] + timedelta(seconds=duration) - now
    return False, None


def use_cd(chat_id, user_id, command):
    get_cd_dict(command)[(chat_id, user_id)] = datetime.now()


# ==================== UNSPLASH ====================
async def search_unsplash(query, per_page=10):
    url = "https://api.unsplash.com/search/photos"
    headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
    params = {"query": query, "per_page": per_page, "page": 1}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return [item["urls"]["regular"] for item in data.get("results", [])]
        except Exception as e:
            log.error(f"Unsplash: {e}")
            return []


# ==================== ВОПРОСЫ ДЛЯ /spin ====================
SPIN_QUESTIONS = [
    "Какая самая странная еда, которую ты пробовал?",
    "Если бы ты мог выбрать суперспособность, которая была бы абсолютно бесполезной — какую бы выбрал?",
    "Что бы ты делал, если бы на 24 часа стал невидимым?",
    "Какая самая глупая вещь, которую ты делал на камеру?",
    "Если бы ты мог говорить с животными, что бы спросил у своего питомца?",
    "Какая твоя самая неловкая ситуация в школе/на работе?",
    "Если бы ты был героем фильма, какой бы это был фильм?",
    "Какой самый странный сон ты видел?",
    "Что бы ты спросил у инопланетян, если бы они прилетели?",
    "Если бы ты мог отменить один закон в мире, какой бы это был закон?",
    "Какая самая смешная шутка, которую ты слышал?",
    "Если бы ты мог жить в любой эпохе, какую бы выбрал?",
    "Что бы ты делал, если бы выиграл в лотерею 10 миллионов?",
    "Какой твой самый стыдный момент в интернете?",
    "Если бы ты мог поменяться жизнью с любым человеком, с кем бы поменялся?",
]

# ==================== СЛОВА ДЛЯ /sosat ====================
RANDOM_WORDS = [
    "кот", "привет", "чайник", "Владимир", "мандарин", "космос", "велосипед",
    "одуванчик", "банан", "дракон", "шлёпа", "мем", "бот", "пельмень",
    "капибара", "флекс", "вайб", "фолк", "долина", "сковорода", "сыр",
    "подушка", "кактус", "утюг", "закат", "шнурок", "лампочка", "кнопка",
    "огурец", "микрофон", "самокат", "трамвай", "облако", "одуван"
]

# ==================== ФАКТЫ ====================
FACTS = [
    "ты однажды пытался объяснить бабушке, что такое мем — и она до сих пор думает, что это новый вид супа",
    "ты платишь за подписку на музыку, но слушаешь только песни 90-х из своего детства",
    "ты готовишь еду на 3 дня вперёд, но съедаешь всё за один вечер",
    "ты сохраняешь посты в Instagram 'на потом' и никогда туда не возвращаешься",
    "ты искал свой телефон, держа его в руках, 3 раза за последнюю неделю",
    "ты включаешь уведомления в игре, чтобы случайно не пропустить сбор ресурсов",
    "ты пересматриваешь 'Офис' уже 5 раз, хотя знаешь все шутки наизусть",
    "ты заказываешь доставку еды, потому что лень идти на кухню за 5 метров",
    "ты смотришь видео с ремонтом квартир, хотя сам не забил гвоздь ни разу в жизни",
    "ты добавляешь книги в список 'хочу прочитать' и забываешь про них навсегда",
    "ты на работе открываешь Excel, а сам скроллишь мемы",
    "ты пьёшь кофе в 10 вечера и удивляешься, почему не спишь",
    "ты просыпаешься за 5 минут до будильника и злишься на целый день",
    "ты считаешь, что салат — это здоровая еда, пока не зальёшь его майонезом",
    "ты готов на всё ради скидки 5% в магазине, даже на абонемент в спортзал",
    "ты пересматриваешь своё фото 20 раз, чтобы решить, нравится ли оно тебе",
    "ты в 2 часа ночи смотришь видео с алмазными мозаиками и хочешь купить одну",
    "ты делишься мемом в чат, хотя уже отправил его вчера",
    "ты в магазине берёшь корзину, но в итоге покупаешь только хлеб и молоко",
    "ты не можешь пройти мимо зеркала, не сделав странное лицо",
    "ты планируешь начать бегать с понедельника каждую неделю уже год",
    "ты считаешь шаги до холодильника за тренировку",
    "ты смотришь прогноз погоды и всё равно выходишь без зонта",
    "ты отвечаешь на сообщения через 3 часа, потому что 'думал над ответом'",
    "ты в спорах всегда прав, даже если это признаёшь только мысленно",
    "ты сохраняешь рецепты из интернета, но готовишь только доширак",
    "ты идёшь в магазин за одним товаром, а возвращаешься с 5 пакетами",
    "ты проверяешь телефон во время просмотра фильма и перематываешь назад 5 раз",
    "ты считаешь, что у тебя есть суперспособность — находить потерянные вещи, когда они уже не нужны",
    "ты обещаешь себе меньше сидеть в телефоне, но это сообщение — подтверждение обратного",
    "ты думал, что квартира убирается сама, пока не понял, что это был ты",
    "ты смотришь тиктоки и смеёшься, даже когда никто не видит",
    "ты один раз попытался приготовить ужин и с тех пор заказываешь доставку",
    "ты считаешь, что кофе — это не напиток, а состояние души",
    "ты включаешь телевизор и засыпаешь под него, а просыпаешься — он всё ещё работает",
    "ты прячешь сладости от себя и находишь их через неделю",
    "ты считаешь, что после 23:00 все решения становятся гениальными",
    "ты нажимаешь 'пропустить рекламу', даже если она тебе интересна",
    "ты заводишь будильник за час до выхода и всё равно опаздываешь",
    "ты гуглишь симптомы и находишь у себя все болезни, включая вымышленные",
    "ты в 3 ночи думаешь о том, что сделал не так 5 лет назад",
    "ты пересматриваешь старые чаты и понимаешь, что был слишком странным",
    "ты фотографируешь еду, но не выкладываешь, потому что забыл",
    "ты отвечаешь 'да, я в курсе', хотя понятия не имеешь, о чём речь",
    "ты думал, что взрослая жизнь — это свобода, а это просто бесконечные счета",
    "ты просыпаешься и думаешь: 'сегодня всё изменю', а заканчиваешь день дошираком",
    "ты считаешь, что твой кот понимает тебя лучше, чем люди",
    "ты включаешь режим 'не беспокоить', но всё равно проверяешь телефон каждые 5 минут",
    "ты купил абонемент в спортзал и ходишь туда только за водой",
    "ты считаешь, что мемы — это искусство, и никто не переубедит тебя",
    "ты один раз разбил телефон и неделю жил без него — это были лучшие дни",
    "ты считаешь, что у тебя есть 6-е чувство — чувство, что кто-то смотрит, когда ты ешь",
    "ты начинаешь уборку с одного угла, а заканчиваешь в другом и уже не помнишь, что делал",
    "ты считаешь, что инопланетяне уже здесь, и они просто ждут удобного момента",
    "ты покупаешь книгу и читаешь её, только если она есть в аудиоформате",
    "ты сохраняешь важные фотографии на телефон и забываешь их там",
    "ты откладываешь важные дела на 'завтра' уже 3 года",
    "ты считаешь, что у котиков есть свои мем-шпионы",
    "ты готовишь настолько сложные ужины, что проще было заказать пиццу",
    "ты считаешь, что тишина в чате — это признак того, что все заняты мемами",
    "ты просыпаешься от звука собственных мыслей",
    "ты уже год обещаешь себе выучить английский, но учишь только мемы на английском",
    "ты считаешь, что авокадо — это переоценённый овощ, но всё равно его покупаешь",
    "ты включаешь сериал на фоне и не понимаешь, что происходит, но смотришь до конца",
    "ты считаешь, что кофе с утра — это ритуал, а не привычка",
    "ты покупаешь скидочные товары и радуешься, хотя они тебе не нужны",
    "ты считаешь, что если не ответить на сообщение, то оно исчезнет само",
    "ты однажды разговаривал с растением и был уверен, что оно понимает",
    "ты считаешь, что борщ — это не еда, а культура",
    "ты включаешь музыку, но переключаешь трек, так и не дослушав ни один",
    "ты считаешь, что в каждом чате есть главный мемологист, и это ты",
    "ты ищешь вдохновение в ночи, а находишь только пустой холодильник",
    "ты считаешь, что понедельник — это не день, а проверка на прочность",
    "ты перечитываешь свои сообщения и удивляешься, зачем ты это написал",
    "ты считаешь, что зима существует только для того, чтобы укрываться пледом",
    "ты покупаешь технику и читаешь инструкцию, только если она на русском",
    "ты считаешь, что смех — это лучшее лекарство, а мемы — его рецепт",
    "ты однажды приготовил ужин, но забыл его съесть",
    "ты считаешь, что у каждого есть суперспособность — находить странные видео в 3 ночи",
    "ты включаешь новогодние фильмы летом, потому что настроение",
    "ты считаешь, что петрушка — это не трава, а украшение",
    "ты один раз попытался петь в караоке и с тех пор только слушаешь",
    "ты считаешь, что носить пижаму целый день — это не лень, а стиль жизни",
    "ты покупаешь продукты впрок, но они портятся, потому что ты ешь только доширак",
    "ты считаешь, что дождь — это хороший повод не выходить из дома",
    "ты собираешь плейлисты, но слушаешь только одно и то же",
    "ты считаешь, что важные дела можно отложить на понедельник, даже если сегодня вторник",
    "ты однажды сказал, что будешь писать книгу, и это было 5 лет назад",
    "ты считаешь, что у твоего кота есть свои планы, в которые ты не посвящён",
    "ты откладываешь просмотр сериала, чтобы посмотреть его залпом, и так и не начинаешь",
    "ты считаешь, что чеснок — это защита не только от вампиров, но и от людей",
    "ты однажды попытался учить программирование, но остановился на 'Hello, World!'",
    "ты считаешь, что мемы — это единственное, что объединяет поколения",
    "ты включаешь анимацию и думаешь, что это слишком круто для твоего возраста",
    "ты считаешь, что магия существует, просто она в мемах",
    "ты заказываешь еду на дом, потому что лень мыть посуду",
    "ты считаешь, что ночь — это время для мемов и осознания жизни",
    "ты покупаешь красивый блокнот, но пишешь там только списки покупок",
    "ты считаешь, что если песня играет, значит, настроение улучшится",
    "ты однажды попытался не использовать телефон целый день и сошёл с ума через час",
    "ты считаешь, что самая сложная задача дня — выбрать, что посмотреть",
    "ты покупаешь вещь, потому что она на скидке, и никогда её не носишь",
    "ты считаешь, что есть 2 типа людей: те, кто любит мемы, и те, кто врёт",
    "ты однажды хотел стать популярным, но понял, что популярность — это слишком сложно",
    "ты считаешь, что лучший способ решить проблему — это съесть что-то вкусное",
    "ты пытаешься просыпаться рано уже 3 года — и до сих пор не получается",
    "ты считаешь, что чипсы — это не просто еда, а состояние души",
    "ты один раз пытался приготовить торт, и он получился, но есть его было страшно",
    "ты считаешь, что мемы — это лекарство от скуки",
    "ты покупаешь абонемент, потому что он выгодный, и ходишь один раз",
    "ты включаешь прямые эфиры, чтобы чувствовать себя частью чего-то важного",
    "ты считаешь, что инопланетяне уже смотрят твои мемы и не понимают их",
    "ты сохраняешь рецепты и забываешь, что они вообще есть",
    "ты считаешь, что улыбка — это лучший аксессуар",
    "ты однажды попытался не есть сладкое, и это длилось ровно день",
    "ты считаешь, что мемы — это универсальный язык, понятный всем",
    "ты хотел изменить жизнь, но залип в мемах",
    "ты считаешь, что газировка — это ложь, но всё равно её пьёшь",
    "ты однажды сказал 'я не буду смеяться', а потом сломался через 2 секунды",
    "ты считаешь, что у котиков есть свой план по захвату мира",
    "ты покупаешь одежду, потому что она крутая, и носишь её только дома",
    "ты считаешь, что на 1 января надо загадывать желания, но всегда забываешь",
    "ты однажды пытался не скроллить 5 минут и понял, что это невозможно",
    "ты считаешь, что магия — это когда доширак готовится 3 минуты",
    "ты покупаешь подписку и забываешь её отменить",
    "ты считаешь, что мемы — это способ сказать то, что ты не можешь сказать словами",
    "ты смотришь старые фото и думаешь: 'зачем я это делал?'",
    "ты считаешь, что человек, который придумал смайлы, должен получить Нобелевскую премию",
    "ты однажды сказал 'я всё контролирую', а потом уронил телефон",
    "ты считаешь, что смешные видео лечат лучше любого врача",
    "ты покупаешь вещи, потому что они красивые, и не знаешь, куда их деть",
    "ты считаешь, что мемы — это искусство, и ты его ценитель",
    "ты однажды не выходил из дома целый день и назвал это 'выходным'",
    "ты считаешь, что ночь — лучшее время для продуктивности, но просто лежишь",
    "ты думаешь, что стал взрослым, когда начал радоваться новой губке для посуды",
    "ты считаешь, что если оставишь чат на 5 минут — пропустишь 100 мемов",
    "ты уже не помнишь, зачем открыл телефон, но мемы листаешь с удовольствием",
    "ты считаешь, что твой юмор понимают только избранные",
    "ты говоришь 'я перестану есть по ночам', но заказываешь доставку в 2 часа",
    "ты считаешь, что сосиска в тесте — это еда для души",
    "ты переписываешься в чате и смеёшься над собственными мемами",
    "ты считаешь, что у тебя есть талант — находить странные факты в интернете",
    "ты однажды попытался сделать утреннюю зарядку и не повторил",
    "ты считаешь, что если ты смеёшься — значит, всё хорошо",
]

# ==================== ЖИВОТНЫЕ ====================
ANIMALS = [
    {"name": "Ленивец", "emoji": "🦥", "description": "Ты — ленивец! Твой девиз: «Зачем спешить, если можно не спешить?» Ты мастер ничегонеделания и любишь долго обдумывать даже самые простые решения."},
    {"name": "Кот", "emoji": "🐱", "description": "Ты — кот! Ты обожаешь внимание, но только когда тебе это нужно. В остальное время ты просто наблюдаешь за миром и иногда позволяешь себя гладить."},
    {"name": "Собака", "emoji": "🐶", "description": "Ты — собака! Ты преданный друг, который всегда рад видеть всех. Ты любишь гулять, играть и иногда грызть тапки."},
    {"name": "Пингвин", "emoji": "🐧", "description": "Ты — пингвин! Ты всегда хорошо выглядишь в костюме, идёшь по жизни по-деловому, но внутри ты просто хочешь скользить по льду."},
    {"name": "Лиса", "emoji": "🦊", "description": "Ты — лиса! Ты умный и хитрый, всегда найдёшь выход из сложной ситуации. Главное — не попасться в капкан."},
    {"name": "Панда", "emoji": "🐼", "description": "Ты — панда! Ты милый и неуклюжий. Любишь бамбук (и всё остальное) и считаешь, что объедаться — это нормально."},
    {"name": "Совушка", "emoji": "🦉", "description": "Ты — сова! Ты мудрый и немного загадочный. Любишь ночные посиделки и считаешь себя главным экспертом во всём."},
    {"name": "Дельфин", "emoji": "🐬", "description": "Ты — дельфин! Весёлый и дружелюбный, ты всегда находишь способ развеселить других. Любишь воду и свободу!"},
    {"name": "Волк", "emoji": "🐺", "description": "Ты — волк! Ты сильный, независимый и немного загадочный. Ходишь своей тропой и никому не позволяешь вести тебя."},
    {"name": "Заяц", "emoji": "🐇", "description": "Ты — заяц! Быстрый, пугливый, но очень обаятельный. Ты всегда в движении и часто оказываешься в центре событий."},
    {"name": "Медведь", "emoji": "🐻", "description": "Ты — медведь! Ты выглядишь грозно, но внутри ты мягкий и добрый. Любишь мёд и долгий зимний сон."},
    {"name": "Кролик", "emoji": "🐰", "description": "Ты — кролик! Милый, пушистый и обожаешь быть в центре внимания. Твоя самая сильная сторона — очарование."},
    {"name": "Капибара", "emoji": "🦫", "description": "Ты — капибара! Ты дружишь со всеми, спокоен как удав и всегда готов прийти на помощь. Ты — король чата!"},
    {"name": "Енот", "emoji": "🦝", "description": "Ты — енот! Ты обожаешь всё блестящее, любишь копаться в мусорках и часто оказываешься в центре хаоса."},
    {"name": "Жираф", "emoji": "🦒", "description": "Ты — жираф! Ты всегда видишь ситуацию с высоты. Любишь быть в центре внимания и иметь широкий кругозор."},
    {"name": "Хомяк", "emoji": "🐹", "description": "Ты — хомяк! Ты любишь запасать еду на зиму, а потом забываешь о ней. Милый, пухлый и всегда с щеками!"},
    {"name": "Тигр", "emoji": "🐅", "description": "Ты — тигр! Ты сильный, грациозный и никого не боишься. Ты идёшь к цели, даже если она на другой стороне джунглей."},
    {"name": "Обезьяна", "emoji": "🐒", "description": "Ты — обезьяна! Весёлый, энергичный и любишь быть в центре внимания. Ты умеешь поднимать настроение другим."},
    {"name": "Ёжик", "emoji": "🦔", "description": "Ты — ёжик! Колючий снаружи, но мягкий внутри. Ты заботишься о себе и редко открываешься людям."},
    {"name": "Корова", "emoji": "🐄", "description": "Ты — корова! Ты добрая, спокойная и всегда готова поделиться теплом. Любишь природу и свежий воздух."},
    {"name": "Свинья", "emoji": "🐷", "description": "Ты — свинья! Ты ценишь уют, еду и простые радости. Ты всегда знаешь, где найти что-то вкусное."},
    {"name": "Лягушка", "emoji": "🐸", "description": "Ты — лягушка! Ты прыгаешь от одной идеи к другой, и всегда находишь способ удивить собеседника."},
    {"name": "Слон", "emoji": "🐘", "description": "Ты — слон! Ты — самый большой и добрый человек в чате. Ты никогда не забываешь обид (и хороших шуток тоже)"},
    {"name": "Фламинго", "emoji": "🦩", "description": "Ты — фламинго! Ты яркий, стильный и любишь розовые оттенки. Ты всегда в тренде, даже если это просто стояние на одной ноге."},
    {"name": "Крокодил", "emoji": "🐊", "description": "Ты — крокодил! Ты скрываешь свои эмоции, но внутри ты эмоциональный и иногда пускаешь слезу."},
]

# ==================== СТИКЕРЫ ====================
ALL_STICKERS = [
    "CAACAgIAAxUAAWokXU38_MuMDT7hhvRuZctYuCKJAALIoAACX-ToSLg5DDhF1X44OwQ",
    "CAACAgIAAxUAAWokXU3n6LDpd626aZfX7VT1CippAAKapAAC1p_wSAAByejMhUYpHjsE",
    "CAACAgIAAxUAAWokXU2g9ZIu2x-b64HWhbTOHOSyAAIcnQAC3VDoSOuIDUYFAz2BOwQ",
    "CAACAgIAAxUAAWokXU3kY6BWLWQmeQ1PT3CuNvckAALwmwACnprwSGUZCsPk22EiOwQ",
    "CAACAgIAAxUAAWokXU1P5osRo_HB15PVBBuAnmWYAAItnwACnFTpSB_8LsN-xOJNOwQ",
    "CAACAgIAAxUAAWokXU145P7V1DEkjhTLlaXXX59PAALyowACrybxSGptuXllGPv-OwQ",
    "CAACAgIAAxUAAWokXU2nC51Pa2TgnjArRylBRh6dAAKIlAACpXXxSAKVXz87axSvOwQ",
    "CAACAgIAAxUAAWokXU3yvOnmWqjerRPfLpFlUmlQAAKPlgACEs7xSJ3qpb9R_ic9OwQ",
    "CAACAgIAAxUAAWokXU1Tx63zAYHN1CYC-KLgxNp3AALjkgACkRfpSIIvRDiWnY-cOwQ",
    "CAACAgIAAxUAAWokXU2PFjUgEX5hbqY2TGVcOfRKAAL_ogACKlzpSNLm2zRZiSkLOwQ",
    "CAACAgIAAxUAAWokXU11faTEjbsjSMbpdSTX_syYAAKBpAACk1TwSJvEuKFpOpQkOwQ",
    "CAACAgIAAxUAAWokXU054Wc3FW_Q65FfJRkSiRyGAALRkQACY1voSCA9QH6QwSK0OwQ",
    "CAACAgIAAxUAAWokXU0xK40IFwFOpALJGJCawG3JAAJsogAC8PLpSI4JLVCVuf3DOwQ",
    "CAACAgIAAxUAAWokXU3F4V-pld62BG0lhelfM3EYAAK8lQACxh7pSIQrDNt_r-ewOwQ",
    "CAACAgIAAxUAAWokXU2FvJ8W422Xk8-scBiNe2DJAALMlwACtEXpSE2VkrI2O1NPOwQ",
    "CAACAgIAAxUAAWokXU2AJk5Zoxg5JGFSKpEBGCztAAJqkQACvhXpSIbM9Bs6Yiq3OwQ",
    "CAACAgIAAxUAAWokXU2Ke64cafmdIygw8DJoIa2FAAKdlAACqSvpSAsCfDWpfan3OwQ",
    "CAACAgIAAxUAAWokXU3_vpExN7T73faHRspM89StAALwkwACG47pSKQmC5SvHXY2OwQ",
    "CAACAgIAAxUAAWokXU1FYgmIQOkwZwni7kBL6q4aAALVkgACCLPoSBBAczlFMpckOwQ",
    "CAACAgIAAxUAAWokXU1Bcjzngw-9VgNv11VbK5kZAAL3mgACR6_pSAPVJLLjrWzCOwQ",
    "CAACAgIAAxUAAWokXU0koChsyWXcz8b4bp_7YVoVAAI1pwACXcXxSIoTuEZ1bSkXOwQ",
    "CAACAgIAAxUAAWokXU06R9Oi46TtOoeq4QiZjANEAALmnQACs9fpSFScirWoMo1EOwQ",
    "CAACAgIAAxUAAWokXU2g331GAnLH0xBLFw-jiPCzAAITlwACIYHoSLqoE7BW4MtMOwQ",
    "CAACAgIAAxUAAWokXU0SOvpJYjHjt__9n8fDF8hyAAJLogACDxjoSCyyEYrlpPQFOwQ",
    "CAACAgIAAxUAAWokXU1RCz4BVL_bQe67sSOZpDUUAAIxnwACA0zxSLETELVACMCEOwQ",
    "CAACAgIAAxUAAWokXU1HP5Z1sBsn5v-_kclbr5FcAALupgAC2IPpSBVYbcjvEJ0YOwQ",
    "CAACAgIAAxUAAWokXU3jhdL8f6mf9p9o6qftwLkDAAJznAACctfpSL1T9GnpVCBVOwQ",
    "CAACAgIAAxUAAWokXU3N7gR9Bm1oLYvYcVH2F2FiAAKsmgAC3N3pSOaBEBGDCR5mOwQ",
    "CAACAgIAAxUAAWokXU1f0pEwqzFe4uoJtQlE4EemAAIFnwAChojoSObP2PZ914nlOwQ",
    "CAACAgIAAxUAAWokXU3XO193i3yIAjXnG7hF7R8sAALDmAACC9XpSFJUb0ShZP7xOwQ",
    "CAACAgIAAxUAAWokXU2-RzYebZlF_qRE-FIP_IFRAAJRmgACNCLpSBtLnVJCXaN-OwQ",
    "CAACAgIAAxUAAWokXU2aflNlvwyWsjNEldfQgsOFAALZoQACiJHpSGbjHTrA40tiOwQ",
    "CAACAgIAAxUAAWokXU3aIsoRtEkQEVHq239nssTRAAJ_lgAC_TzwSCLA8vZAh057OwQ",
    "CAACAgIAAxUAAWokXU12xlepwifRhj5DDP2KRVWIAAKJmwACWHToSGCuMRMW6er0OwQ",
    "CAACAgIAAxUAAWokXU0DmQJX3Gq_Y43rIsGffAusAALcnAACzY7pSJw-DlEmlOYNOwQ",
    "CAACAgIAAxUAAWokXU0JQKo0EOuYfHgai5zmxGxrAAJFmgACHUfpSCgMy0tj7U36OwQ",
    "CAACAgIAAxUAAWokXU3nQztqXppXKc7l-IYRj96oAALLogAChJDoSMy3tBbywS0bOwQ",
    "CAACAgIAAxUAAWokXU3mw2MEemdJixNQK09fn5jOAAKzmQACeM7xSASa7gtGWh2UOwQ",
    "CAACAgIAAxUAAWokXU1eoo-9uxxWPNRnIfHzfKHTAAKPqQAC6pXxSCM573gtTxL2OwQ",
    "CAACAgIAAxUAAWokXU2aU_YVvdB2RVazkB4FHIP6AAKnmwACR07oSP6jbuaVlSgeOwQ",
    "CAACAgIAAxUAAWokXU1BcNUiplZFmjpKErjpQIg7AAIbowACrvPwSPU98nWhUfwpOwQ",
    "CAACAgIAAxUAAWokXU3OOev59WsUmiodW3X8-plnAAImmgAC2LHpSG9vFJI2cNXJOwQ",
    "CAACAgIAAxUAAWokXU1ls-VjEDmP5T2y_DNT_phsAAKJmgACKlHoSI2cdA9ZCp_GOwQ",
    "CAACAgIAAxUAAWokXU26OFyUmKrZoMZw2FIFewT1AAJZogACCCfxSIKUwIEuydI6OwQ",
    "CAACAgIAAxUAAWokXU1j56UDAAGQLcchl4AuQ56xPwACxpAAAlNX6UhbfJefFZD3DTsE",
    "CAACAgIAAxUAAWokXU0Rt_vgMt-4ckAZbShunuT5AAKXmQACl6joSMGUYHCrd9IPOwQ",
    "CAACAgIAAxUAAWokXU0iyVVJ4wMv4KfGiseHP-pbAAI7kgACRnPoSBdEcPembb1jOwQ",
    "CAACAgIAAxUAAWokXU0QQP6JSMlyzwyeAAHZRGE1VQACmZcAAlZk8UjjaDtj7bLOuzsE",
    "CAACAgIAAxUAAWokXU1sE5jdwqgEXodlglf050hZAAI2pQACPlXwSB3A4o8O3ieKOwQ",
    "CAACAgIAAxUAAWokXU1CCx3bmxPah8WQS0SMlQykAAKcowACKYjpSFYwt9h2fUyDOwQ",
    "CAACAgIAAxUAAWokXU1Lhze1gqwuQW4PzeQEk7BcAALClAACgcLoSFkkmomd88UeOwQ",
    "CAACAgIAAxUAAWokXU0w2nyPMEh0LLj8G51vVcQ3AAJ8mQACmDrpSFXnjmQgnnrnOwQ",
    "CAACAgIAAxUAAWokXU1Q40DEOwoCfmUQXLFIkyLKAAKljQACNvHoSOVpq3NXMv1IOwQ",
    "CAACAgIAAxUAAWokXU3-suc0276lX4Jgd9AeZ66PAAKxnQACkhbwSEP_P9wol8YUOwQ",
    "CAACAgIAAxUAAWokXU2d0kjGcwJY6RO1p4aInlMeAALqnQACInnpSOv8_4I2N89jOwQ",
    "CAACAgIAAxUAAWokXU1GaGoXVxu4xhdDibp-1-7WAALZmwACeAboSOZwgjSK7iOGOwQ",
    "CAACAgIAAxUAAWokXU00p-pk9uR_cWFYL6nhZVIKAAIylAACJBPoSJWbNuGzJxGrOwQ",
    "CAACAgIAAxUAAWokXU3-OVrW-BSSQkTXYzPBUG1NAAIJogACx27pSH0fM34bkvVgOwQ",
    "CAACAgIAAxUAAWokXU2C9et-3PMYVMKamIcopRw3AAL1kQACSQLoSNZm6t3tQwpmOwQ",
    "CAACAgIAAxUAAWokXU200CqT6dl28y1PiCHhhrZUAAKmmAACDLzpSJhChea7kJrFOwQ",
    "CAACAgIAAxUAAWokXU03q9BSjtZ9AwqRolDhUsEBAAKinQACkDDwSPPokQMTbZP3OwQ",
    "CAACAgIAAxUAAWokXU0-188FPP824k_yN-G9O198AAKmogACjIvoSNm7s1WSUII1OwQ",
    "CAACAgIAAxUAAWokXU0yO-usbG7NnIocUMLucsMGAALEnQACOBbwSOlWGpdk7w8UOwQ",
    "CAACAgIAAxUAAWokXU2tNjBL4V5ey2yJWMOid3uGAAKFqAAC4kPpSMcMgQ-faAonOwQ",
    "CAACAgIAAxUAAWokXU2lOPF-rp0HR2SMXb7LOSW_AAJupgAChgPoSNjnmp9rNsGgOwQ",
    "CAACAgIAAxUAAWokXU1ooY1vjMJrjnp043BEXWrgAAJQoAAC_mXwSNw2vQomGUbLOwQ",
    "CAACAgIAAxUAAWokXU2cFJQhXAwV_d0zKFIEPeZHAAJ8lwACv9vwSM8Ly_LNOjXAOwQ",
    "CAACAgIAAxUAAWokXU0Ery983i0HZnXRZZUAAZHrTAACYZYAAkBU6UifV21q0JPMszsE",
    "CAACAgIAAxUAAWokXU0U_bU8qtgQhCHFNDYTpzFcAAKrvQACs4ToSIWTSsOf0kbhOwQ",
    "CAACAgIAAxUAAWokXU3w2opDxm0wfmDc3uO2TthcAAK6mwACH3vxSIvV_JZVbdYaOwQ",
    "CAACAgIAAxUAAWokXU0VyUh3CtarsPGBsOMm1KaRAAIplgACjMbxSLoUZxhNtl-rOwQ",
    "CAACAgIAAxUAAWokXU1vd2hlsDYH5bi1jIk9uCpRAAKRlwACj_LoSBo-E5fBcVqIOwQ",
    "CAACAgIAAxUAAWokXU0OL4q4FyeSiutzawkq58ZTAAKLlQACaLToSPFC7k8BbUcCOwQ",
    "CAACAgIAAxUAAWokXU0ZLGPTC2HJU3GqYF4Gj33fAAKUpAACdO7pSLewaO4hgULLOwQ",
    "CAACAgIAAxUAAWokXU2kVOIWDgABupWnSZqWK7yyVAAC5Z8AAon78UjVSzqMyF65VzsE",
    "CAACAgIAAxUAAWokXU197MtGAt_YBRhYcblckVvHAALkoQACVszxSJ9t7rB-f0BcOwQ",
    "CAACAgIAAxUAAWokXU3xXHpajnRH3OhuuMwGHlUIAALbnAACwIDpSEVbM4mDlBInOwQ",
    "CAACAgIAAxUAAWokXU3HvrULMhw4uM6ojaP2P-gaAALEnQACMzPwSAMP16RwRbasOwQ",
    "CAACAgIAAxUAAWokXU151IxDHxC9WSvfjM_m_o6-AAJHmQACeCHxSHvFPOGATAHhOwQ",
    "CAACAgIAAxUAAWokXU3_OBYAASU7to_WVoU6KCs_fgACLKEAA8voSPVkfVCBbtwCOwQ",
    "CAACAgIAAxUAAWokXU0fzySsWYNVVKCOLVuSxdbzAAIMmwACp4PxSJoestOQcJFuOwQ",
    "CAACAgIAAxUAAWokXU2y6n3_wkA6pqm9EKBML1W7AAIimgACG87oSKGUNkxeyvgIOwQ",
    "CAACAgIAAxUAAWokXU0lxRRHr4JXzNNlrifDfEy3AAJVngACcynxSAUduowqmi3IOwQ",
    "CAACAgIAAxUAAWokXU20LaWcveD0Qm974tbPzXm4AAOjAAIb3vFIW5kxrM6IL3s7BA",
    "CAACAgIAAxUAAWokXU3PWloxcXR_vlTL78trzZroAAKeoQACMIboSNlUcWLgiST9OwQ",
    "CAACAgIAAxUAAWokXU14m02rHakZYGS4dk71P51xAALtkAAC5bnpSDr0rFkvUvt3OwQ",
    "CAACAgIAAxUAAWokXU0CMv4wpj3xgMDJLc9_acRcAAKslQACkX7oSKyvzuBMnqo_OwQ",
    "CAACAgIAAxUAAWokXU2g-Mjrtkevpo7sCG9oLH9PAAJMlwACVmDoSJ2fvmxmYuAlOwQ",
    "CAACAgIAAxUAAWokXU2ysZ6rWAxQRLGLvbginBJXAAKVoQACPQPoSEn21EUKiBmFOwQ",
    "CAACAgIAAxUAAWokXU2cSDl_AUdFqHvA__WtaDLkAAK4mAACFkTpSNYODlwd_V7-OwQ",
    "CAACAgIAAxUAAWokXU2Lar5jpz5xs-Z0aUpS0xiRAALRmAAC1z_oSAvF-3BwWSdLOwQ",
    "CAACAgIAAxUAAWokXU2xa3KK_ulMpHJKaw0NDS07AALTlQAC_UzxSFy_pnoX8VRHOwQ",
    "CAACAgIAAxUAAWokXU3faKa05PsyZhCbJUtWplztAAJimgACdfjoSN0-4iMiLp1dOwQ",
    "CAACAgIAAxUAAWokXU30BI0cZ2WYYO0j3z5FaUiKAAIgmQACr3DpSP5_nKzrur-EOwQ",
    "CAACAgIAAxUAAWokXU0NPhPU5iZt-DmDGL8q9SK2AALelQACNFPoSCxvrR8fOJU8OwQ",
    "CAACAgIAAxUAAWokXU0O4gABq_jYWGCnbv63SGO6zgACY5MAAr5K6EgJsYCRyQEfCzsE",
    "CAACAgIAAxUAAWokXU0l3XA0k3dCKdj1fD9KcOKaAAJVlQACVdDpSManYlkq4Ws8OwQ",
    "CAACAgIAAxUAAWokXU1mwBSBEigeFrUHMWjSU2VcAAJTkgACnyroSAanrZU3sUEQOwQ",
    "CAACAgIAAxUAAWokXU2RKoo0nQShDuOyk2ipqnL7AAJ9lQACPPPwSL1dEu7oFkacOwQ",
    "CAACAgIAAxUAAWokXU1dBhcpe_oYsw2mB1QhcljxAALJlAACvivoSAABcLJ9o4nplDsE",
    "CAACAgIAAxUAAWokXU2vp3dtAAHIRuRVgOZw6TlOYQACyZAAAhoh6EiP1AXNb4OMqjsE",
    "CAACAgIAAxUAAWokXU3LcDMs1AABjuRuDL_5X-p1PwACDJoAAsBH6EjcG4Veo7zuVTsE",
    "CAACAgIAAxUAAWokXU2UkENzvdNX4w2z078NmzhYAAKwpwACEwTpSNO3vrsKav5POwQ",
    "CAACAgIAAxUAAWokXU02M6LnSGaNt5lbknmpLM1ZAAL-ngACfO7wSOvZnliOfdL2OwQ",
    "CAACAgIAAxUAAWokXU32IztmaQ_IxpvoW_66spbOAAJxmQAC4XzwSAABe1HIP4bqIzsE",
    "CAACAgIAAxUAAWokXU2ghwos7UJCzZfyFEszqvdcAAJ6mwACsJvwSJLY1lTRvh8BOwQ",
    "CAACAgIAAxUAAWokXU189dXETCJ4VLzh4gZCXZRLAAJikgAC7vzoSLenLXCIn-8kOwQ",
    "CAACAgIAAxUAAWokXU1sxWcogLbdEdRd1Zslgn28AAL_mwACWzToSMf3uNaMA23YOwQ",
    "CAACAgIAAxUAAWokXU3aTGDlWnqduVr9HRaKZ8D8AAIunwACd4rxSK8HMRUhuxPROwQ",
    "CAACAgIAAxUAAWokXU2941EY1qcPK-NRcT1Huu_mAALlnwACHgLpSJGGxEZ-ASFjOwQ",
    "CAACAgIAAxUAAWokXU1whdhsVot_dMpG46vqWtxSAAJamAAC_E7oSCmaNtrOnL-DOwQ",
    "CAACAgIAAxUAAWokXU2yCc6uzDAMU_tKSwoPfS2lAAIolgACRU7pSO8tHCdkoaaWOwQ",
    "CAACAgIAAxUAAWokXU2oEl-VrIa5Ix4vzQPiAmS-AALClgAChJ7xSOnwdPw-PzguOwQ",
    "CAACAgIAAxUAAWokXU2wM8mc2fyoCcV6vJS1_Vx6AALymQACImvoSIZ5f9yyKPkgOwQ",
    "CAACAgIAAxUAAWokXU2iaYcRVBaN8k5PesCR7_6IAALnowACSw_oSO0TpuIWsJSmOwQ",
    "CAACAgIAAxUAAWokXU2MpYfyG-n1-qEnML6N_0FzAAKFmwADpfFI0vQKiVKGAp47BA",
    "CAACAgIAAxUAAWokXU2gg1EIplsThbm0SI-5LferAAKTmAACBXDpSEteaRM2rX0uOwQ",
    "CAACAgIAAxUAAWokXU2zVOK7cekWAy_WZ9RqtdT8AALKlAACo-DpSH0qUHTjBZPyOwQ",
    "CAACAgIAAxUAAWokXU0qoYt9JBcTNQlUNbgcwlZfAAKvnAACdgrxSLLlcK__QZsFOwQ",
    "CAACAgIAAxUAAWokXU1tCYayC_vALXj9kpE3li4cAAK3mAACCEDoSMEAAWz7N8YnTjsE",
    "CAACAgIAAxUAAWokXXtuMaakA017HVbN2gbHJmb6AAKrogACCQW5SJb-BSId1GdVOwQ",
    "CAACAgIAAxUAAWokXXsCfaMplAmcfnOmkHunrmtmAALKnQACVlq4SINnIZh5VUN7OwQ",
    "CAACAgIAAxUAAWokXXvDbHH5XvqmlehN9ksy4PZGAAJxowAC2mWZSAHFSsu-KrK1OwQ",
    "CAACAgIAAxUAAWokXXspO7Vx5Y_Vsn78oUDWBM2PAAKhngACNTCZSItYVl8Qyjn4OwQ",
    "CAACAgIAAxUAAWokXXsKmx5ZamdbsucKWbOZMgV5AALPmQAC-L-ZSM6uTxShEdElOwQ",
    "CAACAgIAAxUAAWokXXv_QUEo4mS3jHJug7NimHnUAAJJmQACvpqgSB0j7pqK3oFFOwQ",
    "CAACAgIAAxUAAWokXXvCQ9Y9lt3FfjML_GAzrPGoAAIUmQACiYeYSBDq029KggqPOwQ",
    "CAACAgIAAxUAAWokXXuzQ_QbgIIaOjU7v3-KGd2KAAJGpQAC9CuZSPra3CV_Kt_pOwQ",
    "CAACAgIAAxUAAWokXXsBevataZ7Iu9CoL5GhVqVNAAKCnAAClduZSMtCQjVW1jB-OwQ",
    "CAACAgIAAxUAAWokXXu77ihFncTCzk5qlxCvRJfXAAJamwACYMJugSLNszm8sIAlyOwQ",
    "CAACAgIAAxUAAWokXXvEPe0PC5paq9GxtKta86ThAAIGngACvt-ZSCUh-hVPfumAOwQ",
    "CAACAgIAAxUAAWokXXsbBnomGgZU89vWn1Y7-WFaAAIvmAACgaSYSLT9UDj3WyvXOwQ",
    "CAACAgIAAxUAAWokXXuezDPeAnlprcfj4xTQ2hQVAAKVmAAC8XqYSDvb5g0ayWX8OwQ",
    "CAACAgIAAxUAAWokXXuPqmyhHMqzzK4aNGGmkYLHAAI_mwACUOWhSAPvHhqpKQJgOwQ",
    "CAACAgIAAxUAAWokXXsK3HNaRRRptRsOsDGBmpUGAAK4nAACU36ZSO32KHyuPr3zOwQ",
    "CAACAgIAAxUAAWokXXsv208KuGrNkHYIfgH294l-AAJqlwACKz2gSJjpJi7bpQ3FOwQ",
    "CAACAgIAAxUAAWokXXscgM6FH5DdaV8Ce_PTYFrYAALrxAACeSWYSMkJewONTJ9NOwQ",
    "CAACAgIAAxUAAWokXXv912mUVA5GGVGOVmOx9cC3AAIvkQACwFahSBxJ6TgCdRJGOwQ",
    "CAACAgIAAxUAAWokXXtCIYxhT9ryzJcek_7rDR7FAAICoAACVcShSAJruw6Pj0wWOwQ",
    "CAACAgIAAxUAAWokXXtCNXDxmBbrxDCzSSfCbQABZQACp6EAAsV1mEg6XNcTGrpyvTsE",
    "CAACAgIAAxUAAWokXXudOi06Ick77gg2uXoMfdmoAAIZmwACYbCYSGuFCcNlMoLdOwQ",
    "CAACAgIAAxUAAWokXXvtAxDFMyexm2pIkUPyKV__AAKnmgACrUqhSAAB_Do6yyUAASY7BA",
    "CAACAgIAAxUAAWokXXuOBumtj3kJW-L0BfXaTfCUAAL_mwACfH6YSMrvNQloQ8wTOwQ",
    "CAACAgIAAxUAAWokXXv6XYHezWurAY1fYFvR4LXkAAJXnwACeAqYSKLqnyPWud2oOwQ",
    "CAACAgIAAxUAAWokXXte9xwbxlq4cvUcHBbXA-dHAAKhlgACXviYSLtH0JZuEEpgOwQ",
    "CAACAgIAAxUAAWokXXsHy3ZjQ_vq0XVC3g0MbR7lAAJ0kQACVuWhSC_DK_aUFzlzOwQ",
    "CAACAgIAAxUAAWokXXslEklBS9Ky8ZWuTlMNZroLAAJ2nQACQSSZSP07rmj9HJ86OwQ",
    "CAACAgIAAxUAAWokXXswH570HoKBdokt48eu0ovPAAKurAAC7a6ZSG3gmlqFHzC5OwQ",
    "CAACAgIAAxUAAWokXXte1ZcOlcNzru3Bk5DVsrMbAALApAAC8xqYSKI-HUwl521DOwQ",
    "CAACAgIAAxUAAWokXXtwBPK-CwwMRiDpTw4CHcz9AAI4ngACKi2ZSCoEhqPUHysNOwQ",
    "CAACAgIAAxUAAWokXXuurPDp_UFZM8d0b9r2A52nAAOgAALxDJhI3emEKD8DTK87BA",
    "CAACAgIAAxUAAWokXXvZnqH91VdZayiI_GPkKOHfAAKQpgACjOuYSMeOeUfOBOkOOwQ",
    "CAACAgIAAxUAAWokXXtoGyskRROoV3zghmTH1j7cAAKjnwACBZKgSMPDCyIOUc0dOwQ",
    "CAACAgIAAxUAAWokXXuzwFvsByiLKcnG6cgd69n7AAJ-qQACO42YSGnw5cjOmLvWOwQ",
    "CAACAgIAAxUAAWokXXssyRPrrTfe1QMCOzOU1rWWAAJPmAACPDCgSMHheXvDi1s6OwQ",
    "CAACAgIAAxUAAWokXXvS7-O05emVfGcCXvQOsqO_AAJpmQACmY-ZSFYu2QOf--EuOwQ",
    "CAACAgIAAxUAAWokXXsmlEDnaPvjbi8Ye30Nmr0QAAIunQACuzGZSHSCQmZtSwFpOwQ",
    "CAACAgIAAxUAAWokXXucUNzS6JA2DIO5qFpHoYCxAALPlAACneqZSByNsuetbZNNOwQ",
    "CAACAgIAAxUAAWokXXumT3MUgGbif65sBj4EUvK1AAJaoAAC3sWhSBAO00VfY4GOOwQ",
    "CAACAgIAAxUAAWokXXuR1U74J2oIsQGgLATadqraAALanQACZUiZSIHS367c8OrBOwQ",
    "CAACAgIAAxUAAWokXXtJeQ1_RsLKdzRYZJaUFM3tAAJWoAACTnegSKadU_aZ0gumOwQ",
    "CAACAgIAAxUAAWokXXt-kNUtGTz9C7oAAeiy6iR0QgAC2J0AAmnXmEjItkddm00qOzsE",
    "CAACAgIAAxUAAWokXXtYg4yt-vzTw-SL3OimFpyhAAIkoAACbxaZSFqLdNrVBQ-zOwQ",
    "CAACAgIAAxUAAWokXXtCHuuY2iMmsvgYTeR4ctaYAAKZmQACODWYSOA6STiyhF1tOwQ",
    "CAACAgIAAxUAAWokXXuSmF9_kzgJhts73zNfk6DRAALqnQACYf6hSOl2M7YhukkAATsE",
    "CAACAgIAAxUAAWokXXtfOIUXbcrpl4m2UAV1u0WoAALonAACOcWZSAXPx7nvdlW_OwQ",
    "CAACAgIAAxUAAWokXXttXcw1IRQMZY16OMI_IgUHAAIsngAC5luYSHv0N45QDXaAOwQ",
    "CAACAgIAAxUAAWokXXuJU1nu0wIBkM_t3nziZdLqAAIqoQACSzuYSLMxmdbe2_hJOwQ",
    "CAACAgIAAxUAAWokXXtojpMKonBl-uJJXaWFPXLEAAJJoQACZAmYSAddsdcK2bu6OwQ",
    "CAACAgIAAxUAAWokXXu3_Lm3KieR2YTIhOqIKfxVAAL3owACtD2YSMK5znFGE5J8OwQ",
    "CAACAgIAAxUAAWokXXv9xYRW7yIyOiNu7QABMJyZcAACK5YAAgzToEi5RY3uH3IDaDsE",
    "CAACAgIAAxUAAWokXXuwpxeaWFjv2yz-Sss0TzdLAAIWowAC5e6ZSJuZ4MLOBrFmOwQ",
    "CAACAgIAAxUAAWokXXu6lnXZLlBdux16BzORvSd-AAKGnAACAvuhSEpZak_aIpKMOwQ",
    "CAACAgIAAxUAAWokXXsy56v1gVjGO-0p28_OLhLgAAJ5mwACTrqZSBDbnmN-e1WOOwQ",
    "CAACAgIAAxUAAWokXXv0JUCTPTGkU8Xxn66ZGmgeAAIUpQACe1-ZSO4VxcVUuUdVOwQ",
    "CAACAgIAAxUAAWokXXswuViRPGrTs3EnTaLoX92QAAJcogACokGZSB4zUcHkr5L5OwQ",
    "CAACAgIAAxUAAWokXXuNu_Nx4abUSxwCJGAa5CxgAAL9nwACyfeZSCFfWCoX6Yg6OwQ",
    "CAACAgIAAxUAAWokXXsp-94n7No4SLYvIOyOx9EfAAJepwACR7yZSEmZbPO39l73OwQ",
    "CAACAgIAAxUAAWokXXtw_nDxc3nDNWtK5Zf9L8QcAALcoQACzCigSHfzh-FyO6iPOwQ",
    "CAACAgIAAxUAAWokXXsTKYgBdB_HqDAn_LKMim_FAAIDmwAC_r-gSAvA5dV0zs10OwQ",
    "CAACAgIAAxUAAWokXXvwEHtlhp2CHh2cUT4-3ONbAALPmgAC11ShSI7LTLnayu4EOwQ",
    "CAACAgIAAxUAAWokXXuOi5NRV_8kb0aAiV2nYjxoAALjjwACPiGpSKX6-t6DFjNDOwQ",
    "CAACAgIAAxUAAWokXXvXtEoWvqNTFabUhz76CFk1AAJpmQACFO6gSEaEHLmw0dMrOwQ",
    "CAACAgIAAxUAAWokXXv1tKOrKQhgGzQhIncShVnVAAIBqgAC7xuoSBYf1XOsy2-8OwQ",
    "CAACAgIAAxUAAWokXXtsBCg6XqJORXYGIC9lRs_MAAIdngACG4ygSNvoloM9wzpVOwQ",
    "CAACAgIAAxUAAWokXXu3WO73nHrgAAEOKv4RcGv9EwACmZsAAuknoEhEhvBRQOaoPDsE",
    "CAACAgIAAxUAAWokXXs7kvzRxA9JBav_Ac4h0p64AAIfswACXjepSEaFDZrjpHY2OwQ",
    "CAACAgIAAxUAAWokXXt9AeBsGlxOODOL0s5Jo0kFAAJOlQACMKWpSBY8PRxb82DVOwQ",
    "CAACAgIAAxUAAWokXXuALvP-e0Ge8zywNMAQoBH7AAKKnQAC9BygSIrxdiHtHyWsOwQ",
    "CAACAgIAAxUAAWokXXtaptFA7SBY_mhJf0IvplhpAAIWlwAChbepSIK-faMlvmR-OwQ",
    "CAACAgIAAxUAAWokXXvthwPbcVmpuzTWmloZ7ZSkAAItnwACpn2hSLsWPWgHV1QYOwQ",
    "CAACAgIAAxUAAWokXXtQ0EPvb1x4D7cSrZwYZyYIAALvogACs3ehSLPMNjHsgIanOwQ",
    "CAACAgIAAxUAAWokXXu_QZV3h0j96_Kv4mAvLZz_AALvnQACvJqoSPqYwW6DBpUPOwQ",
    "CAACAgIAAxUAAWokXXvbEWIg1H15zc3knajPXWCmAAIlpwACfZGhSBIQv5mk2Vc_OwQ",
    "CAACAgIAAxUAAWokXXvNmUm2UM3txbBnIDuhGniJAAILlAAC5v6oSBYgywXR5gTFOwQ",
    "CAACAgIAAxUAAWokXXtnRP_60Ok5w8Q6tdx9dCM_AAK8mwACecKhSNfNUZUnbKckOwQ",
    "CAACAgIAAxUAAWokXXv_ML9n-pjsOEPZjBx_HMpdAAIMmAACb0mpSMKOSpwcGJ_wOwQ",
    "CAACAgIAAxUAAWokXXupKYaD_UUoLEJgWOAUG1d1AAKQowAC6ligSJWvPChtE--LOwQ",
    "CAACAgIAAxUAAWokXXvrYsn9235a5EokEDHoVZObAAIzngAClOCoSEt4gztLG45xOwQ",
    "CAACAgIAAxUAAWokXXvIEj50riAS6xkbWK9oEsI1AAK6kwACOAABqUjx4oBocXzNJjsE",
    "CAACAgIAAxUAAWokXXs-4K6sK-RPIXmosucM_h4VAAIgngAChgSxSGfwa-BlmEdxOwQ",
    "CAACAgIAAxUAAWokXXuu5K7m_A9ONNRqqZed9mV0AALJlwACN8G5SPECO2R93tQSOwQ",
    "CAACAgIAAxUAAWokXXuWiPzeJFjH8rA2mg-ZW5J0AAIEoQAC2DKxSEOTKi9_QAi9OwQ",
    "CAACAgIAAxUAAWokXXtd9X9sZQYgkCLBZMct3XUQAAK2mwAC4OO5SDReC2a8wcMEOwQ",
    "CAACAgIAAxUAAWokXXvLGFeLlZBhBq3Kgmc3BVNZAAJnngACZSXASCwhqZN813RGOwQ",
    "CAACAgIAAxUAAWokXXtJ4a0DblPwMRVpus7BRXUaAAKEpQAC8fu5SMIOQNpKhM7uOwQ",
    "CAACAgIAAxUAAWokXXtAgsKptbd-PBI4Z54RtiptAAKUowACVbm5SKFRfDUx60GWOwQ",
    "CAACAgIAAxUAAWokXXu5DbuutjtHM4ZsCwRmsw4hAALymwACJoG4SFshbcDoFH4YOwQ",
    "CAACAgIAAxUAAWokXXuLXXJGDGp9dAAB1u2C53qebwACcbEAAuuRuUiwa2nqIqllHzsE",
    "CAACAgIAAxUAAWokXXvxn9CmPBgtbaDIQqt2K_o3AAIfsAAC8xa5SICCZFcqu7DHOwQ",
    "CAACAgIAAxUAAWokXXtTlNFlOnlaN5z8IChXR0G7AAJilwACXVC5SIwMx_S6O6rUOwQ",
    "CAACAgIAAxUAAWokXXtsisCb6NcT_EeZNdrNE_jZAAK6uwAC3ny4SEcH_qXnyAABljsE",
    "CAACAgIAAxUAAWokXXuVCtzGfFimiBNNcUiNCWyvAAKkpAACNbq5SJnv4EXK-WRkOwQ",
    "CAACAgIAAxUAAWokXXtW8MUum0dtI57oV5Sn0aHjAALSmQACZr3BSEZqCrJMJOGlOwQ",
    "CAACAgIAAxUAAWokXXubJrzQJMLzoai0NH9aVUdKAAKymgACXpXBSLPrzlz-x4uMOwQ",
    "CAACAgIAAxUAAWokXXvU4rw29GkKDNaTpiL8SbugAAKwpQAClZ7BSCXDJKKjoRGDOwQ",
    "CAACAgIAAxUAAWokXXsdPo3PwX6QJkEN1_pkJZS-AAKMpAACrg25SOc0kx_i-WHsOwQ",
    "CAACAgIAAxUAAWokXXtwDYR5k0d3BQPcOF01lR-zAAL4lQACfgTBSAr1OtZUnQjfOwQ",
    "CAACAgIAAxUAAWokXXtm00fDC-OgLwqAUzHgdI8FAAKKoAACit64SK99d2EZnaxJOwQ",
    "CAACAgIAAxUAAWokXXtCccqN8LnCx0v34ac839Z0AAJ7nwAC4nPASItb5kawnnyIOwQ",
    "CAACAgIAAxUAAWokXXuSRmCLsjOlBIv9v9S_bz3sAALIlAAC38rASBiZ3IbWMouNOwQ",
    "CAACAgIAAxUAAWokXXtnfEnG68RYUVmH3t7WyJ-bAALXnQAC_W64SPRKJ-yIZRBFOwQ",
    "CAACAgIAAxUAAWokXXvhraVXmDJU4T4cmPDBXtZrAAJzqwACP5W5SKWsOU1ZEO1VOwQ",
    "CAACAgIAAxUAAWokXXtq_9mWI5DHMLYKCWrbR2f4AAJgmwACyh3BSDEnnTyhRn52OwQ",
    "CAACAgIAAxUAAWokXXu9n4MzmtS8n04qz209Ltz_AAKqlwACZi3ASJA952SmyVpEOwQ",
    "CAACAgIAAxUAAWokXXt5SIgKdjnv6l7LQ4-EQJOhAALDjQACtLjBSMvCimgpdwx-OwQ",
    "CAACAgIAAxUAAWokXXvi-Qf1i_TOedvqRuic3GeUAAJVlAACAajASBFZVYYYKo95OwQ",
    "CAACAgIAAxUAAWokXXui58J2d4X71sijV0EfH9ZxAAL_mQAC0k_ASJQeC4FQVy38OwQ",
    "CAACAgIAAxUAAWokXXv4kCkKaWsaxCPnMNOHT4jcAALNnAACN7fASD34Y_c87uObOwQ",
    "CAACAgIAAxUAAWokXXvYFt-sMb-UXarwMgu4PNFOAAI0lwACk_rASBjJOTJ1740aOwQ",
    "CAACAgIAAxUAAWokXXsEe8shSu9Oe9Mcap3orTuFAALFmwACK6vASBlSCk8IYWorOwQ",
    "CAACAgIAAxUAAWokXXuwtEFLElZMOS0zN2bB-fftAAJplQAC8Q3ASDLITb-erZLoOwQ",
    "CAACAgIAAxUAAWokXXu1TIcr9gcFr94_UnOziQ2DAALynwACqxTASA4vMoi8-e8BOwQ",
    "CAACAgIAAxUAAWokXXtwvMRqnaR4AcEb5OrbxvIcAAISpgACJ__ASHS_dFPUdybKOwQ",
    "CAACAgIAAxUAAWokXXv64gkZ7BRTeNdFuZQZD_fkAAKjlAACSBXBSA2YLoKimB-KOwQ",
    "CAACAgIAAxUAAWokXXudKC30vNl2Vc_t8a7bwk8SAAJ_mwACAyK5SNOc4wAB2LT2izsE",
    "CAACAgIAAxUAAWokXXsYLSHqWpoH_sUzsn5o6NODAAIQngACPpjASNnzb7VdPg99OwQ",
    "CAACAgIAAxUAAWokXXtUKJSuseMTx4pLII-zYnbBAAIHpwACIeC5SJSPCe_VJfIcOwQ",
    "CAACAgIAAxUAAWokXXuk-u2OnkXmtJlkln6jXGE_AAKdmAACv0bASG8MePi3-iYdOwQ",
    "CAACAgIAAxUAAWokXXts84KNb-Yep8yIk27tOaFgAAKongACjXTASBXe8jAvGkkIOwQ",
    "CAACAgIAAxkBAAICxmokYXtosRs9osXp8-nK2ezRK9qjAAKlqwACibPASKtTnKfNS3oiOwQ",
    "CAACAgIAAxUAAWokZOn6gQlM7Z_8smcno3a9Z00GAAKooAACk9W5SNftq8hewLZROwQ",
    "CAACAgIAAxUAAWokZOkdGoHrovTLlQrHGkURcQR5AAKyoAACbJy4SKWr2t1E4YauOwQ",
    "CAACAgIAAxUAAWokZOnp-2z-x-D0Ul9PnqJ6PwzoAAIJlQAC8o3BSPApjfm3IraWOwQ",
    "CAACAgIAAxUAAWokZOnnLTq1xJqrOTKzkVbHmOnYAAIlpQACuxe5SDxs-bd-F-YCOwQ",
    "CAACAgIAAxUAAWokZOl8m-AgLOa6HMkUYvRnQotwAAIjrAAC6Ri5SHqBXzswn9F5OwQ",
    "CAACAgIAAxUAAWokZOm7kQqClVUlnV3wkT2edEkBAAKSmwACUJDASPWjUECwREeAOwQ",
    "CAACAgIAAxUAAWokZOmctFGuYwENyJeyGO0d_lqWAAIglgACMDHBSKZ7QhtETDfGOwQ",
    "CAACAgIAAyEFAATeTZCOAAJSAWokT6Cj7e0s1zoTg5gxPdJapYo8AAJsngACBl7BSHF9ROkwNGOWOwQ",
    "CAACAgIAAxUAAWokZOmH-2ZJPP2Z7DqFeG97jI-OAALhmgACRSHBSPRzpTg-S8vYOwQ",
    "CAACAgIAAxUAAWokZOkSRtAt5GfnGUxsG9kL7o5uAAKphgACn1PASM3X1A5XJkJaOwQ",
    "CAACAgIAAxUAAWokZOmoWSXag6vZ1wiHW_V3EjH6AALVlQACWwjBSIHwsjgxz-eqOwQ",
    "CAACAgIAAxUAAWokZOngN6A_eSJLdZq3xrytGh9wAAIpkAACRT_BSF7HKLpJYL_FOwQ",
    "CAACAgIAAxUAAWokZOl6yTe9NwftKt9-iR0WZKk_AAJpkQACvTnASCYM--0hUPeAOwQ",
    "CAACAgIAAxUAAWokZOlsJBzvxeeVLqpd7XZgiCV-AAI4owACjZi4SLidP49Q2PyxOwQ",
    "CAACAgIAAxUAAWokZOldN9P3pnkkcaemFkwOxM1LAAJ7mwACheLBSN04fEDmufgDOwQ",
    "CAACAgIAAxUAAWokZOlwkFrdZixuEng-hgABUnybDQACipgAAgkGwUhqyU3P51S58zsE",
    "CAACAgIAAxUAAWokZOnrlHpLrrinJAtvg-MIMTHzAAJfjgACmNzBSMheEBxPr4mWOwQ",
    "CAACAgIAAxUAAWokZOkxEGKeVsZN_fgrhftqY0OpAALzjwACbAjASJLNoRMXC48vOwQ",
    "CAACAgIAAxUAAWokZOl2upUbeI9yPT4wBDyEnXTKAAIzjAACUv7BSAPrqEslfLcBOwQ",
    "CAACAgIAAxUAAWokZOnt-8l57ROaTPED9CuGBRJJAAL2jwACX3fASBmUwKncgNOrOwQ",
    "CAACAgIAAxUAAWokZOnjLLMasp29XCnLCgwnx1BtAAI2oQACzwS5SD5076zR8VexOwQ",
    "CAACAgIAAxUAAWokZOlQ6z6f40HjP6zcor9O6C-7AAJClwACoifBSGLczGbwAAHSYzsE",
    "CAACAgIAAxUAAWokZOmPfkrF464UKm3T8zce1SvJAAJisAAC0s24SP0pdNDqNyrrOwQ",
    "CAACAgIAAxUAAWokZOnO_z2IzMR8x8oJdSAUYczqAAJDpQACRW3BSBLpQYK2pwWLOwQ",
    "CAACAgIAAxUAAWokZOleYsC6_FJPIUM4RrjMp3iCAALOnQACD2_ASMa6bJbx9RVDOwQ",
    "CAACAgIAAxUAAWokZOl5JAwAAWuMMczyvOY8flzoqgACLJoAAgqLwUiRN6TYPBNXuTsE",
    "CAACAgIAAxUAAWokZOmnxVrjV77K8G0iHS2PjeaAAALUoQACmFq5SDg8Tpu-MLg1OwQ",
    "CAACAgIAAxUAAWokZOkmUKHb4xkiKFHcVEr2gWaYAAIflQACZBzASKPiEdcibbrQOwQ",
    "CAACAgIAAxUAAWokZOnAdl9FywlWPB24y5oQ8FI0AAITkAACo_TASFB1Hl5-g0K1OwQ",
    "CAACAgIAAxUAAWokZOl38u283IKlN76OpRSndEX4AAKZmQACYtnBSPkOwNcEvt8OOwQ",
    "CAACAgIAAxUAAWokZOlA-m4Oz3P_pleNlJMsmbrxAAI_qQACTY65SKYfiqLxVKYhOwQ",
]

litvin_stickers = [
    "CAACAgIAAxUAAWokZOof_KEL11Lbga2X2TTEDJtmAAL8VwACkbZhSmesSj3bmwlsOwQ",
    "CAACAgIAAxUAAWokZOrFnMJcM70JZo862P7WPqO5AAJDXAAC1MFhSsHcJdIERCutOwQ",
    "CAACAgIAAxUAAWokZOrIkImxkTZL16V2KJJR_mGSAAKAXQAC2DBgSiEJcbehp-3cOwQ",
    "CAACAgIAAxUAAWokZOpXuwcNSTsi_IhemrZR8hhGAAJ1RwACdRxgSmnk2Sit5GM-OwQ",
    "CAACAgIAAxUAAWokZOrE9zk-354_nLeJTsTS94HlAAKKTQAC865hSty6lbKlXtgUOwQ",
    "CAACAgIAAxUAAWokZOrXsQzNgWgrcaVRsjm3MQNVAALwXAAC0lBgSnMLKlnrcxCAOwQ",
    "CAACAgIAAxUAAWokZOrcRrFDfkdPiMVp5bvQZ2OCAALsVgAC7OFhSnPKTU9C9WI1OwQ",
    "CAACAgIAAxUAAWokZOqsJI0Jm2YJIVQE1_Mrm7tiAAKOYAACdr9ZShdnFOe0LN0DOwQ",
    "CAACAgIAAxUAAWokZOoBCYk2mzXFBDRmj4aya4J_AAJ2TwAC73JgSszNytteRA84OwQ",
    "CAACAgIAAxUAAWokZOqVvrfmvH3y32JkNhv7bl0xAAKvVwACLw5YStP372eX0YN3OwQ",
    "CAACAgIAAxUAAWokZOq6AAHe_JvBZ5LoabbVg9juXgACc1EAAuboYUrqWfDcSMX9UTsE",
    "CAACAgIAAxUAAWokZOq28LgHgQewLfRfbf52Wh0hAAKYUQACFJZhShIoEQABHCulaTsE",
    "CAACAgIAAxUAAWokZOoZ765j3tmLMFf0SayaoixsAALsTwACrqxgSj62cr2-QEqqOwQ",
    "CAACAgIAAxUAAWokZOoln2XHX7C9_XriE_DH832BAAKfWwACG6tgSlLbPUkNPzpqOwQ",
    "CAACAgIAAxUAAWokZOo_wrR1tZvLom5v9Hn_REedAAKJTwACw89gSkNYL_2LDqBFOwQ",
]

bred_stickers = [
    "CAACAgIAAxUAAWokZOrge-Tda8NNA5mVI1yQD9RzAAImmwACEMfgSLuhxfmBNlC7OwQ",
    "CAACAgIAAxUAAWokZOp3vYT_kqgVC0IBqWt9fJ5rAAKslQAC0AvgSC6z5DOASxnmOwQ",
    "CAACAgIAAxUAAWokZOqPy4sfhf8RwY8h923JEK6mAAJwlQACdPPgSF_79t1gAzBWOwQ",
    "CAACAgIAAxUAAWokZOpLHc-W7YaIiCj_Ja_j5dB1AAJ6mAACmDLhSGtXeSWqYIBoOwQ",
    "CAACAgIAAxUAAWokZOr5pLWAUFoiPuyVMlatINCaAAKVmgACvOThSMXEconXutNXOwQ",
    "CAACAgIAAxUAAWokZOqyjvZHu2ThY_85QQz-8D_AAAKjmAACG8TpSFN3SITsJQO9OwQ",
    "CAACAgIAAxUAAWokZOoamGkIK5nP8TRKnlGFOV2kAALumgACKwfoSGbpp5H-_FUtOwQ",
    "CAACAgIAAxUAAWokZOrJJu0mjNDupgRL8Z8ybFbQAAIFmQACYrzwSE1A45UleIJaOwQ",
    "CAACAgIAAxUAAWokZOrb0xeG9RjNaLYdQgPQRRHxAAL1oQACKI3xSA9YlAEYZ_aeOwQ",
    "CAACAgIAAxUAAWokZOrYy4OOd48SfeH_0A386bqoAAJ3oQACVf7wSE5ramK968t_OwQ",
    "CAACAgIAAxUAAWokZOqTSo8YZsXHxKNkji4TlxEdAAKTlwACyPXxSG-jPa2Ylm-FOwQ",
    "CAACAgIAAxUAAWokZOo-Fqs1C6k4ddkwIHu-dOrSAAIiowACLyfxSHSfR0DhBwswOwQ",
    "CAACAgIAAxUAAWokZOoIsyZAJ1bMRC4yOcuSxz5kAAIsoAAC8V7oSAmTkpQ-NHhROwQ",
    "CAACAgIAAxUAAWokZOq_x_mfFMJOxIj4rGCW2sxbAAIynAACXoz4SDYJ_Y2pCF65OwQ",
    "CAACAgIAAxUAAWokZOoZlEOqShv3nJw7LxsXaXBbAALIlgACDt7xSO8HU0FOnrFaOwQ",
    "CAACAgIAAxUAAWokZOoQqBEbFYo8RofwOpy3hZh4AAIUlAACX5_4SD21t5Zzk04KOwQ",
    "CAACAgIAAxUAAWokZOoNv54wg8kQxDeo50b_YKyUAAISngACNSoAAUn9reJaUS-TsDsE",
    "CAACAgIAAxUAAWokZOpJXvfbpNw4Y_B9DW4sCJvNAAL6nQACfnYBSe9ztheP5_8aOwQ",
    "CAACAgIAAxUAAWokZOpBDxoojO3KY_JD6_GV0BGlAAJeogAC1zgISRlBwYgWvghsOwQ",
    "CAACAgIAAxUAAWokZOprRsYJ8HJyxvERFosDBqj_AALemQACQqYISXWezm5Y9_0bOwQ",
    "CAACAgIAAxUAAWokZOoigHFKKEHXlypehuio6tX1AAJ4mgACn5oZSXc1HKHJXFJsOwQ",
    "CAACAgIAAxUAAWokZOpSuq334b9cVti-mhNp4eoTAAKonwAC8LMZSbfbhhb0mpvvOwQ",
    "CAACAgIAAxUAAWokZOqrLrI7I9V8SGQ62je-EgABtgACd5YAAjn-GEk-URr3nqLikjsE",
    "CAACAgIAAxUAAWokZOrRRqjXR411VMJGbKJKdQJ1AALJkgACt-EZSSmZZfiLeHZjOwQ",
    "CAACAgIAAxUAAWokZOonOSd-HQdnr_Y6Yv3sArLiAAIjlwACwQcYSZhMyxIvHudfOwQ",
    "CAACAgIAAxUAAWokZOqPh4Qognvw7OzIuqJ0Iq-VAAJenQACraQYSXQktG7N0MKmOwQ",
    "CAACAgIAAxUAAWokZOqpkOgeg7uyQTsgOCtCcykFAAI3pQACdOAZSRKLWF5d_R8JOwQ",
    "CAACAgIAAxUAAWokZOo2TxPb480UAnA8aNbwCVaVAALhqQACWS4ZSaAFhKZD0AxbOwQ",
    "CAACAgIAAxUAAWokZOqFrs_x4HBaQvhVXfC9lEspAAL6mwACOPMQSaK10V93Xs6vOwQ",
    "CAACAgIAAxUAAWokZOrBQV8gB5C3KLkNEBe1nfnJAAJHngACfKEZSV6e5DgwiooBOwQ",
    "CAACAgIAAxUAAWokZOoHbOE2ice4d6cjkNysfS9HAAJUogAC-3URSfqtER43YXroOwQ",
    "CAACAgIAAxUAAWokZOqyJo2VHov4AAHI4Cgmf59kOAACJZsAAnMcGUmMNfSSrSfYHTsE",
    "CAACAgIAAxUAAWokZOq0SvZCB8UAAcKQl6r2Xb-BQgACA6AAAlVqGElQPZbebZiuAzsE",
    "CAACAgIAAxUAAWokZOo6xNC9w054dW5XCIzW9uSsAAKFngACrXF4SGrsnKVCa62FOwQ",
    "CAACAgIAAxUAAWokZOreWIzO8BOlFSb4vbhGt99XAAKemQACnCRwSKvK93OoPelOOwQ",
    "CAACAgIAAxUAAWokZOpdVBFnZuwNKWmBOmgT5gAB-gACeJIAAofveUhyZovjqvFtYjsE",
    "CAACAgIAAxUAAWokZOpmzHzMLkYDUDNVEXOCM4hjAAJgjQACaoZ5SPqbY789bpuUOwQ",
    "CAACAgIAAxUAAWokZOqA4nZNg8BxmyZyCChETt4xAAK-jgACNEN4SIELJ6luqn4hOwQ",
    "CAACAgIAAxUAAWokZOqKY3FA-88NgB5NMUs87vu8AAIujgACiKh5SEmVOsuK3uKzOwQ",
    "CAACAgIAAxUAAWokZOqaU8j5pkJb2XVvepFiy23-AAIyiwACchZ5SAmbhgGbXPMGOwQ",
    "CAACAgIAAxUAAWokZOqd79qTfa800lPeZYd90SYEAAJliwACr7t4SPWhn36i1JBpOwQ",
    "CAACAgIAAxUAAWokZOrpm4MdI6ai5NKmG0d928QOAALslwAC93F5SLchHdGftU1NOwQ",
    "CAACAgIAAxUAAWokZOpSuOmYYTY8ZMyWh3dkZ59jAAIGhAACSLl4SHpf37KkDaPrOwQ",
    "CAACAgIAAxUAAWokZOrFbQAB38-RjCj54f_mDX56mAACgaIAAjnlcEibzWuHFqXgyDsE",
    "CAACAgIAAxUAAWokZOrh0Lz697MbO8e-8qh_sRmIAAJRkwACSuF5SCGPU2qUk-8jOwQ",
    "CAACAgIAAxUAAWokZOpsqDAdFQ6r8cerAAHKHqhHgQACUYwAAvpheUjgqXeeJFOeoTsE",
    "CAACAgIAAxUAAWokZOqiAXiA3711Q_TyiPhyFzALAALakwACwD55SBox3domPjGROwQ",
    "CAACAgIAAxUAAWokZOrG40e6MTW66zTsxm4Z-loOAAJOmAACHOB4SE3Urosl5Hw4OwQ",
        ]


# ============================================================
# ХЭНДЛЕРЫ: КОМАНДЫ
# ============================================================

@router.message(Command("start"))
async def start(message: Message):
    save_chat_id(message.chat.id)
    add_activity(message.chat.id, message.from_user.id)
    if message.chat.type == "private":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 Профиль", web_app=WebAppInfo(url=MINI_APP_URL))]
        ])
        await message.answer(
            "👋 Привет! Я бот Folk Valley.\n\n"
            "🎮 **Игры:**\n"
            "• `/game` — выбрать игру\n"
            "• `/answer` — ответ в игре\n"
            "• `/top` — топ активных\n"
            "• `/spin` — чат-рулетка (только в группах)\n\n"
            "🐱 **Животные:**\n"
            "• `/cat`, `/dog`, `/animal`\n\n"
            "🧠 `/factme` — факт о тебе\n\n"
            "🌟 `/donate` — поддержать (в ЛС)\n"
            "📩 `/offer` — идея админу (в ЛС)\n\n"
            "🎭 `/folk`, `/litvin`, `/bred`, `/sosat`, `/zabava`, `/search`, `/voice`\n\n"
            "⚙️ `/cooldown` — кулдауны\n\n"
            "🃏 `/card`, `/profile`, `/ah`",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await message.answer("Я в группе! /folk /litvin /bred /sosat /zabava /search /voice /game /top /cat /dog /animal /factme /spin /cooldown")


@router.message(Command("folk"))
async def folk(message: Message):
    save_chat_id(message.chat.id)
    add_activity(message.chat.id, message.from_user.id)
    chat_id, user_id = message.chat.id, message.from_user.id
    cool, remain = check_cd(chat_id, user_id, 'folk')
    if cool:
        s = max(0, int(remain.total_seconds()))
        m, sec = divmod(s, 60)
        await message.answer(f"⏳ {m} мин {sec} сек", reply_to_message_id=message.message_id)
        return
    if not ALL_STICKERS:
        await message.answer("Стикеры не загружены.")
        return
    await message.answer_sticker(sticker=random.choice(ALL_STICKERS))
    use_cd(chat_id, user_id, 'folk')


@router.message(Command("litvin"))
async def litvin(message: Message):
    save_chat_id(message.chat.id)
    add_activity(message.chat.id, message.from_user.id)
    chat_id, user_id = message.chat.id, message.from_user.id
    cool, remain = check_cd(chat_id, user_id, 'litvin')
    if cool:
        s = max(0, int(remain.total_seconds()))
        m, sec = divmod(s, 60)
        await message.answer(f"⏳ {m} мин {sec} сек", reply_to_message_id=message.message_id)
        return
    if not litvin_stickers:
        await message.answer("Стикеры не загружены.")
        return
    await message.answer_sticker(sticker=random.choice(litvin_stickers))
    use_cd(chat_id, user_id, 'litvin')


@router.message(Command("bred"))
async def bred(message: Message):
    save_chat_id(message.chat.id)
    add_activity(message.chat.id, message.from_user.id)
    chat_id, user_id = message.chat.id, message.from_user.id
    cool, remain = check_cd(chat_id, user_id, 'bred')
    if cool:
        s = max(0, int(remain.total_seconds()))
        m, sec = divmod(s, 60)
        await message.answer(f"⏳ {m} мин {sec} сек", reply_to_message_id=message.message_id)
        return
    if not bred_stickers:
        await message.answer("Стикеры не загружены.")
        return
    await message.answer_sticker(sticker=random.choice(bred_stickers))
    use_cd(chat_id, user_id, 'bred')


@router.message(Command("sosat"))
async def sosat(message: Message):
    save_chat_id(message.chat.id)
    add_activity(message.chat.id, message.from_user.id)
    words = random.choices(RANDOM_WORDS, k=random.randint(3, 6))
    await message.answer(" ".join(words))


@router.message(Command("zabava"))
async def zabava(message: Message):
    save_chat_id(message.chat.id)
    add_activity(message.chat.id, message.from_user.id)
    if not message.photo and not (message.reply_to_message and message.reply_to_message.photo):
        await message.answer("📸 Отправь фото с подписью /zabava текст или ответь командой на фото.")
        return
    args = get_args(message)
    if not args:
        await message.answer(
            "❌ Напиши текст.\n\nПримеры:\n"
            "/zabava 1 Текст сверху\n"
            "/zabava 2 Текст снизу\n"
            "/zabava 1 Верхний 2 Нижний"
        )
        return
    try:
        idx1 = args.index("1")
    except ValueError:
        idx1 = -1
    try:
        idx2 = args.index("2")
    except ValueError:
        idx2 = -1
    top_text = ""
    bottom_text = ""
    if idx1 == -1 and idx2 == -1:
        top_text = " ".join(args).strip()
    else:
        if idx1 != -1:
            top_parts = args[idx1+1:idx2] if (idx2 != -1 and idx2 > idx1) else args[idx1+1:]
            top_text = " ".join(top_parts).strip()
        if idx2 != -1:
            bottom_parts = args[idx2+1:idx1] if (idx1 != -1 and idx1 > idx2) else args[idx2+1:]
            bottom_text = " ".join(bottom_parts).strip()
    if not top_text and not bottom_text:
        await message.answer("❌ Текст не распознан.")
        return
    file_id = message.photo[-1].file_id if message.photo else message.reply_to_message.photo[-1].file_id
    try:
        file = await bot.get_file(file_id)
        img_bytes = io.BytesIO()
        await bot.download_file(file.file_path, img_bytes)
        image_data = img_bytes.getvalue()
    except Exception as e:
        await message.answer(f"❌ Ошибка загрузки фото: {e}")
        return
    loop = asyncio.get_event_loop()
    photo_url = await loop.run_in_executor(None, upload_to_imgbb, image_data)
    if not photo_url:
        await message.answer("❌ Не удалось загрузить фото на ImgBB.")
        return
    top_enc = urllib.parse.quote(top_text or "_")
    bottom_enc = urllib.parse.quote(bottom_text or "_")
    bg_enc = urllib.parse.quote(photo_url)
    url = f"https://api.memegen.link/images/custom/{top_enc}/{bottom_enc}.png?background={bg_enc}&font=impact"
    try:
        response = await loop.run_in_executor(None, lambda: requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30))
        if response.status_code != 200:
            await message.answer(f"❌ Ошибка генерации мема: {response.status_code}")
            return
        await message.answer_photo(photo=response.content, caption="🎭 Твой мем готов!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("search"))
async def search(message: Message):
    save_chat_id(message.chat.id)
    add_activity(message.chat.id, message.from_user.id)
    chat_id, user_id = message.chat.id, message.from_user.id
    cool, remain = check_cd(chat_id, user_id, 'search')
    if cool:
        s = max(0, int(remain.total_seconds()))
        m, sec = divmod(s, 60)
        await message.answer(f"⏳ Подожди {m} мин {sec} сек", reply_to_message_id=message.message_id)
        return
    query = " ".join(get_args(message))
    if not query:
        await message.answer("❌ Напиши запрос: /search кот")
        return
    status_msg = await message.answer(f"🔍 Ищу: {query}...")
    loop = asyncio.get_event_loop()
    try:
        translated = await loop.run_in_executor(None, translate_text, query, 'en')
        search_query = translated or query
    except Exception:
        search_query = query
    try:
        urls = await search_unsplash(search_query, per_page=10)
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {e}")
        return
    if not urls:
        await status_msg.edit_text(f"❌ Ничего не найдено: {query}")
        return
    if message.chat.type == "private":
        count = min(3, len(urls))
        selected = random.sample(urls, count)
        caption = f"🖼️ Нашёл {count} картинок: {query}"
    else:
        selected = [random.choice(urls)]
        caption = f"🖼️ Картинка: {query}"
    await status_msg.delete()
    for idx, url in enumerate(selected):
        try:
            response = await loop.run_in_executor(None, lambda: requests.get(url, timeout=15))
            if response.status_code == 200:
                await message.answer_photo(photo=response.content, caption=caption if idx == 0 else "")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
    use_cd(chat_id, user_id, 'search')


@router.message(Command("voice"))
async def voice(message: Message):
    save_chat_id(message.chat.id)
    add_activity(message.chat.id, message.from_user.id)
    chat_id, user_id = message.chat.id, message.from_user.id
    cool, remain = check_cd(chat_id, user_id, 'voice')
    if cool:
        s = max(0, int(remain.total_seconds()))
        m, sec = divmod(s, 60)
        await message.answer(f"⏳ Подожди {m} мин {sec} сек", reply_to_message_id=message.message_id)
        return
    text = " ".join(get_args(message))
    if not text:
        await message.answer("❌ Напиши текст: /voice Привет мир")
        return
    try:
        tts = gTTS(text=text, lang='ru')
        audio_bytes = BytesIO()
        tts.write_to_fp(audio_bytes)
        audio_bytes.seek(0)
        await message.answer_voice(voice=audio_bytes, caption="🔊 Озвучено!")
        use_cd(chat_id, user_id, 'voice')
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("cat"))
async def cat(message: Message):
    save_chat_id(message.chat.id)
    add_activity(message.chat.id, message.from_user.id)
    try:
        r = await asyncio.to_thread(requests.get, "https://api.thecatapi.com/v1/images/search", timeout=10)
        data = r.json()
        if data and "url" in data[0]:
            img = await asyncio.to_thread(requests.get, data[0]["url"], timeout=10)
            await message.answer_photo(photo=img.content, caption="🐱 Мяу!")
        else:
            await message.answer("❌ Не удалось найти котика!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("dog"))
async def dog(message: Message):
    save_chat_id(message.chat.id)
    add_activity(message.chat.id, message.from_user.id)
    try:
        r = await asyncio.to_thread(requests.get, "https://api.thedogapi.com/v1/images/search", timeout=10)
        data = r.json()
        if data and "url" in data[0]:
            img = await asyncio.to_thread(requests.get, data[0]["url"], timeout=10)
            await message.answer_photo(photo=img.content, caption="🐶 Гав!")
        else:
            await message.answer("❌ Не удалось найти собачку!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("top"))
async def top(message: Message):
    save_chat_id(message.chat.id)
    add_activity(message.chat.id, message.from_user.id)
    chat_id = message.chat.id
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("📊 Топ только для групп!")
        return
    stats = user_stats.get(chat_id, {})
    if not stats:
        await message.answer("📊 Пока нет активности!")
        return
    sorted_users = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]
    text = "🏆 **Топ-10:**\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for idx, (uid, count) in enumerate(sorted_users):
        try:
            member = await bot.get_chat_member(chat_id, uid)
            name = f"@{member.user.username}" if member.user.username else member.user.first_name
        except Exception:
            name = f"ID: {uid}"
        text += f"{medals[idx]} **{name}** — {count}\n"
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("factme"))
async def factme(message: Message):
    save_chat_id(message.chat.id)
    add_activity(message.chat.id, message.from_user.id)
    fact = random.choice(FACTS)
    await message.answer(f"🧠 **Факт о тебе, {message.from_user.first_name}:**\n\n{fact}", parse_mode="Markdown")


@router.message(Command("animal"))
async def animal(message: Message):
    save_chat_id(message.chat.id)
    add_activity(message.chat.id, message.from_user.id)
    a = random.choice(ANIMALS)
    await message.answer(f"🐾 **Ты — {a['name']}!**\n\n{a['emoji']} {a['description']}", parse_mode="Markdown")


@router.message(Command("spin"))
async def spin(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("🎲 Только в группах!")
        return
    known = list(user_stats.get(message.chat.id, {}).keys())[:200]
    candidates = []
    for uid in known:
        try:
            m = await bot.get_chat_member(message.chat.id, int(uid))
            if m.user and not m.user.is_bot and m.status not in ("left", "kicked"):
                candidates.append(m.user)
        except Exception:
            pass
    if not candidates:
        await message.answer("Пока не знаю активных. Пусть участники напишут что-нибудь.")
        return
    target = random.choice(candidates)
    q = random.choice(SPIN_QUESTIONS)
    name = f"@{target.username}" if target.username else (target.first_name or "Участник")
    await message.answer(f"🎲 Чат-рулетка!\n\n👤 Выпал: {name}\n❓ {q}")


@router.message(Command("offer"))
async def offer(message: Message):
    if message.chat.type != "private":
        await message.answer("❌ Только в ЛС!")
        return
    text = " ".join(get_args(message))
    if not text:
        await message.answer(
            f"📋 **Правила:**\n\n{OFFER_RULES_URL}\n\nНапиши `/offer Твоя идея`",
            parse_mode="Markdown", disable_web_page_preview=True
        )
        return
    user = message.from_user
    uname = f"@{user.username}" if user.username else user.first_name
    safe = escape_markdown(text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принять", callback_data=f"offer_accept_{user.id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"offer_reject_{user.id}"),
    ]])
    try:
        await bot.send_message(ADMIN_ID, f"📩 **Новая идея от {uname}** (ID: `{user.id}`)\n\n{safe}",
                               reply_markup=kb, parse_mode="Markdown")
        await message.answer("✅ Идея отправлена! 🙌")
    except Exception as e:
        log.error(f"Ошибка offer: {e}")
        await message.answer("❌ Ошибка отправки.")


@router.message(Command("donate"))
async def donate(message: Message):
    if message.chat.type != "private":
        await message.answer("❌ Только в ЛС!")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 10", callback_data="donate_10"),
         InlineKeyboardButton(text="⭐ 50", callback_data="donate_50")],
        [InlineKeyboardButton(text="⭐ 100", callback_data="donate_100"),
         InlineKeyboardButton(text="⭐ 200", callback_data="donate_200")],
        [InlineKeyboardButton(text="⭐ 500", callback_data="donate_500")],
        [InlineKeyboardButton(text="✏️ Своя сумма", callback_data="donate_custom")],
    ])
    await message.answer("🌟 **Поддержи бота звёздами!**", reply_markup=kb, parse_mode="Markdown")


@router.message(Command("chats"))
async def chats(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет прав!")
        return
    try:
        with open(CHATS_DB_FILE, "r", encoding="utf-8") as f:
            ids = json.load(f)
    except Exception:
        await message.answer("📭 Нет чатов.")
        return
    if not ids:
        await message.answer("📭 Пусто.")
        return
    result = f"📊 **Чатов:** {len(ids)}\n\n"
    for cid in ids[:20]:
        result += f"`{cid}`\n"
    if len(ids) > 20:
        result += f"\n... и ещё {len(ids) - 20}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📨 Разослать всем", callback_data="broadcast_all")
    ]])
    await message.answer(result, reply_markup=kb, parse_mode="Markdown")


@router.message(Command("go"))
async def go(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет прав!")
        return
    text = " ".join(get_args(message))
    if not text:
        await message.answer("❌ `/go Текст`", parse_mode="Markdown")
        return
    try:
        with open(CHATS_DB_FILE, "r", encoding="utf-8") as f:
            ids = json.load(f)
    except Exception:
        await message.answer("❌ Нет чатов!")
        return
    status = await message.answer(f"🚀 Рассылка в {len(ids)}...")
    sent = failed = 0
    for cid in ids:
        try:
            await bot.send_message(cid, text, parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.3)
    await status.edit_text(f"✅ Готово!\n📤 {sent}\n❌ {failed}\n📊 {len(ids)}")


@router.message(Command("donate_broadcast"))
async def donate_broadcast(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет прав!")
        return
    text = " ".join(get_args(message))
    if not text:
        await message.answer("❌ `/donate_broadcast Текст`", parse_mode="Markdown")
        return
    d = load_donations()
    if not d:
        await message.answer("📭 Нет донатеров!")
        return
    uids = [int(u) for u in d.keys()]
    status = await message.answer(f"🚀 Рассылка {len(uids)} донатерам...")
    sent = failed = 0
    for uid in uids:
        try:
            await bot.send_message(uid, text, parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.3)
    await status.edit_text(f"✅ Готово!\n📤 {sent}\n❌ {failed}\n📊 {len(uids)}")


@router.message(Command("donates"))
async def donates(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет прав!")
        return
    d = load_donations()
    if not d:
        await message.answer("📭 Нет донатов!")
        return
    sorted_d = sorted(d.items(), key=lambda x: x[1]["total"], reverse=True)
    total = sum(v["total"] for v in d.values())
    result = f"🌟 **Статистика:**\n\n📊 Всего: **{total}**\n👤 Донатеров: **{len(d)}**\n\n🏆 **Топ:**\n"
    for i, (uid, data) in enumerate(sorted_d[:10], 1):
        try:
            info = await bot.get_chat(int(uid))
            name = f"@{info.username}" if info.username else info.first_name
        except Exception:
            name = f"ID: {uid}"
        result += f"{i}. **{name}** — {data['total']} ({data['count']})\n"
    await message.answer(result, parse_mode="Markdown")


@router.message(Command("cancel"))
async def cancel_broadcast(message: Message):
    uid = message.from_user.id
    if uid in pending_broadcast_all:
        del pending_broadcast_all[uid]
        await message.answer("❌ Отменено.")
    else:
        await message.answer("Нет активной рассылки.")


# ============================================================
# ИГРЫ
# ============================================================

@router.message(Command("game"))
async def game(message: Message):
    save_chat_id(message.chat.id)
    add_activity(message.chat.id, message.from_user.id)
    chat_id = message.chat.id
    user_id = message.from_user.id
    if chat_id in games and games[chat_id]["active"]:
        await message.answer("❌ Игра уже идёт!")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Угадай число", callback_data=f"game_start:guess:{user_id}")],
        [InlineKeyboardButton(text="✂️ КНБ", callback_data=f"game_start:rps:{user_id}")],
        [InlineKeyboardButton(text="🧠 Викторина", callback_data=f"game_start:quiz:{user_id}")],
        [InlineKeyboardButton(text="🛑 Завершить", callback_data=f"game_stop:{user_id}")],
    ])
    await message.answer("🎮 **Выбери игру:**\n\n📝 `/answer`", reply_markup=kb, parse_mode="Markdown")


@router.message(Command("answer"))
async def answer(message: Message):
    save_chat_id(message.chat.id)
    add_activity(message.chat.id, message.from_user.id)
    chat_id = message.chat.id
    user_id = message.from_user.id
    if chat_id not in games or not games[chat_id]["active"]:
        await message.answer("❌ Нет активной игры!")
        return
    gd = games[chat_id]
    if gd["user_id"] != user_id:
        await message.answer("❌ Только создатель игры!")
        return
    text = " ".join(get_args(message))
    if not text:
        await message.answer("❌ Напиши ответ после команды!")
        return
    if gd["type"] == "guess":
        try:
            guess = int(text.strip())
        except ValueError:
            await message.answer("❌ Напиши число!")
            return
        if guess < 1 or guess > 100:
            await message.answer("❌ От 1 до 100!")
            return
        gd["data"]["tries"] += 1
        gd["data"]["users"].add(user_id)
        num = gd["data"]["number"]
        if guess == num:
            await message.answer(f"🎉 **Угадал!** Число **{num}**!\nПопыток: {gd['data']['tries']}\n\n`/game`", parse_mode="Markdown")
            games[chat_id]["active"] = False
            if chat_id in game_timers:
                game_timers[chat_id].cancel()
                del game_timers[chat_id]
            return
        hint = "📈 Больше!" if guess < num else "📉 Меньше!"
        await message.answer(f"❌ **{hint}**\nПопыток: {gd['data']['tries']}", parse_mode="Markdown")
    elif gd["type"] == "quiz":
        if gd["data"].get("answered"):
            await message.answer("❌ Уже отвечал!")
            return
        ua = text.strip().lower()
        correct = gd["data"]["answer"]
        if ua == correct:
            await message.answer(f"🎉 **Правильно!**\nОтвет: {correct}\n\n`/game`", parse_mode="Markdown")
        else:
            gd["data"]["answered"] = True
            await message.answer(f"❌ **Неверно!**\nПравильно: {correct}\n\n`/game`", parse_mode="Markdown")
        games[chat_id]["active"] = False
        if chat_id in game_timers:
            game_timers[chat_id].cancel()
            del game_timers[chat_id]


async def auto_end_game(chat_id):
    await asyncio.sleep(60)
    if chat_id in games and games[chat_id]["active"]:
        games[chat_id]["active"] = False
        try:
            await bot.send_message(chat_id, "⏰ **Игра завершена по таймауту!**\n`/game`", parse_mode="Markdown")
        except Exception:
            pass
        game_timers.pop(chat_id, None)


# ============================================================
# КОЛБЭКИ
# ============================================================

@router.callback_query(F.data.startswith("game_start:"))
async def game_start_cb(query: CallbackQuery):
    await query.answer()
    chat_id = query.message.chat.id
    user_id = query.from_user.id
    parts = query.data.split(":")
    game_type = parts[1]
    initiator = int(parts[2])
    if chat_id in games and games[chat_id]["active"]:
        await query.message.edit_text("❌ Игра уже идёт!")
        return
    if initiator != user_id:
        await query.message.edit_text("❌ Только создатель!")
        return
    games[chat_id] = {"user_id": user_id, "type": game_type, "active": True, "data": {}}
    if chat_id in game_timers:
        game_timers[chat_id].cancel()
    game_timers[chat_id] = asyncio.create_task(auto_end_game(chat_id))
    uname = query.from_user.username or query.from_user.first_name
    if game_type == "guess":
        games[chat_id]["data"] = {"number": random.randint(1, 100), "tries": 0, "users": set()}
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛑 Завершить", callback_data=f"game_stop:{user_id}")]])
        await query.message.edit_text(
            f"🎯 **Началась!** (Создатель: @{uname})\n\nЯ загадал число 1–100.\n`/answer 50`",
            reply_markup=kb, parse_mode="Markdown"
        )
    elif game_type == "rps":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🪨 Камень", callback_data=f"game_rps:камень:{user_id}")],
            [InlineKeyboardButton(text="✂️ Ножницы", callback_data=f"game_rps:ножницы:{user_id}")],
            [InlineKeyboardButton(text="📄 Бумага", callback_data=f"game_rps:бумага:{user_id}")],
            [InlineKeyboardButton(text="🛑 Завершить", callback_data=f"game_stop:{user_id}")],
        ])
        await query.message.edit_text(f"✂️ **КНБ!** (Создатель: @{uname})\n\nВыбери ход:", reply_markup=kb, parse_mode="Markdown")
    elif game_type == "quiz":
        qs = [
            {"q": "Сколько планет в Солнечной системе?", "a": "8"},
            {"q": "Столица Франции?", "a": "париж"},
            {"q": "Сколько дней в феврале в високосный год?", "a": "29"},
            {"q": "Сколько цветов в радуге?", "a": "7"},
        ]
        q = random.choice(qs)
        games[chat_id]["data"] = {"question": q["q"], "answer": q["a"].lower(), "answered": False}
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛑 Завершить", callback_data=f"game_stop:{user_id}")]])
        await query.message.edit_text(
            f"🧠 **Викторина!** (Создатель: @{uname})\n\n❓ {q['q']}\n\n`/answer ...`",
            reply_markup=kb, parse_mode="Markdown"
        )


@router.callback_query(F.data.startswith("game_stop:"))
async def game_stop_cb(query: CallbackQuery):
    await query.answer()
    chat_id = query.message.chat.id
    user_id = query.from_user.id
    if chat_id not in games or not games[chat_id]["active"]:
        await query.message.edit_text("❌ Нет игры!")
        return
    if games[chat_id]["user_id"] != user_id:
        await query.answer("Только создатель!", show_alert=True)
        return
    games[chat_id]["active"] = False
    if chat_id in game_timers:
        game_timers[chat_id].cancel()
        del game_timers[chat_id]
    await query.message.edit_text("🛑 Игра завершена!")


@router.callback_query(F.data.startswith("game_rps:"))
async def game_rps_cb(query: CallbackQuery):
    await query.answer()
    chat_id = query.message.chat.id
    user_id = query.from_user.id
    parts = query.data.split(":")
    choice = parts[1]
    if chat_id not in games or not games[chat_id]["active"] or games[chat_id]["type"] != "rps":
        await query.message.edit_text("❌ Игра неактивна!")
        return
    if games[chat_id]["user_id"] != user_id:
        await query.answer("Только создатель!", show_alert=True)
        return
    bot_choice = random.choice(["камень", "ножницы", "бумага"])
    if choice == bot_choice:
        result = "🤝 Ничья!"
    elif (choice == "камень" and bot_choice == "ножницы") or \
         (choice == "ножницы" and bot_choice == "бумага") or \
         (choice == "бумага" and bot_choice == "камень"):
        result = "🎉 Ты выиграл!"
    else:
        result = "😅 Бот выиграл!"
    em = {"камень": "🪨", "ножницы": "✂️", "бумага": "📄"}
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Ещё раз", callback_data=f"game_start:rps:{user_id}")],
        [InlineKeyboardButton(text="🛑 Завершить", callback_data=f"game_stop:{user_id}")],
    ])
    await query.message.edit_text(
        f"✂️ Ты: {em[choice]} {choice}\n🤖 Бот: {em[bot_choice]} {bot_choice}\n\n**{result}**",
        reply_markup=kb, parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("cd:"))
async def cd_button(query: CallbackQuery):
    cmd = query.data.split(":")[1]
    pending_cooldown_input[(query.message.chat.id, query.from_user.id)] = cmd
    await query.answer()
    await query.message.edit_text(f"Введи кулдаун для /{cmd} (0-3600):")


@router.callback_query(F.data == "broadcast_all")
async def broadcast_all_callback(query: CallbackQuery):
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.message.edit_text("❌ Нет прав!")
        return
    pending_broadcast_all[query.from_user.id] = True
    await query.message.edit_text("✏️ Введи текст рассылки.\n/cancel — отмена.")


@router.callback_query(F.data.startswith("offer_"))
async def offer_callback(query: CallbackQuery):
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Только админ!", show_alert=True)
        return
    await query.answer()
    parts = query.data.split("_")
    action = parts[1]
    target = int(parts[2])
    if action == "accept":
        txt = "🌟 **Спасибо за идею!** Возможно, увидишь её в следующем обновлении!"
    else:
        txt = "❌ **Твоя идея отклонена.**"
    try:
        await bot.send_message(target, txt, parse_mode="Markdown")
    except Exception as e:
        log.error(f"offer reply: {e}")
    await query.message.edit_text(query.message.text + f"\n\n✅ {action}", reply_markup=None)


@router.callback_query(F.data.startswith("donate_"))
async def donate_callback(query: CallbackQuery):
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    if data == "donate_custom":
        temp_donation_amounts[user_id] = 0
        await query.message.edit_text(
            f"✏️ Сумма: **0**\n\n",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ +5", callback_data="donate_adj_+5"),
                 InlineKeyboardButton(text="➕ +10", callback_data="donate_adj_+10")],
                [InlineKeyboardButton(text="➖ -5", callback_data="donate_adj_-5"),
                 InlineKeyboardButton(text="➖ -10", callback_data="donate_adj_-10")],
                [InlineKeyboardButton(text="✅ Отправить", callback_data="donate_send"),
                 InlineKeyboardButton(text="❌ Отмена", callback_data="donate_cancel")],
            ]),
            parse_mode="Markdown"
        )
        return
    if data.startswith("donate_adj_"):
        if user_id not in temp_donation_amounts:
            await query.message.edit_text("❌ Начни заново с /donate")
            return
        delta = int(data.split("_")[-1])
        new_amount = max(0, temp_donation_amounts[user_id] + delta)
        temp_donation_amounts[user_id] = new_amount
        await query.message.edit_text(
            f"✏️ Сумма: **{new_amount}**",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ +5", callback_data="donate_adj_+5"),
                 InlineKeyboardButton(text="➕ +10", callback_data="donate_adj_+10")],
                [InlineKeyboardButton(text="➖ -5", callback_data="donate_adj_-5"),
                 InlineKeyboardButton(text="➖ -10", callback_data="donate_adj_-10")],
                [InlineKeyboardButton(text="✅ Отправить", callback_data="donate_send"),
                 InlineKeyboardButton(text="❌ Отмена", callback_data="donate_cancel")],
            ]),
            parse_mode="Markdown"
        )
        return
    if data == "donate_cancel":
        temp_donation_amounts.pop(user_id, None)
        await query.message.edit_text("❌ Отменено.")
        return
    if data == "donate_send":
        if user_id not in temp_donation_amounts:
            await query.message.edit_text("❌ Начни заново с /donate")
            return
        amount = temp_donation_amounts.pop(user_id)
        if amount <= 0:
            await query.message.edit_text("❌ Сумма > 0!")
            return
        await create_invoice(query, user_id, amount)
        return
    try:
        amount = int(data.split("_")[1])
    except Exception:
        await query.message.edit_text("❌ Ошибка!")
        return
    await create_invoice(query, user_id, amount)


async def create_invoice(query: CallbackQuery, user_id: int, amount: int):
    try:
        link = await bot.create_invoice_link(
            title="Донат в Folk Valley",
            description=f"Пожертвование {amount} звёзд",
            payload=f"donation_{user_id}_{amount}_{int(time.time())}",
            provider_token="",
            currency="XTR",
            prices=[{"label": f"{amount} звёзд", "amount": amount}],
        )
        await query.message.edit_text(
            f"🌟 **Оплата!**\nСумма: **{amount}**\n\n[Оплатить {amount} звёзд]({link})",
            parse_mode="Markdown", disable_web_page_preview=True
        )
    except Exception as e:
        await query.message.edit_text(f"❌ Ошибка: {e}")


@router.callback_query(F.data.in_({"card_free", "card_premium"}))
async def card_callback(query: CallbackQuery):
    log.warning("CARD HIT: data=%r user=%s", query.data, query.from_user.id)
    await query.answer()
    user_id = query.from_user.id
    is_premium = query.data == "card_premium"
    now = datetime.now()
    if user_id in card_cooldowns:
        tl = card_cooldowns[user_id] + timedelta(minutes=10) - now
        if tl > timedelta(0):
            m, s = divmod(int(tl.total_seconds()), 60)
            await query.message.edit_text(f"⏳ Подожди {m} мин {s} сек!")
            return
    if is_premium and get_user_balance(user_id) < 50:
        await query.message.edit_text("❌ Нужно 50 монет!")
        return
    rarity = roll_rarity(is_premium)
    card_id, card_data = get_card_by_rarity(rarity)
    if not card_data:
        await query.message.edit_text("❌ Карточка не найдена. Монеты не списаны.")
        return
    if is_premium:
        update_user_balance(user_id, -50)
    new_card = add_card_to_user(user_id, card_id, card_data)
    card_cooldowns[user_id] = now
    emojis = {"обычная": "⬜", "редкая": "🟦", "эпическая": "🟪",
              "мифическая": "🌟", "легендарная": "👑", "секретная": "🔮"}
    caption = (
        f"{emojis.get(rarity, '🃏')} **{card_data['name']}**\n"
        f"📊 Редкость: {rarity}\n"
        f"💰 Баланс: {get_user_balance(user_id)}\n\n"
        "🔄 Следующая через 10 минут."
    )
    file_id = card_data.get("file_id")
    chat_id = query.message.chat.id
    if file_id and file_id != "1111111111":
        try:
            await bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption, parse_mode="Markdown")
            try:
                await query.message.delete()
            except Exception:
                pass
        except Exception as e:
            log.exception(f"Фото карточки: {e}")
            await query.message.edit_text(caption + "\n\n⚠️ Фото не отправилось, но карточка сохранена.", parse_mode="Markdown")
    else:
        await query.message.edit_text(caption + "\n\n🖼️ Нет изображения.", parse_mode="Markdown")
    if rarity == "секретная":
        try:
            user = query.from_user
            uname = f"@{user.username}" if user.username else user.first_name
            await bot.send_message(ADMIN_ID,
                f"🔮 **СЕКРЕТНАЯ!**\n\n👤 {uname} (ID: `{user.id}`)\n🃏 **{card_data['name']}**\n💰 {get_user_balance(user_id)}",
                parse_mode="Markdown")
        except Exception:
            pass


# ============================================================
# КАРТОЧКИ (команды)
# ============================================================

@router.message(Command("card"))
async def card(message: Message):
    user_id = message.from_user.id
    now = datetime.now()
    if user_id in card_cooldowns:
        tl = card_cooldowns[user_id] + timedelta(minutes=10) - now
        if tl > timedelta(0):
            m, s = divmod(int(tl.total_seconds()), 60)
            await message.answer(f"⏳ Подожди {m} мин {s} сек!")
            return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎴 Обычная (0)", callback_data="card_free"),
        InlineKeyboardButton(text="💎 Платная (50)", callback_data="card_premium"),
    ]])
    await message.answer(
        f"🎴 **Открыть карточку!**\n\n💰 Баланс: {get_user_balance(user_id)}",
        reply_markup=kb, parse_mode="Markdown"
    )


@router.message(Command("profile"))
async def profile(message: Message):
    user_id = message.from_user.id
    ud = get_user_card_data(user_id)
    cards = ud.get("cards", [])
    rc = {}
    for c in cards:
        r = c.get("rarity", "неизвестно")
        rc[r] = rc.get(r, 0) + 1
    emojis = {"обычная": "⬜", "редкая": "🟦", "эпическая": "🟪",
              "мифическая": "🌟", "легендарная": "👑", "секретная": "🔮"}
    text = f"👤 **Профиль**\n\n💰 {ud.get('balance', 0)}\n🃏 Всего: {ud.get('total_cards', 0)}\n\n📊 **Редкости:**\n"
    for r, c in rc.items():
        text += f"{emojis.get(r, '🃏')} {r}: {c}\n"
    if cards:
        text += "\n🃏 **Последние 5:**\n"
        for c in cards[-5:]:
            text += f"{emojis.get(c.get('rarity', 'обычная'), '🃏')} {c.get('name', '?')}\n"
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("ah"))
@router.message(Command("auction"))
async def auction(message: Message):
    args = get_args(message)
    user_id = message.from_user.id
    if not args:
        a = load_auction()
        if not a:
            await message.answer("📭 Нет лотов.\n\n`/ah sell <instance_id> <цена>`", parse_mode="Markdown")
            return
        text = "🏷️ **Лоты:**\n\n"
        for lot_id, lot in list(a.items())[:10]:
            text += f"• {lot.get('card_name', '?')} — {lot.get('price', 0)} (от {lot.get('seller', '?')})\n  `/ah buy {lot_id}`\n"
        await message.answer(text, parse_mode="Markdown")
        return
    if args[0].lower() == "sell":
        if len(args) < 3:
            await message.answer("❌ `/ah sell <instance_id> <цена>`", parse_mode="Markdown")
            return
        instance_id = args[1]
        try:
            price = int(args[2])
            if price <= 0:
                raise ValueError
        except ValueError:
            await message.answer("❌ Цена > 0!")
            return
        ud = get_user_card_data(user_id)
        card_found = next((c for c in ud.get("cards", []) if c.get("instance_id") == instance_id), None)
        if not card_found:
            await message.answer("❌ Нет такой карточки!")
            return
        ud["cards"] = [c for c in ud["cards"] if c.get("instance_id") != instance_id]
        save_user_card_data(user_id, ud)
        a = load_auction()
        lot_id = f"lot_{int(time.time()*1000)}_{random.randint(1000,9999)}"
        a[lot_id] = {
            "seller": user_id, "card_name": card_found.get("name"),
            "card_id": card_found.get("card_id"), "rarity": card_found.get("rarity"),
            "file_id": card_found.get("file_id", ""), "instance_id": instance_id,
            "price": price, "created": datetime.now().isoformat(),
        }
        save_auction(a)
        await message.answer(f"✅ **{card_found.get('name')}** выставлена за {price}!")
        return
    if args[0].lower() == "buy":
        if len(args) < 2:
            await message.answer("❌ `/ah buy <lot_id>`", parse_mode="Markdown")
            return
        lot_id = args[1]
        a = load_auction()
        lot = a.get(lot_id)
        if not lot:
            await message.answer("❌ Лот не найден!")
            return
        seller_id = lot["seller"]
        price = lot["price"]
        if seller_id == user_id:
            await message.answer("❌ Своя карточка!")
            return
        if get_user_balance(user_id) < price:
            await message.answer(f"❌ Нужно {price} монет!")
            return
        sd = get_user_card_data(seller_id)
        card_to_transfer = next((c for c in sd.get("cards", []) if c.get("instance_id") == lot.get("instance_id")), None)
        if not card_to_transfer:
            await message.answer("❌ Карточка недоступна!")
            a.pop(lot_id, None)
            save_auction(a)
            return
        update_user_balance(user_id, -price)
        update_user_balance(seller_id, price)
        sd["cards"] = [c for c in sd["cards"] if c.get("instance_id") != lot.get("instance_id")]
        save_user_card_data(seller_id, sd)
        bd = get_user_card_data(user_id)
        bd["cards"].append(card_to_transfer)
        bd["total_cards"] += 1
        save_user_card_data(user_id, bd)
        a.pop(lot_id, None)
        save_auction(a)
        await message.answer(f"✅ Куплено **{lot.get('card_name')}** за {price}!")
        return
    await message.answer("❌ `/ah sell` или `/ah buy`", parse_mode="Markdown")


# ============================================================
# АДМИН КАРТОЧКИ
# ============================================================

@router.message(Command("listcards"))
async def list_cards(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет прав!")
        return
    cards = load_cards_data()
    if not cards:
        await message.answer("📭 Нет карточек!")
        return
    text = "🃏 **Все карточки:**\n\n"
    order = {"обычная": 0, "редкая": 1, "эпическая": 2, "мифическая": 3, "легендарная": 4, "секретная": 5}
    sorted_cards = sorted(cards.items(), key=lambda x: order.get(x[1].get("rarity", "обычная"), 99))
    for cid, c in sorted_cards:
        r = c.get("rarity", "?")
        em = {"обычная": "⬜", "редкая": "🟦", "эпическая": "🟪",
              "мифическая": "🌟", "легендарная": "👑", "секретная": "🔮"}.get(r, "🃏")
        text += f"{em} `{cid}` — {c.get('name', '?')} ({r})\n"
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("addcard"))
async def add_card(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет прав!")
        return
    args = get_args(message)
    if len(args) < 4:
        await message.answer("❌ `/addcard <id> <название> <редкость> <file_id>`", parse_mode="Markdown")
        return
    card_id, name, rarity, file_id = args[0], args[1], args[2].lower(), args[3]
    if rarity not in ["обычная", "редкая", "эпическая", "мифическая", "легендарная", "секретная"]:
        await message.answer("❌ Неверная редкость!")
        return
    cards = load_cards_data()
    if card_id in cards:
        await message.answer(f"❌ ID `{card_id}` уже есть!", parse_mode="Markdown")
        return
    cards[card_id] = {"name": name, "rarity": rarity, "file_id": file_id}
    save_cards_data(cards)
    await message.answer(f"✅ **{name}** добавлена!", parse_mode="Markdown")


@router.message(Command("removecard"))
async def remove_card(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет прав!")
        return
    args = get_args(message)
    if not args:
        await message.answer("❌ `/removecard <id>`", parse_mode="Markdown")
        return
    cards = load_cards_data()
    if args[0] not in cards:
        await message.answer(f"❌ `{args[0]}` не найдена!", parse_mode="Markdown")
        return
    name = cards[args[0]].get("name", "?")
    del cards[args[0]]
    save_cards_data(cards)
    await message.answer(f"✅ **{name}** удалена!", parse_mode="Markdown")


@router.message(Command("editcard"))
async def edit_card(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет прав!")
        return
    args = get_args(message)
    if len(args) < 3:
        await message.answer("❌ `/editcard <id> <name|rarity|file_id> <значение>`", parse_mode="Markdown")
        return
    card_id, field = args[0], args[1].lower()
    value = " ".join(args[2:])
    if field not in ["name", "rarity", "file_id"]:
        await message.answer("❌ Поля: name, rarity, file_id")
        return
    cards = load_cards_data()
    if card_id not in cards:
        await message.answer(f"❌ `{card_id}` не найдена!", parse_mode="Markdown")
        return
    if field == "rarity" and value not in ["обычная", "редкая", "эпическая", "мифическая", "легендарная", "секретная"]:
        await message.answer("❌ Неверная редкость!")
        return
    old = cards[card_id].get(field, "?")
    cards[card_id][field] = value
    save_cards_data(cards)
    await message.answer(f"✅ `{field}` обновлено: `{old}` → `{value}`", parse_mode="Markdown")


@router.message(Command("givemoney"))
async def give_money(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет прав!")
        return
    args = get_args(message)
    if len(args) < 2:
        await message.answer("❌ `/givemoney <user_id> <сумма>`", parse_mode="Markdown")
        return
    try:
        target = int(args[0])
        amount = int(args[1])
    except ValueError:
        await message.answer("❌ Числа!")
        return
    if amount <= 0:
        await message.answer("❌ Сумма > 0!")
        return
    nb = update_user_balance(target, amount)
    await message.answer(f"✅ Выдано {amount} пользователю `{target}`. Новый баланс: {nb}", parse_mode="Markdown")


@router.message(Command("getid"))
async def getid(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет прав!")
        return
    reply = message.reply_to_message
    if reply and reply.photo:
        await message.answer(f"✅ `{reply.photo[-1].file_id}`", parse_mode="Markdown")
    else:
        await message.answer("❌ Ответь на фото.")


@router.message(Command("cooldown"))
async def cooldown_cmd(message: Message):
    save_chat_id(message.chat.id)
    add_activity(message.chat.id, message.from_user.id)
    if message.chat.type not in ("group", "supergroup"):
        return
    try:
        admins = await bot.get_chat_administrators(message.chat.id)
        owner = next((a for a in admins if a.status == "creator"), None)
        if not owner or message.from_user.id != owner.user.id:
            await message.answer("Только создатель группы.")
            return
    except Exception:
        await message.answer("Бот должен быть админом.")
        return
    f = get_cd(message.chat.id, 'folk')
    l = get_cd(message.chat.id, 'litvin')
    b = get_cd(message.chat.id, 'bred')
    s = get_cd(message.chat.id, 'search')
    v = get_cd(message.chat.id, 'voice')
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Folk ({f}с)", callback_data="cd:folk")],
        [InlineKeyboardButton(text=f"Litvin ({l}с)", callback_data="cd:litvin")],
        [InlineKeyboardButton(text=f"Bred ({b}с)", callback_data="cd:bred")],
        [InlineKeyboardButton(text=f"Search ({s}с)", callback_data="cd:search")],
        [InlineKeyboardButton(text=f"Voice ({v}с)", callback_data="cd:voice")],
    ])
    await message.answer(
        f"⚙️ Кулдауны:\n/folk: {f}с\n/litvin: {l}с\n/bred: {b}с\n/search: {s}с\n/voice: {v}с",
        reply_markup=kb
    )


# ============================================================
# INLINE
# ============================================================

@router.inline_query()
async def inline_query(query: InlineQuery):
    if not ALL_STICKERS:
        await query.answer([], cache_time=0, is_personal=True)
        return
    await query.answer(
        [InlineQueryResultCachedSticker(
            id=str(random.randint(100000, 999999)),
            sticker_file_id=random.choice(ALL_STICKERS),
        )],
        cache_time=0, is_personal=True,
    )


# ============================================================
# ОПЛАТА (STARS)
# ============================================================

@router.pre_checkout_query()
async def precheckout_callback(query: PreCheckoutQuery):
    try:
        parts = query.invoice_payload.split("_", 3)
        valid = (len(parts) == 4 and parts[0] == "donation"
                 and int(parts[1]) == query.from_user.id
                 and query.currency == "XTR"
                 and query.total_amount == int(parts[2])
                 and int(parts[2]) > 0)
    except Exception:
        valid = False
    if not valid:
        await query.answer(ok=False, error_message="Данные счёта не совпадают.")
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def payment_successful(message: Message):
    payment = message.successful_payment
    if not payment or payment.currency != "XTR":
        return
    charge_id = payment.telegram_payment_charge_id
    if not hasattr(bot, "_processed_payments"):
        bot._processed_payments = set()
    if charge_id and charge_id in bot._processed_payments:
        return
    add_donation(message.from_user.id, payment.total_amount)
    if charge_id:
        bot._processed_payments.add(charge_id)
    await message.answer(
        f"🌟 Спасибо за донат!\n\nТы пожертвовал {payment.total_amount} звёзд.\n"
        f"Твой вклад помогает боту развиваться! 🙌"
    )


# ============================================================
# НОВЫЕ УЧАСТНИКИ
# ============================================================

@router.message(F.new_chat_members)
async def welcome_new_member(message: Message):
    save_chat_id(message.chat.id)
    for member in message.new_chat_members:
        if member.id == bot.id:
            continue
        name = f"@{member.username}" if member.username else member.first_name
        await message.answer(f"h {name} !")


# ============================================================
# ТРИГГЕРЫ И ТЕКСТОВЫЙ РОУТЕР (В КОНЦЕ!)
# ============================================================

async def handle_triggers(message: Message):
    text = (message.text or "").strip()
    tl = text.lower()
    chat_id = message.chat.id
    user_id = message.from_user.id

    if "бугульма" in tl:
        save_chat_id(chat_id)
        add_activity(chat_id, user_id)
        cool, remain = check_cd(chat_id, user_id, 'folk')
        if cool:
            s = max(0, int(remain.total_seconds()))
            m, sec = divmod(s, 60)
            await message.answer(f"⏳ {m} мин {sec} сек", reply_to_message_id=message.message_id)
            return
        if ALL_STICKERS:
            await message.answer_sticker(sticker=random.choice(ALL_STICKERS))
            use_cd(chat_id, user_id, 'folk')
        return
    if "литвин" in tl:
        save_chat_id(chat_id)
        add_activity(chat_id, user_id)
        cool, remain = check_cd(chat_id, user_id, 'litvin')
        if cool:
            s = max(0, int(remain.total_seconds()))
            m, sec = divmod(s, 60)
            await message.answer(f"⏳ {m} мин {sec} сек", reply_to_message_id=message.message_id)
            return
        if litvin_stickers:
            await message.answer_sticker(sticker=random.choice(litvin_stickers))
            use_cd(chat_id, user_id, 'litvin')
        return
    if "бред" in tl:
        save_chat_id(chat_id)
        add_activity(chat_id, user_id)
        cool, remain = check_cd(chat_id, user_id, 'bred')
        if cool:
            s = max(0, int(remain.total_seconds()))
            m, sec = divmod(s, 60)
            await message.answer(f"⏳ {m} мин {sec} сек", reply_to_message_id=message.message_id)
            return
        if bred_stickers:
            await message.answer_sticker(sticker=random.choice(bred_stickers))
            use_cd(chat_id, user_id, 'bred')
        return
    if tl == "мой факт":
        save_chat_id(chat_id)
        add_activity(chat_id, user_id)
        fact = random.choice(FACTS)
        await message.answer(f"🧠 **Факт о тебе, {message.from_user.first_name}:**\n\n{fact}", parse_mode="Markdown")
        return
    if tl in ["моё животное", "мое животное"]:
        save_chat_id(chat_id)
        add_activity(chat_id, user_id)
        a = random.choice(ANIMALS)
        await message.answer(f"🐾 **Ты — {a['name']}!**\n\n{a['emoji']} {a['description']}", parse_mode="Markdown")
        return
    if text in ["п", "П", "p", "P"]:
        save_chat_id(chat_id)
        add_activity(chat_id, user_id)
        await message.answer("п")
        return


async def handle_broadcast_all_input(message: Message):
    uid = message.from_user.id
    if uid not in pending_broadcast_all:
        return
    del pending_broadcast_all[uid]
    text = (message.text or "").strip()
    if not text:
        await message.answer("❌ Пусто. Отменено.")
        return
    try:
        with open(CHATS_DB_FILE, "r", encoding="utf-8") as f:
            ids = json.load(f)
    except Exception:
        await message.answer("❌ Нет чатов!")
        return
    if not ids:
        await message.answer("❌ Пусто!")
        return
    status = await message.answer(f"🚀 Рассылка в {len(ids)}...")
    sent = failed = 0
    for cid in ids:
        try:
            await bot.send_message(cid, text, parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.3)
    await status.edit_text(f"✅ Готово!\n📤 {sent}\n❌ {failed}\n📊 {len(ids)}")


async def cd_input(message: Message):
    key = (message.chat.id, message.from_user.id)
    if key not in pending_cooldown_input:
        return
    cmd = pending_cooldown_input.pop(key)
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Нужно число. Отмена.")
        return
    sec = int(text)
    if not 0 <= sec <= 3600:
        await message.answer("0-3600. Отмена.")
        return
    chat_cooldowns.setdefault(message.chat.id, {})[cmd] = sec
    await message.answer(f"✅ /{cmd}: {sec}с")


@router.message(F.text)
async def handle_text_router(message: Message):
    if not message.text:
        return
    uid = message.from_user.id
    if uid == ADMIN_ID and uid in pending_broadcast_all:
        return await handle_broadcast_all_input(message)
    key = (message.chat.id, uid)
    if key in pending_cooldown_input:
        return await cd_input(message)
    if message.text.startswith("/"):
        return
    await handle_triggers(message)


# ============================================================
# ОШИБКИ
# ============================================================

async def global_error_handler(event):
    log.error("Ошибка обработчика: %r", event.exception, exc_info=event.exception)


# ============================================================
# FLASK
# ============================================================

flask_app = Flask(__name__)


@flask_app.route('/getUserGroups')
def get_user_groups():
    uid = request.args.get('user_id', type=str)
    if not uid or not uid.lstrip('-').isdigit():
        return jsonify({"ok": False, "error": "user_id must be an integer"}), 400
    return jsonify({"ok": True, "result": user_groups.get(int(uid), [])})


def run_flask():
    flask_app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)


# ============================================================
# MAIN
# ============================================================

async def main():
    global bot
    migrate_files()
    load_user_groups()
    load_stats()

    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    dp.errors.register(global_error_handler)

    if MONITOR_CHAT_ID:
        asyncio.create_task(monitor_loop())

    threading.Thread(target=run_flask, daemon=True, name="flask-server").start()

    log.info("Бот запускается! folk=%s litvin=%s bred=%s",
             len(ALL_STICKERS), len(litvin_stickers), len(bred_stickers))

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
