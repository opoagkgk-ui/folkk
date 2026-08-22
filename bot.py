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
import time
from collections import defaultdict
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
from deep_translator import GoogleTranslator
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

# ==================== ТОКЕН ИЗ ОКРУЖЕНИЯ ====================
TOKEN = os.environ.get("API_TOKEN")
if not TOKEN:
    raise ValueError("Переменная окружения API_TOKEN не установлена!")

ADMIN_ID = 8371473442

MINI_APP_URL = "https://jalal-p7p9.onrender.com"

IMGBB_API_KEY = "2bbaa8526b22fc8d7930403e13dbbdcd"
UNSPLASH_ACCESS_KEY = "VTNenGnCKKbtcMddc_oN6qg5AGpmEXKUMDHK99qkbiA"

# ==================== ШРИФТ С АВТО-ЗАГРУЗКОЙ ====================
FONT_URLS = [
    "https://raw.githubusercontent.com/ArtifexSoftware/urw-base35-fonts/master/Impact.ttf",
    "https://github.com/ArtifexSoftware/urw-base35-fonts/raw/master/Impact.ttf",
]
FONT_PATH = "Impact.ttf"

def download_font():
    if os.path.exists(FONT_PATH):
        return True
    for url in FONT_URLS:
        try:
            print(f"📥 Пытаемся скачать шрифт с {url}...")
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                with open(FONT_PATH, "wb") as f:
                    f.write(response.content)
                print("✅ Шрифт Impact успешно загружен!")
                return True
        except Exception as e:
            print(f"⚠️ Не удалось загрузить с {url}: {e}")
            continue
    print("❌ Не удалось скачать шрифт Impact, будет использован запасной шрифт.")
    return False

