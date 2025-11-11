import os
import logging
import sqlite3
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

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

# Создаем бота
bot = telebot.TeleBot(TOKEN)

# ================== GOOGLE CALENDAR ==================
def get_google_calendar_service():
    """Получаем сервис для работы с Google Calendar"""
    try:
        SCOPES = ['https://www.googleapis.com/auth/calendar']
        creds = None
        
        # Проверяем наличие файла credentials
        if os.getenv("GOOGLE_CREDENTIALS_JSON"):
    creds_data = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
    with open("credentials.json", "w") as f:
        json.dump(creds_data, f)
    print("✅ credentials.json создан из переменной окружения")
elif not os.path.exists(GOOGLE_CREDENTIALS_FILE):
    print(f"❌ Файл {GOOGLE_CREDENTIALS_FILE} не найден!")
    return None

        print(f"✅ Файл {GOOGLE_CREDENTIALS_FILE} найден")
        
        # Файл token.json хранит токены доступа пользователя
        if os.path.exists(GOOGLE_TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)
        
        # Если нет валидных учетных данных, запросим у пользователя авторизацию
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                print("🔑 Запускаю авторизацию Google Calendar...")
                flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=8081)
            
            # Сохраняем учетные данные для следующего запуска
            with open(GOOGLE_TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())

        service = build('calendar', 'v3', credentials=creds)
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
            'description': f'Создано через Telegram бота',
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': TIMEZONE,
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': TIMEZONE,
            },
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
    """Создаем таблицу для задач"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Создаем таблицу с правильной структурой
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
    print("✅ База данных создана")

def add_task(user_id, description, task_datetime, google_event_id=None):
    """Добавляем задачу в базу"""
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
    """Получаем задачи пользователя"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, description, datetime, google_event_id FROM tasks WHERE user_id=? AND datetime > ? ORDER BY datetime",
        (user_id, datetime.now().isoformat())
    )
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def delete_task(task_id, user_id):
    """Удаляем задачу"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Получаем google_event_id перед удалением
    cursor.execute("SELECT google_event_id FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
    result = cursor.fetchone()
    google_event_id = result[0] if result else None
    
    cursor.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
    conn.commit()
    conn.close()
    
    # Удаляем из Google Calendar если есть
    if google_event_id:
        delete_google_event(google_event_id)
    
    return True

def get_task_by_id(task_id, user_id):
    """Получаем задачу по ID"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, description, datetime, google_event_id FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
    task = cursor.fetchone()
    conn.close()
    return task

# ================== УМНЫЙ ПАРСИНГ ДАТ ==================
def parse_datetime(date_str, time_str):
    """
    Умный парсинг дат и времени
    """
    try:
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        
        # Парсим время
        time_str = time_str.replace('.', ':')
        if ':' not in time_str:
            time_str += ':00'
        
        try:
            time_obj = datetime.strptime(time_str, "%H:%M").time()
        except:
            raise ValueError("Неверный формат времени. Используй: 9.00 или 17.30")
        
        date_str = date_str.lower().strip()
        
        # Дни недели
        weekdays = {
            "пн": 0, "понедельник": 0,
            "вт": 1, "вторник": 1, 
            "ср": 2, "среда": 2,
            "чт": 3, "четверг": 3,
            "пт": 4, "пятница": 4,
            "сб": 5, "суббота": 5,
            "вс": 6, "воскресенье": 6
        }
        
        if date_str in weekdays:
            target_weekday = weekdays[date_str]
            days_ahead = target_weekday - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target_date = (now + timedelta(days=days_ahead)).date()
        
        elif '.' in date_str:
            try:
                day, month = date_str.split('.')
                day = int(day.strip())
                month = int(month.strip())
                year = now.year
                
                if month < now.month or (month == now.month and day < now.day):
                    year += 1
                    
                target_date = datetime(year, month, day).date()
            except:
                raise ValueError("Неверный формат даты. Используй: 9.12")
        
        else:
            raise ValueError("Неизвестный формат даты")
        
        result = datetime.combine(target_date, time_obj)
        result = tz.localize(result)
        return result
        
    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")
        raise ValueError(f"Не удалось распознать: {date_str} {time_str}")

