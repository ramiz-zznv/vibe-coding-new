import os
import json
import logging
import sqlite3
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from flask import Flask, request

# Google Calendar imports
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

# ================== НАСТРОЙКИ ==================
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_PATH = os.getenv("DATABASE_PATH", "tasks.db")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS", "credentials.json")
GOOGLE_TOKEN_FILE = os.getenv("GOOGLE_TOKEN", "token.json")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== CREDENTIALS ДЛЯ RENDER ==================
if os.getenv("GOOGLE_CREDENTIALS_JSON"):
    try:
        creds_data = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
        with open(GOOGLE_CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            json.dump(creds_data, f, indent=2, ensure_ascii=False)
        print("✅ credentials.json создан из переменной окружения (Render)")
    except Exception as e:
        print(f"❌ Ошибка при создании credentials.json: {e}")
else:
    print("⚠️ GOOGLE_CREDENTIALS_JSON не найден, используется локальный файл (если есть)")

# ================== СОЗДАЕМ БОТА ==================
bot = telebot.TeleBot(TOKEN)

# ================== GOOGLE CALENDAR ==================
def get_google_calendar_service():
    """Получаем сервис для работы с Google Calendar"""
    try:
        SCOPES = ['https://www.googleapis.com/auth/calendar']
        creds = None

        if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
            print(f"❌ Файл {GOOGLE_CREDENTIALS_FILE} не найден!")
            return None

        if os.path.exists(GOOGLE_TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                print("🔑 Запускаю авторизацию Google Calendar...")
                flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=8081)
            with open(GOOGLE_TOKEN_FILE, "w") as token:
                token.write(creds.to_json())

        service = build("calendar", "v3", credentials=creds)
        print("✅ Сервис Google Calendar создан")
        return service

    except Exception as e:
        logger.error(f"Ошибка получения сервиса Google Calendar: {e}")
        return None

def create_google_event(description, start_time, end_time):
    """Создаем событие в Google Calendar"""
    try:
        service = get_google_calendar_service()
        if not service:
            return None

        event = {
            'summary': description,
            'description': 'Создано через Telegram бота',
            'start': {'dateTime': start_time.isoformat(), 'timeZone': TIMEZONE},
            'end': {'dateTime': end_time.isoformat(), 'timeZone': TIMEZONE},
        }

        event = service.events().insert(calendarId='primary', body=event).execute()
        logger.info(f'Событие создано в Google Calendar: {event.get("id")}')
        return event.get('id')

    except Exception as e:
        logger.error(f"Ошибка создания события в Google Calendar: {e}")
        return None

def delete_google_event(event_id):
    """Удаляем событие из Google Calendar"""
    try:
        service = get_google_calendar_service()
        if not service or not event_id:
            return False
        service.events().delete(calendarId='primary', eventId=event_id).execute()
        logger.info(f'Событие удалено из Google Calendar: {event_id}')
        return True
    except Exception as e:
        logger.error(f"Ошибка удаления события из Google Calendar: {e}")
        return False

# ================== БАЗА ДАННЫХ ==================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        description TEXT,
        datetime TEXT,
        google_event_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()
    print("✅ База данных готова")

def add_task(user_id, description, task_datetime, google_event_id=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tasks (user_id, description, datetime, google_event_id) VALUES (?, ?, ?, ?)",
        (user_id, description, task_datetime, google_event_id)
    )
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return task_id

def get_tasks(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, description, datetime, google_event_id FROM tasks WHERE user_id=? AND datetime > ? ORDER BY datetime",
        (user_id, datetime.now().isoformat())
    )
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def get_task_by_id(task_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, description, datetime, google_event_id FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
    task = cursor.fetchone()
    conn.close()
    return task

def delete_task(task_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT google_event_id FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
    result = cursor.fetchone()
    google_event_id = result[0] if result else None
    cursor.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
    conn.commit()
    conn.close()
    if google_event_id:
        delete_google_event(google_event_id)
    return True

# ================== ПАРСИНГ ДАТ ==================
def parse_datetime(date_str, time_str):
    try:
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        time_str = time_str.replace('.', ':')
        if ':' not in time_str:
            time_str += ':00'
        time_obj = datetime.strptime(time_str, "%H:%M").time()
        date_str = date_str.lower().strip()
        weekdays = {
            "пн": 0, "понедельник": 0, "вт": 1, "вторник": 1,
            "ср": 2, "среда": 2, "чт": 3, "четверг": 3,
            "пт": 4, "пятница": 4, "сб": 5, "суббота": 5, "вс": 6, "воскресенье": 6
        }
        if date_str in weekdays:
            target_weekday = weekdays[date_str]
            days_ahead = target_weekday - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target_date = (now + timedelta(days=days_ahead)).date()
        elif '.' in date_str:
            day, month = map(int, date_str.split('.'))
            year = now.year
            if month < now.month or (month == now.month and day < now.day):
                year += 1
            target_date = datetime(year, month, day).date()
        else:
            raise ValueError("Неверный формат даты")
        result = tz.localize(datetime.combine(target_date, time_obj))
        return result
    except Exception as e:
        raise ValueError(f"Не удалось распознать дату: {e}")

# ================== КОМАНДЫ БОТА ==================
@bot.message_handler(commands=['start'])
def start_command(message):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("/add"), KeyboardButton("/list"), KeyboardButton("/today"), KeyboardButton("/delete"), KeyboardButton("/help"))
    has_calendar = "✅" if os.path.exists(GOOGLE_CREDENTIALS_FILE) else "❌"
    bot.reply_to(message, f"👋 Привет! Я бот для задач.\n📅 Google Calendar: {has_calendar}", reply_markup=kb)

@bot.message_handler(commands=['help'])
def help_command(message):
    bot.reply_to(message, "📋 Команды:\n/add описание дата время\n/list\n/today\n/delete\n")

@bot.message_handler(commands=['add'])
def add_command(message):
    try:
        parts = message.text.split(' ', 3)
        if len(parts) < 4:
            bot.reply_to(message, "❌ Формат: /add описание дата время\nПример: /add Встреча пн 14.30")
            return
        description, date_str, time_str = parts[1], parts[2], parts[3]
        parsed_datetime = parse_datetime(date_str, time_str)
        end_time = parsed_datetime + timedelta(hours=1)
        google_event_id = create_google_event(description, parsed_datetime, end_time)
        task_id = add_task(message.from_user.id, description, parsed_datetime.isoformat(), google_event_id)
        resp = f"✅ Задача #{task_id} добавлена: {description}\n🕐 {parsed_datetime.strftime('%d.%m %H:%M')}"
        if google_event_id: resp += "\n📅 Добавлено в Google Calendar"
        bot.reply_to(message, resp)
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['list'])
def list_command(message):
    tasks = get_tasks(message.from_user.id)
    if not tasks:
        bot.reply_to(message, "📭 У тебя нет задач")
        return
    resp = "📋 Твои задачи:\n"
    for tid, desc, dt_str, gid in tasks:
        dt = datetime.fromisoformat(dt_str)
        resp += f"#{tid} - {desc} {'📅' if gid else ''}\n   {dt.strftime('%d.%m %H:%M')}\n"
    bot.reply_to(message, resp)

@bot.message_handler(commands=['delete'])
def delete_command(message):
    parts = message.text.split(' ', 1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ Укажи ID задачи: /delete 1")
        return
    try:
        tid = int(parts[1])
        delete_task(tid, message.from_user.id)
        bot.reply_to(message, f"✅ Задача #{tid} удалена.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

# ================== FLASK ДЛЯ RENDER ==================
app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def webhook():
    if request.method == "POST":
        update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
        bot.process_new_updates([update])
        return "OK", 200
    else:
        return "Bot is running!", 200

# ================== ЗАПУСК ==================
if __name__ == "__main__":
    init_db()
    if os.path.exists(GOOGLE_CREDENTIALS_FILE):
        print(f"✅ Google Calendar настроен ({GOOGLE_CREDENTIALS_FILE})")
    else:
        print(f"ℹ️ Google Calendar не найден")
    print("✅ Бот запущен!")

    RENDER_URL = os.getenv("RENDER_URL")
    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_URL}")
    print(f"🌐 Webhook установлен: {RENDER_URL}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