def get_impact_font(size):
    if not os.path.exists(FONT_PATH):
        download_font()
    paths = [
        FONT_PATH,
        "/app/shared/Impact.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except:
                continue
    return ImageFont.load_default().font_variant(size=size)

# ==================== СОХРАНЕНИЕ ЧАТОВ ====================
CHATS_DB_FILE = "all_chats.json"
DONATIONS_FILE = "donations.json"

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

def save_donations(donations):
    with open(DONATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(donations, f, ensure_ascii=False, indent=2)

def add_donation(user_id, amount):
    donations = load_donations()
    user_id_str = str(user_id)
    if user_id_str not in donations:
        donations[user_id_str] = {"total": 0, "count": 0, "last": None}
    donations[user_id_str]["total"] += amount
    donations[user_id_str]["count"] += 1
    donations[user_id_str]["last"] = datetime.now().isoformat()
    save_donations(donations)

# Для донатов (своя сумма)
temp_donation_amounts = {}

# Ожидание рассылки
pending_broadcast_all = {}

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

# ==================== СТИКЕРЫ (ПУСТО - ВСТАВЬ СВОИ) ====================
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

# ==================== СЛОВАРИ ====================
cooldowns_folk = {}
cooldowns_litvin = {}
cooldowns_bred = {}
cooldowns_search = {}
cooldowns_voice = {}
chat_cooldowns = {}
pending_cooldown_input = {}

user_stats = {}
USER_STATS_FILE = "user_stats.json"

games = {}
game_timers = {}

USER_GROUPS_FILE = "user_groups.json"
user_groups = {}

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# ==================== ФУНКЦИИ ДЛЯ РЕЙТИНГА ====================
def load_stats():
    global user_stats
    if os.path.exists(USER_STATS_FILE):
        try:
            with open(USER_STATS_FILE, 'r', encoding='utf-8') as f:
                user_stats = json.load(f)
                user_stats = {int(k): {int(uid): count for uid, count in v.items()} 
                              for k, v in user_stats.items()}
        except:
            user_stats = {}

def save_stats():
    try:
        with open(USER_STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_stats, f, ensure_ascii=False, indent=2)
    except:
        pass

def add_activity(chat_id, user_id):
    chat_id = int(chat_id)
    user_id = int(user_id)
    if chat_id not in user_stats:
        user_stats[chat_id] = {}
    user_stats[chat_id][user_id] = user_stats[chat_id].get(user_id, 0) + 1
    save_stats()

# ==================== ЗАГРУЗКА НА IMGBB ====================
def upload_to_imgbb(image_bytes):
    url = "https://api.imgbb.com/1/upload"
    encoded_image = base64.b64encode(image_bytes).decode('utf-8')
    payload = {
        "key": IMGBB_API_KEY,
        "image": encoded_image,
        "name": "meme.jpg",
        "expiration": 86400
    }
    try:
        resp = requests.post(url, data=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("success"):
            return data["data"]["url"]
        else:
            logging.error(f"Ошибка ImgBB: {data}")
            return None
    except Exception as e:
        logging.error(f"Исключение при загрузке на ImgBB: {e}")
        return None

# ==================== ПЕРЕВОД ====================
def translate_text(text, target_lang='en'):
    try:
        translated = GoogleTranslator(source='auto', target=target_lang).translate(text)
        return translated
    except Exception as e:
        logging.error(f"Ошибка перевода: {e}")
        return text

# ==================== КУЛДАУНЫ ====================
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

def get_cd(chat_id, command):
    if chat_id not in chat_cooldowns:
        chat_cooldowns[chat_id] = {
            'folk': 60,
            'litvin': 60,
            'bred': 60,
            'search': 600,
            'voice': 30
        }
    return chat_cooldowns[chat_id].get(command, 60 if command != 'search' else 600)

def get_cd_dict(command):
    if command == 'folk':
        return cooldowns_folk
    elif command == 'litvin':
        return cooldowns_litvin
    elif command == 'bred':
        return cooldowns_bred
    elif command == 'search':
        return cooldowns_search
    elif command == 'voice':
        return cooldowns_voice
    return {}

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

# ==================== UNSPLASH ====================
async def search_unsplash(query, per_page=10):
    url = "https://api.unsplash.com/search/photos"
    headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
    params = {"query": query, "per_page": per_page, "page": 1}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    logging.error(f"Unsplash ошибка: {resp.status}")
                    return []
                data = await resp.json()
                results = data.get("results", [])
                return [item["urls"]["regular"] for item in results]
        except Exception as e:
            logging.error(f"Ошибка Unsplash: {e}")
            return []

# ==================== ТАЙМАУТ ИГР ====================
async def auto_end_game(chat_id, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(60)
    if chat_id in games and games[chat_id]["active"]:
        games[chat_id]["active"] = False
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⏰ **Игра завершена по таймауту!**\nТеперь можно запустить новую: `/game`",
                parse_mode="Markdown"
            )
        except:
            pass
        if chat_id in game_timers:
            del game_timers[chat_id]

# ==================== ДОНАТЫ ====================
async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("❌ Эта команда доступна только в личных сообщениях!")
        return
    
    user_id = update.effective_user.id
    kb = [
        [
            InlineKeyboardButton("⭐ 10 звезд", callback_data=f"donate_10"),
            InlineKeyboardButton("⭐ 50 звезд", callback_data=f"donate_50"),
        ],
        [
            InlineKeyboardButton("⭐ 100 звезд", callback_data=f"donate_100"),
            InlineKeyboardButton("⭐ 200 звезд", callback_data=f"donate_200"),
        ],
        [
            InlineKeyboardButton("⭐ 500 звезд", callback_data=f"donate_500"),
        ],
        [
            InlineKeyboardButton("✏️ Своя сумма", callback_data=f"donate_custom"),
        ],
    ]
    await update.message.reply_text(
        "🌟 **Поддержи бота звёздами!**\n\n"
        "Выбери сумму доната в звёздах Telegram. После оплаты ты получишь уведомление, а бот запомнит твой вклад.",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def donate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == "donate_custom":
        temp_donation_amounts[user_id] = 0
        await query.edit_message_text(
            "✏️ **Настрой сумму доната:**\n\n"
            f"💰 Текущая сумма: **0 звёзд**\n\n"
            "Используй кнопки ниже для изменения суммы.\n"
            "Когда будет готово, нажми «Отправить».",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("➕ +5", callback_data="donate_adj_+5"),
                    InlineKeyboardButton("➕ +10", callback_data="donate_adj_+10"),
                ],
                [
                    InlineKeyboardButton("➖ -5", callback_data="donate_adj_-5"),
                    InlineKeyboardButton("➖ -10", callback_data="donate_adj_-10"),
                ],
                [
                    InlineKeyboardButton("✅ Отправить", callback_data="donate_send"),
                    InlineKeyboardButton("❌ Отменить", callback_data="donate_cancel"),
                ],
            ]),
            parse_mode="Markdown"
        )
        return
    
    if data.startswith("donate_adj_"):
        if user_id not in temp_donation_amounts:
            await query.edit_message_text("❌ Ошибка. Начни заново с /donate")
            return
        delta = int(data.split("_")[-1])
        new_amount = temp_donation_amounts[user_id] + delta
        if new_amount < 0:
            new_amount = 0
        temp_donation_amounts[user_id] = new_amount
        await query.edit_message_text(
            f"✏️ **Настрой сумму доната:**\n\n"
            f"💰 Текущая сумма: **{new_amount} звёзд**\n\n"
            "Используй кнопки ниже для изменения суммы.\n"
            "Когда будет готово, нажми «Отправить».",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("➕ +5", callback_data="donate_adj_+5"),
                    InlineKeyboardButton("➕ +10", callback_data="donate_adj_+10"),
                ],
                [
                    InlineKeyboardButton("➖ -5", callback_data="donate_adj_-5"),
                    InlineKeyboardButton("➖ -10", callback_data="donate_adj_-10"),
                ],
                [
                    InlineKeyboardButton("✅ Отправить", callback_data="donate_send"),
                    InlineKeyboardButton("❌ Отменить", callback_data="donate_cancel"),
                ],
            ]),
            parse_mode="Markdown"
        )
        return
    
    if data == "donate_cancel":
        if user_id in temp_donation_amounts:
            del temp_donation_amounts[user_id]
        await query.edit_message_text("❌ Отменено.")
        return
    
    if data == "donate_send":
        if user_id not in temp_donation_amounts:
            await query.edit_message_text("❌ Ошибка. Начни заново с /donate")
            return
        amount = temp_donation_amounts.pop(user_id)
        if amount <= 0:
            await query.edit_message_text("❌ Сумма должна быть больше 0 звёзд!")
            return
        await create_invoice_and_send(query, user_id, amount, context)
        return
    
    try:
        amount = int(data.split("_")[1])
    except:
        await query.edit_message_text("❌ Ошибка! Попробуй снова.")
        return
    await create_invoice_and_send(query, user_id, amount, context)