# ================== КОМАНДЫ БОТА ==================
@bot.message_handler(commands=['start'])
def start_command(message):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("/add"), KeyboardButton("/list"))
    keyboard.add(KeyboardButton("/today"), KeyboardButton("/delete"))
    keyboard.add(KeyboardButton("/help"))
    
    has_calendar = "✅" if os.path.exists(GOOGLE_CREDENTIALS_FILE) else "❌"
    
    bot.reply_to(message, 
        "👋 Привет! Я бот для управления задачами.\n\n"
        f"📅 Google Calendar: {has_calendar}\n\n"
        "📋 Используй кнопки или команды:",
        reply_markup=keyboard
    )

@bot.message_handler(commands=['help'])
def help_command(message):
    has_calendar = "✅ подключен" if os.path.exists(GOOGLE_CREDENTIALS_FILE) else "❌ не настроен"
    
    bot.reply_to(message,
        "📋 Команды:\n"
        "/add описание дата время - Добавить задачу\n"
        "/list - Показать все задачи\n" 
        "/today - Задачи на сегодня\n"
        "/delete - Удалить задачу\n\n"
        "📅 Google Calendar: " + has_calendar + "\n\n"
        "📅 Примеры:\n"
        "/add Встреча пн 14.30\n"
        "/add Учеба 9.12 9.00"
    )

@bot.message_handler(commands=['add'])
def add_command(message):
    try:
        parts = message.text.split(' ', 3)
        
        if len(parts) < 4:
            bot.reply_to(message,
                "❌ Используй: /add описание дата время\n\n"
                "📅 Примеры:\n"
                "/add Встреча пн 14.30\n"
                "/add Учеба 9.12 9.00"
            )
            return
        
        description = parts[1]
        date_str = parts[2]
        time_str = parts[3]
        
        try:
            parsed_datetime = parse_datetime(date_str, time_str)
        except ValueError as e:
            bot.reply_to(message, f"❌ {str(e)}")
            return
        
        # Создаем событие в Google Calendar
        google_event_id = None
        if os.path.exists(GOOGLE_CREDENTIALS_FILE):
            end_time = parsed_datetime + timedelta(hours=1)
            google_event_id = create_google_event(description, parsed_datetime, end_time)
        
        # Добавляем в базу
        task_id = add_task(message.from_user.id, description, parsed_datetime.isoformat(), google_event_id)
        
        response = f"✅ Задача добавлена!\n\n📝 {description}\n🕐 {parsed_datetime.strftime('%d.%m.%Y в %H:%M')}\nID: {task_id}"
        
        if google_event_id:
            response += "\n📅 Добавлено в Google Calendar"
        elif os.path.exists(GOOGLE_CREDENTIALS_FILE):
            response += "\n⚠️ Не удалось добавить в Google Calendar"
        else:
            response += "\nℹ️ Google Calendar не настроен"
        
        bot.reply_to(message, response)
        
    except Exception as e:
        logger.error(f"Ошибка добавления задачи: {e}")
        bot.reply_to(message, "❌ Ошибка при добавлении задачи")

@bot.message_handler(commands=['list'])
def list_command(message):
    try:
        tasks = get_tasks(message.from_user.id)
        
        if not tasks:
            bot.reply_to(message, "📭 У тебя пока нет задач")
            return
        
        response = "📋 Твои задачи:\n\n"
        for task_id, description, dt_str, google_event_id in tasks:
            dt = datetime.fromisoformat(dt_str)
            calendar_icon = " 📅" if google_event_id else ""
            response += f"#{task_id} - {description}{calendar_icon}\n"
            response += f"   🕐 {dt.strftime('%d.%m.%Y %H:%M')}\n\n"
        
        response += "🗑 Используй /delete номер для удаления"
        bot.reply_to(message, response)
        
    except Exception as e:
        logger.error(f"Ошибка получения задач: {e}")
        bot.reply_to(message, "❌ Ошибка при получении задач")