async def create_invoice_and_send(query, user_id, amount, context):
    try:
        invoice_link = await context.bot.create_invoice_link(
            title="Донат в Folk Valley Bot",
            description=f"Пожертвование {amount} звёзд",
            payload=f"donation_{user_id}_{amount}_{int(time.time())}",
            provider_token="",
            currency="XTR",
            prices=[{"label": f"{amount} звёзд", "amount": amount}]
        )
        await query.edit_message_text(
            f"🌟 **Ссылка на оплату создана!**\n\n"
            f"Сумма: **{amount} звёзд**\n"
            f"Нажми на кнопку ниже, чтобы оплатить:\n\n"
            f"[Оплатить {amount} звёзд]({invoice_link})",
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка создания счёта: {e}")

async def payment_successful(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    payment = message.successful_payment
    if not payment:
        return
    
    user_id = update.effective_user.id
    amount = payment.total_amount
    
    add_donation(user_id, amount)
    
    await message.reply_text(
        f"🌟 **Спасибо за донат!**\n\n"
        f"Ты пожертвовал **{amount} звёзд**.\n"
        f"Твой вклад помогает боту развиваться! 🙌",
        parse_mode="Markdown"
    )

# ==================== НОВЫЕ КОМАНДЫ: /spin и /offer ====================
async def spin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Чат-рулетка: выбирает случайного участника и задаёт вопрос."""
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("🎲 Эта команда работает только в группах!")
        return
    
    # Получаем список участников (до 200)
    try:
        members = await context.bot.get_chat_members(chat.id, limit=200)
    except Exception as e:
        await update.message.reply_text(f"❌ Не могу получить список участников: {e}")
        return
    
    if not members:
        await update.message.reply_text("❌ В чате нет участников!")
        return
    
    # Выбираем случайного участника (исключаем бота)
    bot_id = context.bot.id
    valid_members = [m for m in members if m.user.id != bot_id]
    if not valid_members:
        await update.message.reply_text("❌ Нет участников, кроме бота!")
        return
    
    target = random.choice(valid_members).user
    question = random.choice(SPIN_QUESTIONS)
    
    await update.message.reply_text(
        f"🎲 **Чат-рулетка!**\n\n"
        f"👤 Выпал: @{target.username if target.username else target.first_name}\n"
        f"❓ Вопрос: **{question}**",
        parse_mode="Markdown"
    )

async def offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Предложка: отправляет идею админу (только в ЛС)."""
    if update.effective_chat.type != "private":
        await update.message.reply_text("❌ Эта команда доступна только в личных сообщениях!")
        return
    
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text(
            "❌ Напиши свою идею после команды:\n`/offer Идея для бота`",
            parse_mode="Markdown"
        )
        return
    
    user = update.effective_user
    user_id = user.id
    user_name = f"@{user.username}" if user.username else user.first_name
    
    # Отправляем админу
    kb = [
        [
            InlineKeyboardButton("✅ Принять", callback_data=f"offer_accept_{user_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"offer_reject_{user_id}"),
        ]
    ]
    
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📩 **Новая идея от {user_name}** (ID: `{user_id}`)\n\n{text}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    
    await update.message.reply_text(
        "✅ Твоя идея отправлена админу! Спасибо за вклад! 🙌"
    )

async def offer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок админа для предложки."""
    query = update.callback_query
    await query.answer()
    
    user_id_from_callback = query.from_user.id
    if user_id_from_callback != ADMIN_ID:
        await query.answer("❌ Только админ может это делать!", show_alert=True)
        return
    
    data = query.data
    parts = data.split("_")
    action = parts[1]  # accept или reject
    target_user_id = int(parts[2])
    
    if action == "accept":
        response_text = "🌟 **Спасибо за идею!** Возможно, ты увидишь её в следующем обновлении!"
    else:
        response_text = "❌ **Ваша идея отклонена.** Возможно, она не подходит по правилам или не по теме."
    
    try:
        await context.bot.send_message(chat_id=target_user_id, text=response_text, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Не удалось отправить ответ пользователю {target_user_id}: {e}")
    
    # Удаляем кнопки у админа
    await query.edit_message_text(
        text=query.message.text + f"\n\n✅ {action.capitalize()} (ответ отправлен)",
        reply_markup=None
    )
    await query.answer("✅ Готово!")

# ==================== АДМИН-КОМАНДЫ ====================
async def chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ Нет прав!")
        return
    
    try:
        with open(CHATS_DB_FILE, "r", encoding="utf-8") as f:
            chat_ids = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        await update.message.reply_text("📭 Нет сохранённых чатов.")
        return
    
    if not chat_ids:
        await update.message.reply_text("📭 Список чатов пуст.")
        return
    
    result = f"📊 **Всего чатов:** {len(chat_ids)}\n\n"
    for chat_id in chat_ids[:20]:
        result += f"`{chat_id}`\n"
    if len(chat_ids) > 20:
        result += f"\n... и ещё {len(chat_ids) - 20} чатов"
    
    kb = [[InlineKeyboardButton("📨 Разослать всем", callback_data="broadcast_all")]]
    await update.message.reply_text(
        result,
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def broadcast_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id != ADMIN_ID:
        await query.edit_message_text("❌ Нет прав!")
        return
    
    pending_broadcast_all[user_id] = True
    await query.edit_message_text(
        "✏️ **Введи текст для рассылки во все чаты.**\n"
        "Просто напиши сообщение.\n"
        "Чтобы отменить — напиши /cancel.",
        parse_mode="Markdown"
    )

async def handle_broadcast_all_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    
    if user_id not in pending_broadcast_all:
        return
    
    del pending_broadcast_all[user_id]
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("❌ Пустое сообщение. Отменено.")
        return
    
    try:
        with open(CHATS_DB_FILE, "r", encoding="utf-8") as f:
            chat_ids = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        await update.message.reply_text("❌ Нет сохранённых чатов!")
        return
    
    if not chat_ids:
        await update.message.reply_text("❌ Список чатов пуст!")
        return
    
    status_msg = await update.message.reply_text(f"🚀 Начинаю рассылку в {len(chat_ids)} чатов...")
    
    sent = 0
    failed = 0
    for chat_id in chat_ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            sent += 1
        except:
            failed += 1
        time.sleep(0.3)
    
    await status_msg.edit_text(
        f"✅ **Рассылка завершена!**\n\n"
        f"📤 Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}\n"
        f"📊 Всего чатов: {len(chat_ids)}",
        parse_mode="Markdown"
    )

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in pending_broadcast_all:
        del pending_broadcast_all[user_id]
        await update.message.reply_text("❌ Отменено.")
    else:
        await update.message.reply_text("Нет активной рассылки.")

async def go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ У тебя нет прав для этой команды!")
        return
    
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text(
            "❌ Напиши текст для рассылки:\n`/go Текст сообщения`",
            parse_mode="Markdown"
        )
        return
    
    try:
        with open(CHATS_DB_FILE, "r", encoding="utf-8") as f:
            chat_ids = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        await update.message.reply_text("❌ Нет сохранённых чатов!")
        return
    
    if not chat_ids:
        await update.message.reply_text("❌ Список чатов пуст!")
        return
    
    status_msg = await update.message.reply_text(f"🚀 Начинаю рассылку в {len(chat_ids)} чатов...")
    
    sent = 0
    failed = 0
    for chat_id in chat_ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            sent += 1
        except:
            failed += 1
        time.sleep(0.3)
    
    await status_msg.edit_text(
        f"✅ **Рассылка завершена!**\n\n"
        f"📤 Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}\n"
        f"📊 Всего чатов: {len(chat_ids)}",
        parse_mode="Markdown"
    )

async def donate_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ У тебя нет прав для этой команды!")
        return
    
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text(
            "❌ Напиши текст для рассылки донатерам:\n`/donate_broadcast Текст`",
            parse_mode="Markdown"
        )
        return
    
    donations = load_donations()
    if not donations:
        await update.message.reply_text("📭 Нет донатеров!")
        return
    
    user_ids = [int(uid) for uid in donations.keys()]
    status_msg = await update.message.reply_text(f"🚀 Начинаю рассылку {len(user_ids)} донатерам...")
    
    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
            sent += 1
        except:
            failed += 1
        time.sleep(0.3)
    
    await status_msg.edit_text(
        f"✅ **Рассылка донатерам завершена!**\n\n"
        f"📤 Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}\n"
        f"📊 Всего донатеров: {len(user_ids)}",
        parse_mode="Markdown"
    )

async def donates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ У тебя нет прав для этой команды!")
        return
    
    donations = load_donations()
    if not donations:
        await update.message.reply_text("📭 Пока нет донатов!")
        return
    
    sorted_donations = sorted(
        donations.items(),
        key=lambda x: x[1]["total"],
        reverse=True
    )
    
    total_stars = sum(d["total"] for d in donations.values())
    total_users = len(donations)
    
    result = f"🌟 **Статистика донатов:**\n\n"
    result += f"📊 Всего собрано: **{total_stars} звёзд**\n"
    result += f"👤 Уникальных донатеров: **{total_users}**\n\n"
    result += "🏆 **Топ донатеров:**\n"
    
    for i, (uid, data) in enumerate(sorted_donations[:10], 1):
        try:
            user_info = await context.bot.get_chat(int(uid))
            name = user_info.first_name or "Пользователь"
            if user_info.username:
                name = f"@{user_info.username}"
        except:
            name = f"ID: {uid}"
        
        result += f"{i}. **{name}** — {data['total']} звёзд ({data['count']} донатов)\n"
    
    await update.message.reply_text(result, parse_mode="Markdown")

# ==================== /factme и /animal ====================
async def factme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
    user = update.effective_user
    fact = random.choice(FACTS)
    await update.message.reply_text(
        f"🧠 **Факт о тебе, {user.first_name}:**\n\n{fact}",
        parse_mode="Markdown"
    )

async def animal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
    animal_data = random.choice(ANIMALS)
    await update.message.reply_text(
        f"🐾 **Ты — {animal_data['name']}!**\n\n{animal_data['emoji']} {animal_data['description']}",
        parse_mode="Markdown"
    )

# ==================== ПРИВЕТСТВИЕ ====================
async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            continue
        if member.username:
            await update.message.reply_text(f"h @{member.username} !")
        else:
            await update.message.reply_text(f"h {member.first_name} !")

# ==================== КОМАНДЫ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
    if update.effective_chat.type == "private":
        keyboard = [[InlineKeyboardButton("👤 Профиль", web_app=WebAppInfo(url=MINI_APP_URL))]]
        await update.message.reply_text(
            "👋 Привет! Я бот Folk Valley.\n\n"
            "🎮 **Игры:**\n"
            "• `/game` — выбрать игру (угадай число, КНБ, викторина)\n"
            "• Для ответа используй `/answer` (только для создателя игры)\n"
            "• `/top` — топ активных пользователей\n"
            "• `/spin` — чат-рулетка (только в группах)\n\n"
            "🐱 **Животные:**\n"
            "• `/cat` — случайный котик\n"
            "• `/dog` — случайная собачка\n"
            "• `/animal` — кто ты сегодня?\n\n"
            "🧠 **Забавное:**\n"
            "• `/factme` — случайный факт о тебе\n\n"
            "🌟 **Донат:**\n"
            "• `/donate` — поддержать бота звёздами (только в ЛС)\n\n"
            "📩 **Предложка:**\n"
            "• `/offer` — отправить идею админу (только в ЛС)\n\n"
            "🎭 **Развлечения:**\n"
            "• `/folk`, `/litvin`, `/bred` — стикеры\n"
            "• `/sosat` — бессвязный бред\n"
            "• `/zabava` — мем из фото + текст (1 верх, 2 низ)\n"
            "• `/search` — поиск картинок (1 в группе, 3 в лс)\n"
            "• `/voice` — озвучить текст\n\n"
            "⚙️ **Управление:**\n"
            "• `/cooldown` — кулдауны (владелец группы)\n\n"
            "🔄 **Триггеры:**\n"
            "• «бугульма», «литвин», «бред» — стикеры\n"
            "• «мой факт» — случайный факт о тебе\n"
            "• «моё животное» — кто ты сегодня\n"
            "• «п» — бот ответит «п»",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("Я в группе! /folk /litvin /bred /sosat /zabava /search /voice /game /top /cat /dog /animal /factme /spin /cooldown")

async def folk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
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
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
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
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
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
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
    words = random.choices(RANDOM_WORDS, k=random.randint(3, 6))
    await update.message.reply_text(" ".join(words))

# ==================== /zabava ====================
async def zabava(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
    message = update.message
    
    if not message.photo and not (message.reply_to_message and message.reply_to_message.photo):
        await message.reply_text("📸 Отправь фото с подписью /zabava текст или ответь командой на фото.")
        return

    args = context.args
    if not args:
        await message.reply_text(
            "❌ Напиши текст.\n\n"
            "Примеры:\n"
            "/zabava 1 Текст сверху\n"
            "/zabava 2 Текст снизу\n"
            "/zabava 1 Верхний 2 Нижний\n"
            "Если без цифр, текст будет сверху."
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
            if idx2 != -1 and idx2 > idx1:
                top_parts = args[idx1+1:idx2]
            else:
                top_parts = args[idx1+1:]
            top_text = " ".join(top_parts).strip()
        if idx2 != -1:
            if idx1 != -1 and idx1 > idx2:
                bottom_parts = args[idx2+1:idx1]
            else:
                bottom_parts = args[idx2+1:]
            bottom_text = " ".join(bottom_parts).strip()

    if not top_text and not bottom_text:
        await message.reply_text("❌ Текст не распознан. Пример: /zabava 1 Привет 2 Мир")
        return

    if message.photo:
        file_id = message.photo[-1].file_id
    else:
        file_id = message.reply_to_message.photo[-1].file_id

    try:
        file = await context.bot.get_file(file_id)
        img_bytes = io.BytesIO()
        await file.download_to_memory(img_bytes)
        img_bytes.seek(0)
        image = Image.open(img_bytes).convert("RGB")
    except Exception as e:
        await message.reply_text(f"❌ Ошибка загрузки фото: {e}")
        return

    max_size = 1200
    if max(image.width, image.height) > max_size:
        ratio = max_size / max(image.width, image.height)
        new_size = (int(image.width * ratio), int(image.height * ratio))
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    draw = ImageDraw.Draw(image)
    width, height = image.size
    
    font_size = max(int(height / 10), 16)
    font = get_impact_font(font_size)

    def wrap_text(text, font, max_width):
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = f"{current_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        return lines

    def draw_text_with_outline(text, y_start, is_top=True):
        if not text:
            return
        
        max_width = width - 40
        lines = wrap_text(text, font, max_width)
        
        if not lines:
            return
        
        total_height = 0
        line_heights = []
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_height = bbox[3] - bbox[1] + 5
            line_heights.append(line_height)
            total_height += line_height
        
        if not is_top:
            y_start = height - 10 - total_height
        
        y = y_start
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            line_width = bbox[2] - bbox[0]
            x = (width - line_width) // 2
            
            for dx, dy in [(-2, -2), (-2, 0), (-2, 2), (0, -2), (0, 2), (2, -2), (2, 0), (2, 2)]:
                draw.text((x + dx, y + dy), line, font=font, fill="black")
            
            draw.text((x, y), line, font=font, fill="white")
            y += line_heights[i]

    draw_text_with_outline(top_text, 10, is_top=True)
    
    if bottom_text:
        draw_text_with_outline(bottom_text, height - 10, is_top=False)

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=92)
    output.seek(0)
    
    await message.reply_photo(photo=output, caption="🎭 Твой мем готов!")

# ==================== /search ====================
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    message = update.message

    cool, remain = check_cd(chat_id, user_id, 'search')
    if cool:
        m, s = divmod(remain.seconds, 60)
        await message.reply_text(f"⏳ Подожди {m} мин {s} сек", quote=True)
        return

    query = " ".join(context.args) if context.args else ""
    if not query:
        await message.reply_text("❌ Напиши запрос: /search кот")
        return

    status_msg = await message.reply_text(f"🔍 Ищу картинки по запросу: {query}...")
    loop = asyncio.get_event_loop()

    try:
        translated_query = await loop.run_in_executor(None, translate_text, query, 'en')
        logging.info(f"Переведено: '{query}' -> '{translated_query}'")
        search_query = translated_query if translated_query else query
    except Exception as e:
        logging.error(f"Ошибка перевода, использую оригинал: {e}")
        search_query = query

    try:
        urls = await search_unsplash(search_query, per_page=10)
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка поиска: {e}")
        return

    if not urls:
        await status_msg.edit_text(f"❌ Ничего не найдено по запросу: {query}")
        return

    if update.effective_chat.type == "private":
        count = min(3, len(urls))
        selected = random.sample(urls, count)
        caption = f"🖼️ Нашёл {count} картинок по запросу: {query}"
    else:
        count = 1
        selected = [random.choice(urls)]
        caption = f"🖼️ Картинка по запросу: {query}"

    await status_msg.delete()

    for idx, url in enumerate(selected):
        try:
            response = await loop.run_in_executor(None, requests.get, url)
            if response.status_code == 200:
                cap = caption if idx == 0 else ""
                await message.reply_photo(photo=response.content, caption=cap)
            else:
                await message.reply_text(f"❌ Не удалось загрузить картинку: {url[:50]}...")
        except Exception as e:
            await message.reply_text(f"❌ Ошибка при загрузке: {e}")

    use_cd(chat_id, user_id, 'search')

# ==================== /voice ====================
async def voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    message = update.message

    cool, remain = check_cd(chat_id, user_id, 'voice')
    if cool:
        m, s = divmod(remain.seconds, 60)
        await message.reply_text(f"⏳ Подожди {m} мин {s} сек", quote=True)
        return

    text = " ".join(context.args) if context.args else ""
    if not text:
        await message.reply_text("❌ Напиши текст: /voice Привет мир")
        return

    try:
        tts = gTTS(text=text, lang='ru')
        audio_bytes = BytesIO()
        tts.write_to_fp(audio_bytes)
        audio_bytes.seek(0)
        await message.reply_voice(voice=audio_bytes, caption="🔊 Озвучено!")
        use_cd(chat_id, user_id, 'voice')
    except Exception as e:
        await message.reply_text(f"❌ Ошибка озвучивания: {e}")

# ==================== /cat и /dog ====================
async def cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
    url = "https://api.thecatapi.com/v1/images/search"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data and "url" in data[0]:
            img_response = requests.get(data[0]["url"], timeout=10)
            await update.message.reply_photo(photo=img_response.content, caption="🐱 Мяу!")
        else:
            await update.message.reply_text("❌ Не удалось найти котика!")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def dog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
    url = "https://api.thedogapi.com/v1/images/search"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data and "url" in data[0]:
            img_response = requests.get(data[0]["url"], timeout=10)
            await update.message.reply_photo(photo=img_response.content, caption="🐶 Гав!")
        else:
            await update.message.reply_text("❌ Не удалось найти собачку!")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ==================== /top ====================
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    
    if chat_type not in ["group", "supergroup"]:
        await update.message.reply_text("📊 Топ доступен только в группах!")
        return
    
    stats = user_stats.get(chat_id, {})
    if not stats:
        await update.message.reply_text("📊 Пока нет активности в этом чате!")
        return
    
    sorted_users = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]
    
    top_text = "🏆 **Топ-10 активных пользователей:**\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for idx, (user_id, count) in enumerate(sorted_users):
        try:
            user = await context.bot.get_chat_member(chat_id, user_id)
            name = user.user.first_name
            if user.user.username:
                name = f"@{user.user.username}"
        except:
            name = f"ID: {user_id}"
        
        medal = medals[idx] if idx < len(medals) else f"{idx+1}."
        top_text += f"{medal} **{name}** — {count} действий\n"
    
    await update.message.reply_text(top_text, parse_mode="Markdown")

# ==================== ИГРЫ ====================
async def game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    message = update.message
    
    if chat_id in games and games[chat_id]["active"]:
        await message.reply_text(
            f"❌ Игра уже идёт! Её запустил пользователь.\n"
            f"Дождись окончания или попроси его завершить.",
            parse_mode="Markdown"
        )
        return
    
    kb = [
        [InlineKeyboardButton("🎯 Угадай число", callback_data=f"game_start:guess:{user_id}")],
        [InlineKeyboardButton("✂️ Камень-ножницы-бумага", callback_data=f"game_start:rps:{user_id}")],
        [InlineKeyboardButton("🧠 Викторина", callback_data=f"game_start:quiz:{user_id}")],
        [InlineKeyboardButton("🛑 Завершить игру", callback_data=f"game_stop:{user_id}")],
    ]
    await message.reply_text(
        "🎮 **Выбери игру:**\n\n"
        "• Угадай число — я загадаю, ты угадываешь\n"
        "• Камень-ножницы-бумага — игра с ботом\n"
        "• Викторина — ответь на вопрос\n\n"
        "📝 Для ответа используй: `/answer`",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    data_parts = query.data.split(":")
    action = data_parts[0]
    game_type = data_parts[1] if len(data_parts) > 1 else None
    initiator_id = int(data_parts[2]) if len(data_parts) > 2 else None
    
    if action == "game_stop":
        if chat_id in games and games[chat_id]["active"]:
            if games[chat_id]["user_id"] != user_id:
                await query.edit_message_text("❌ Только создатель игры может её завершить!")
                return
            games[chat_id]["active"] = False
            if chat_id in game_timers:
                game_timers[chat_id].cancel()
                del game_timers[chat_id]
            await query.edit_message_text("🛑 Игра завершена!")
        else:
            await query.edit_message_text("❌ Активной игры нет!")
        return
    
    if action == "game_start":
        if chat_id in games and games[chat_id]["active"]:
            await query.edit_message_text("❌ Игра уже идёт в этом чате!")
            return
        
        if initiator_id != user_id:
            await query.edit_message_text("❌ Только создатель игры может её запустить!")
            return
        
        games[chat_id] = {
            "user_id": user_id,
            "type": game_type,
            "active": True,
            "data": {}
        }
        
        if chat_id in game_timers:
            game_timers[chat_id].cancel()
            del game_timers[chat_id]
        task = asyncio.create_task(auto_end_game(chat_id, context))
        game_timers[chat_id] = task
        
        if game_type == "guess":
            number = random.randint(1, 100)
            games[chat_id]["data"]["number"] = number
            games[chat_id]["data"]["tries"] = 0
            games[chat_id]["data"]["users"] = set()
            kb = [[InlineKeyboardButton("🛑 Завершить игру", callback_data=f"game_stop:{user_id}")]]
            await query.edit_message_text(
                f"🎯 **Игра началась!** (Создатель: @{query.from_user.username or query.from_user.first_name})\n\n"
                f"Я загадал число от 1 до 100.\n"
                f"Напиши: `/answer 50` (подставь своё число)\n"
                f"Чтобы завершить игру — нажми кнопку ниже.",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="Markdown"
            )
        
        elif game_type == "rps":
            games[chat_id]["data"]["winner"] = None
            kb = [
                [InlineKeyboardButton("🪨 Камень", callback_data=f"game_rps:камень:{user_id}")],
                [InlineKeyboardButton("✂️ Ножницы", callback_data=f"game_rps:ножницы:{user_id}")],
                [InlineKeyboardButton("📄 Бумага", callback_data=f"game_rps:бумага:{user_id}")],
                [InlineKeyboardButton("🛑 Завершить игру", callback_data=f"game_stop:{user_id}")],
            ]
            await query.edit_message_text(
                f"✂️ **Камень-ножницы-бумага!** (Создатель: @{query.from_user.username or query.from_user.first_name})\n\n"
                f"Выбери свой ход:",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="Markdown"
            )
        
        elif game_type == "quiz":
            questions = [
                {"question": "Сколько планет в Солнечной системе?", "answer": "8"},
                {"question": "Какой язык программирования самый популярный?", "answer": "python"},
                {"question": "Столица Франции?", "answer": "париж"},
                {"question": "Сколько дней в феврале в високосный год?", "answer": "29"},
                {"question": "Как называется самый большой океан?", "answer": "тихий"},
                {"question": "Сколько цветов в радуге?", "answer": "7"},
                {"question": "Какой год считается началом Второй мировой войны?", "answer": "1939"},
            ]
            q = random.choice(questions)
            games[chat_id]["data"]["question"] = q["question"]
            games[chat_id]["data"]["answer"] = q["answer"].lower()
            games[chat_id]["data"]["answered"] = False
            kb = [[InlineKeyboardButton("🛑 Завершить игру", callback_data=f"game_stop:{user_id}")]]
            await query.edit_message_text(
                f"🧠 **Викторина!** (Создатель: @{query.from_user.username or query.from_user.first_name})\n\n"
                f"❓ {q['question']}\n\n"
                f"Напиши: `/answer {q['answer']}` (подставь свой ответ)\n"
                f"Чтобы завершить игру — нажми кнопку ниже.",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="Markdown"
            )

async def game_rps_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    data_parts = query.data.split(":")
    choice = data_parts[1]
    initiator_id = int(data_parts[2]) if len(data_parts) > 2 else None
    
    if chat_id not in games or not games[chat_id]["active"]:
        await query.edit_message_text("❌ Игра уже завершена!")
        return
    
    if games[chat_id]["user_id"] != user_id:
        await query.edit_message_text("❌ Только создатель игры может играть!")
        return
    
    if games[chat_id]["type"] != "rps":
        await query.edit_message_text("❌ Это не камень-ножницы-бумага!")
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
    
    emojis = {"камень": "🪨", "ножницы": "✂️", "бумага": "📄"}
    
    kb = [[InlineKeyboardButton("🔄 Сыграть ещё раз", callback_data=f"game_start:rps:{user_id}")],
          [InlineKeyboardButton("🛑 Завершить игру", callback_data=f"game_stop:{user_id}")]]
    
    await query.edit_message_text(
        f"✂️ **Камень-ножницы-бумага!**\n\n"
        f"Ты: {emojis[choice]} {choice}\n"
        f"Бот: {emojis[bot_choice]} {bot_choice}\n\n"
        f"**{result}**",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

# ==================== /answer ====================
async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    message = update.message
    
    if chat_id not in games or not games[chat_id]["active"]:
        await message.reply_text("❌ Нет активной игры!")
        return
    
    game_data = games[chat_id]
    
    if game_data["user_id"] != user_id:
        await message.reply_text("❌ Только создатель игры может отвечать!")
        return
    
    answer_text = " ".join(context.args) if context.args else ""
    if not answer_text:
        await message.reply_text(
            "❌ Напиши ответ после команды!\n"
            "Примеры:\n"
            "`/answer 50` — для угадайки\n"
            "`/answer Париж` — для викторины",
            parse_mode="Markdown"
        )
        return
    
    if game_data["type"] == "guess":
        await handle_guess_answer(update, context, game_data, answer_text)
    elif game_data["type"] == "quiz":
        await handle_quiz_answer(update, context, game_data, answer_text)
    else:
        await message.reply_text("❌ Неизвестный тип игры!")

async def handle_guess_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, game_data, answer_text):
    message = update.message
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    try:
        guess = int(answer_text.strip())
    except:
        await message.reply_text("❌ Напиши число! Например: `/answer 50`", parse_mode="Markdown")
        return
    
    if guess < 1 or guess > 100:
        await message.reply_text("❌ Число должно быть от 1 до 100!")
        return
    
    game_data["data"]["tries"] += 1
    game_data["data"]["users"].add(user_id)
    number = game_data["data"]["number"]
    
    if guess == number:
        await message.reply_text(
            f"🎉 **Поздравляю!**\n"
            f"Ты угадал число **{number}**!\n"
            f"Попыток: {game_data['data']['tries']}\n\n"
            f"🔄 Сыграть ещё раз: `/game`",
            parse_mode="Markdown"
        )
        games[chat_id]["active"] = False
        if chat_id in game_timers:
            game_timers[chat_id].cancel()
            del game_timers[chat_id]
        return
    
    hint = "📈 Больше!" if guess < number else "📉 Меньше!"
    await message.reply_text(
        f"❌ Не угадал! **{hint}**\n"
        f"Попыток: {game_data['data']['tries']}",
        parse_mode="Markdown"
    )

async def handle_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, game_data, answer_text):
    message = update.message
    chat_id = update.effective_chat.id
    
    if game_data["data"].get("answered", False):
        await message.reply_text("❌ Ты уже отвечал на этот вопрос! Начни новую игру.")
        return
    
    user_answer = answer_text.strip().lower()
    correct_answer = game_data["data"]["answer"]
    
    if user_answer == correct_answer:
        await message.reply_text(
            f"🎉 **Правильно!**\n"
            f"Ответ: {correct_answer}\n\n"
            f"🔄 Сыграть ещё раз: `/game`",
            parse_mode="Markdown"
        )
        games[chat_id]["active"] = False
        if chat_id in game_timers:
            game_timers[chat_id].cancel()
            del game_timers[chat_id]
    else:
        game_data["data"]["answered"] = True
        await message.reply_text(
            f"❌ **Неправильно!**\n"
            f"Правильный ответ: {correct_answer}\n\n"
            f"🔄 Сыграть ещё раз: `/game`",
            parse_mode="Markdown"
        )
        games[chat_id]["active"] = False
        if chat_id in game_timers:
            game_timers[chat_id].cancel()
            del game_timers[chat_id]

# ==================== ТРИГГЕРЫ ====================
async def handle_triggers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return
    
    text = message.text.strip()
    text_lower = text.lower()
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if "бугульма" in text_lower:
        save_chat_id(chat_id)
        add_activity(chat_id, user_id)
        cool, remain = check_cd(chat_id, user_id, 'folk')
        if cool:
            m, s = divmod(remain.seconds, 60)
            await message.reply_text(f"⏳ {m} мин {s} сек", quote=True)
            return
        if ALL_STICKERS:
            await message.reply_sticker(sticker=random.choice(ALL_STICKERS))
            use_cd(chat_id, user_id, 'folk')
        return
    
    if "литвин" in text_lower:
        save_chat_id(chat_id)
        add_activity(chat_id, user_id)
        cool, remain = check_cd(chat_id, user_id, 'litvin')
        if cool:
            m, s = divmod(remain.seconds, 60)
            await message.reply_text(f"⏳ {m} мин {s} сек", quote=True)
            return
        if litvin_stickers:
            await message.reply_sticker(sticker=random.choice(litvin_stickers))
            use_cd(chat_id, user_id, 'litvin')
        return
    
    if "бред" in text_lower:
        save_chat_id(chat_id)
        add_activity(chat_id, user_id)
        cool, remain = check_cd(chat_id, user_id, 'bred')
        if cool:
            m, s = divmod(remain.seconds, 60)
            await message.reply_text(f"⏳ {m} мин {s} сек", quote=True)
            return
        if bred_stickers:
            await message.reply_sticker(sticker=random.choice(bred_stickers))
            use_cd(chat_id, user_id, 'bred')
        return
    
    if text_lower == "мой факт":
        save_chat_id(chat_id)
        add_activity(chat_id, user_id)
        fact = random.choice(FACTS)
        user = update.effective_user
        await message.reply_text(
            f"🧠 **Факт о тебе, {user.first_name}:**\n\n{fact}",
            parse_mode="Markdown"
        )
        return
    
    if text_lower in ["моё животное", "мое животное"]:
        save_chat_id(chat_id)
        add_activity(chat_id, user_id)
        animal_data = random.choice(ANIMALS)
        await message.reply_text(
            f"🐾 **Ты — {animal_data['name']}!**\n\n{animal_data['emoji']} {animal_data['description']}",
            parse_mode="Markdown"
        )
        return
    
    if text in ["п", "П", "p", "P"]:
        save_chat_id(chat_id)
        add_activity(chat_id, user_id)
        await message.reply_text("п")
        return

# ==================== КУЛДАУНЫ ====================
async def cooldown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    add_activity(update.effective_chat.id, update.effective_user.id)
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group", "supergroup"):
        return
    try:
        admins = await context.bot.get_chat_administrators(chat.id)
        owner = next((a for a in admins if a.status == ChatMemberStatus.OWNER), None)
        if not owner or user.id != owner.user.id:
            await update.message.reply_text("Только создатель группы.")
            return
    except:
        await update.message.reply_text("Бот должен быть админом.")
        return
    f, l, b, s, v = get_cd(chat.id, 'folk'), get_cd(chat.id, 'litvin'), get_cd(chat.id, 'bred'), get_cd(chat.id, 'search'), get_cd(chat.id, 'voice')
    kb = [
        [InlineKeyboardButton(f"Folk ({f}с)", callback_data="cd:folk")],
        [InlineKeyboardButton(f"Litvin ({l}с)", callback_data="cd:litvin")],
        [InlineKeyboardButton(f"Bred ({b}с)", callback_data="cd:bred")],
        [InlineKeyboardButton(f"Search ({s}с)", callback_data="cd:search")],
        [InlineKeyboardButton(f"Voice ({v}с)", callback_data="cd:voice")],
    ]
    await update.message.reply_text(
        f"⚙️ Кулдауны:\n/folk: {f}с\n/litvin: {l}с\n/bred: {b}с\n/search: {s}с\n/voice: {v}с\n\nВыбери команду:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def cd_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    chat_id, user = q.message.chat_id, q.from_user
    cmd = q.data.split(":")[1]
    pending_cooldown_input[(chat_id, user.id)] = cmd
    await q.answer()
    await q.edit_message_text(f"Введи новый кулдаун для /{cmd} (0-3600 сек):")

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

# ==================== ИНЛАЙН ====================
async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    if not ALL_STICKERS:
        await update.inline_query.answer([], cache_time=0)
        return
    sid = random.choice(ALL_STICKERS)
    await update.inline_query.answer([
        InlineQueryResultCachedSticker(id=str(random.randint(100000, 999999)), sticker_file_id=sid)
    ], cache_time=0)

# ==================== FLASK ====================
flask_app = Flask(__name__)

@flask_app.route('/getUserGroups')
def get_user_groups():
    uid = request.args.get('user_id')
    if not uid:
        return jsonify({"ok": False})
    return jsonify({"ok": True, "result": user_groups.get(int(uid), [])})

def run_flask():
    flask_app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

# ==================== ЗАПУСК ====================
def main():
    load_user_groups()
    load_stats()
    download_font()
    
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("folk", folk))
    app.add_handler(CommandHandler("litvin", litvin))
    app.add_handler(CommandHandler("bred", bred))
    app.add_handler(CommandHandler("sosat", sosat))
    app.add_handler(CommandHandler("zabava", zabava))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("voice", voice))
    app.add_handler(CommandHandler("cat", cat))
    app.add_handler(CommandHandler("dog", dog))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("game", game))
    app.add_handler(CommandHandler("answer", answer))
    app.add_handler(CommandHandler("cooldown", cooldown_cmd))
    app.add_handler(CommandHandler("factme", factme))
    app.add_handler(CommandHandler("animal", animal))
    app.add_handler(CommandHandler("chats", chats))
    app.add_handler(CommandHandler("go", go))
    app.add_handler(CommandHandler("donate", donate))
    app.add_handler(CommandHandler("donates", donates))
    app.add_handler(CommandHandler("donate_broadcast", donate_broadcast))
    app.add_handler(CommandHandler("cancel", cancel_broadcast))
    app.add_handler(CommandHandler("spin", spin))
    app.add_handler(CommandHandler("offer", offer))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_triggers))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, payment_successful))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(CallbackQueryHandler(cd_button, pattern="^cd:"))
    app.add_handler(CallbackQueryHandler(game_callback, pattern="^game_start:"))
    app.add_handler(CallbackQueryHandler(game_callback, pattern="^game_stop:"))
    app.add_handler(CallbackQueryHandler(game_rps_callback, pattern="^game_rps:"))
    app.add_handler(CallbackQueryHandler(donate_callback, pattern="^donate_"))
    app.add_handler(CallbackQueryHandler(broadcast_all_callback, pattern="^broadcast_all$"))
    app.add_handler(CallbackQueryHandler(offer_callback, pattern="^offer_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.User(ADMIN_ID), handle_broadcast_all_input))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cd_input))

    threading.Thread(target=run_flask, daemon=True).start()
    logging.info(f"Бот запущен! Стикеров: folk={len(ALL_STICKERS)} litvin={len(litvin_stickers)} bred={len(bred_stickers)}")
    app.run_polling()

if __name__ == "__main__":
    main()