@bot.message_handler(commands=['today'])
def today_command(message):
    try:
        tasks = get_tasks(message.from_user.id)
        
        if not tasks:
            bot.reply_to(message, "📭 На сегодня задач нет!")
            return
        
        tz = pytz.timezone(TIMEZONE)
        today = datetime.now(tz).date()
        
        today_tasks = []
        for task in tasks:
            task_id, description, dt_str, google_event_id = task
            dt = datetime.fromisoformat(dt_str)
            if dt.date() == today:
                today_tasks.append(task)
        
        if not today_tasks:
            bot.reply_to(message, "🎉 На сегодня задач нет!")
            return
        
        response = f"📅 Задачи на сегодня ({today.strftime('%d.%m.%Y')}):\n\n"
        for task_id, description, dt_str, google_event_id in today_tasks:
            dt = datetime.fromisoformat(dt_str)
            calendar_icon = " 📅" if google_event_id else ""
            response += f"#{task_id} - {description}{calendar_icon}\n"
            response += f"   🕐 {dt.strftime('%H:%M')}\n\n"
        
        bot.reply_to(message, response)
        
    except Exception as e:
        logger.error(f"Ошибка получения задач на сегодня: {e}")
        bot.reply_to(message, "❌ Ошибка при получении задач")

@bot.message_handler(commands=['delete'])
def delete_command(message):
    try:
        parts = message.text.split(' ', 1)
        
        if len(parts) == 1:
            tasks = get_tasks(message.from_user.id)
            
            if not tasks:
                bot.reply_to(message, "📭 Нет задач для удаления")
                return
            
            response = "🗑 Выбери задачу для удаления:\n\n"
            for task_id, description, dt_str, google_event_id in tasks[:10]:
                dt = datetime.fromisoformat(dt_str)
                calendar_icon = " 📅" if google_event_id else ""
                response += f"/delete_{task_id} - {description}{calendar_icon}\n"
                response += f"   {dt.strftime('%d.%m.%Y %H:%M')}\n\n"
            
            response += "Или используй: /delete номер"
            bot.reply_to(message, response)
            return
        
        try:
            task_id = int(parts[1])
        except ValueError:
            bot.reply_to(message, "❌ ID задачи должен быть числом!")
            return
        
        task = get_task_by_id(task_id, message.from_user.id)
        if not task:
            bot.reply_to(message, "❌ Задача не найдена!")
            return
        
        success = delete_task(task_id, message.from_user.id)
        
        if success:
            bot.reply_to(message, f"✅ Задача #{task_id} удалена из бота и Google Calendar!")
        else:
            bot.reply_to(message, "❌ Ошибка при удалении задачи")
            
    except Exception as e:
        logger.error(f"Ошибка удаления задачи: {e}")
        bot.reply_to(message, "❌ Ошибка при удалении задачи")

@bot.message_handler(func=lambda message: message.text.startswith('/delete_'))
def delete_button_handler(message):
    try:
        task_id = int(message.text.replace('/delete_', ''))
        
        task = get_task_by_id(task_id, message.from_user.id)
        if not task:
            bot.reply_to(message, "❌ Задача не найдена!")
            return
        
        success = delete_task(task_id, message.from_user.id)
        
        if success:
            bot.reply_to(message, f"✅ Задача #{task_id} удалена из бота и Google Calendar!")
        else:
            bot.reply_to(message, "❌ Ошибка при удалении задачи")
            
    except ValueError:
        bot.reply_to(message, "❌ Неверный формат команды")
    except Exception as e:
        logger.error(f"Ошибка удаления через кнопку: {e}")
        bot.reply_to(message, "❌ Ошибка при удалении задачи")

# ================== ЗАПУСК ==================
if __name__ == "__main__":
    init_db()
    print("✅ База данных готова")
    
    if os.path.exists(GOOGLE_CREDENTIALS_FILE):
        print(f"✅ Google Calendar настроен ({GOOGLE_CREDENTIALS_FILE})")
    else:
        print(f"ℹ️ Google Calendar не настроен (файл {GOOGLE_CREDENTIALS_FILE} не найден)")
    
    print("✅ Бот запущен! Ctrl+C для остановки")
from flask import Flask, request

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def webhook():
    if request.method == "POST":
        update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
        bot.process_new_updates([update])
        return "OK", 200
    else:
        return "Bot is running!", 200

if __name__ == "__main__":
    import os
    import logging

    logging.basicConfig(level=logging.INFO)
    init_db()
    print("✅ База данных готова")

    # Настройка Webhook
    TOKEN = os.getenv("TELEGRAM_TOKEN")
    RENDER_URL = os.getenv("RENDER_URL")  # например https://vibe-bot.onrender.com
    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_URL}")

    print(f"🌐 Webhook установлен: {RENDER_URL}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
