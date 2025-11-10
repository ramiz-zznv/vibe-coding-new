import os
import logging
import sqlite3
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Updater, CommandHandler, CallbackContext

# ================== НАСТРОЙКИ ==================
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_PATH = os.getenv("DATABASE_PATH", "tasks.db")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== БАЗА ДАННЫХ ==================
def init_db():
    """Инициализация базы данных SQLite"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            description TEXT,
            datetime TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.commit()
        conn.close()
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")

def add_task(user_id: int, description: str, dt: datetime):
    """Добавление задачи в базу данных"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tasks (user_id, description, datetime) VALUES (?, ?, ?)",
            (user_id, description, dt.isoformat())
        )
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return task_id
    except Exception as e:
        logger.error(f"Ошибка добавления задачи: {e}")
        return None

def get_tasks(user_id: int):
    """Получение всех задач пользователя"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, description, datetime FROM tasks WHERE user_id=? AND datetime > ? ORDER BY datetime",
            (user_id, datetime.now().isoformat())
        )
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Ошибка получения задач: {e}")
        return []

def delete_task(task_id: int, user_id: int):
    """Удаление задачи по ID"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Ошибка удаления задачи: {e}")
        return False

# ================== ПРОСТОЙ ПАРСИНГ ДАТ ==================
def parse_datetime(date_str: str, time_str: str) -> datetime:
    """
    Простой парсинг дат. Поддерживает:
    - дни недели: пн/понедельник, вт/вторник, etc
    - даты: 9.12
    - время: 17.30
    """
    try:
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        
        # Парсим время (формат 17.30)
        time_str = time_str.replace('.', ':')
        if ':' not in time_str:
            time_str += ':00'
        
        try:
            time_obj = datetime.strptime(time_str, "%H:%M").time()
        except:
            raise ValueError("Неверный формат времени. Используйте: 9.00 или 17.30")
        
        date_str = date_str.lower().strip()
        
        # Дни недели (полные и сокращенные)
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
        
        # Даты в формате 9.12
        elif '.' in date_str:
            try:
                day, month = date_str.split('.')
                day = int(day.strip())
                month = int(month.strip())
                year = now.year
                # Если дата уже прошла в этом году, берем следующий год
                if month < now.month or (month == now.month and day < now.day):
                    year += 1
                target_date = datetime(year, month, day).date()
            except:
                raise ValueError("Неверный формат даты. Используйте: 9.12")
        
        else:
            raise ValueError("Неизвестный формат даты")
        
        # Собираем дату и время
        result = datetime.combine(target_date, time_obj)
        result = tz.localize(result)
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка парсинга даты: {e}")
        raise ValueError(f"Не удалось распознать дату: {date_str}")

# ================== КОМАНДЫ БОТА ==================
def start(update: Update, context: CallbackContext):
    """Обработчик команды /start"""
    try:
        keyboard = [
            [KeyboardButton("/add"), KeyboardButton("/list")],
            [KeyboardButton("/today"), KeyboardButton("/delete")],
            [KeyboardButton("/help")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        welcome_text = """
👋 Привет! Я бот для управления задачами.

📋 **Команды:**
/add - Добавить задачу
/list - Все задачи  
/today - Задачи на сегодня
/delete - Удалить задачу
/help - Помощь

📅 **Форматы дат:**
• пн/понедельник, вт/вторник...
• 9.12, 15.3

⏰ **Формат времени:**
• 9.00, 17.30, 14.15

**Пример:**
/add Встреча пн 14.30
/add Учеба 9.12 9.00
        """
        
        update.message.reply_text(welcome_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка в команде /start: {e}")
        update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

def help_command(update: Update, context: CallbackContext):
    """Обработчик команды /help"""
    help_text = """
📋 **Все команды:**

/add - Добавить задачу
Пример: /add Встреча пн 14.30

/list - Все задачи
/today - Задачи на сегодня  
/delete - Удалить задачу
/help - Помощь

📅 **Форматы дат:**
• пн, вт, ср... или понедельник, вторник...
• 9.12, 15.3

⏰ **Формат времени:**
• 9.00, 17.30, 14.15
        """
    update.message.reply_text(help_text)

def add_command(update: Update, context: CallbackContext):
    """Обработчик команды /add"""
    try:
        if not context.args or len(context.args) < 3:
            update.message.reply_text(
                "📝 **Добавление задачи**\n\n"
                "Используйте: /add описание дата время\n\n"
                "**Примеры:**\n"
                "/add Встреча пн 14.30\n"
                "/add Учеба 9.12 9.00\n"
                "/add Совещание вторник 17.30"
            )
            return

        # Разбираем аргументы
        args = context.args
        description = args[0]
        date_str = args[1]
        time_str = args[2]

        # Парсим дату и время
        try:
            parsed_datetime = parse_datetime(date_str, time_str)
        except ValueError as e:
            update.message.reply_text(f"❌ {str(e)}")
            return

        # Добавляем задачу в базу данных
        task_id = add_task(update.message.from_user.id, description, parsed_datetime)

        if task_id:
            response = f"✅ **Задача добавлена!**\n\n📝 {description}\n🕐 {parsed_datetime.strftime('%d.%m.%Y в %H:%M')}"
            update.message.reply_text(response)
        else:
            update.message.reply_text("❌ Ошибка при сохранении задачи")
        
    except Exception as e:
        logger.error(f"Ошибка в команде /add: {e}")
        update.message.reply_text("❌ Ошибка при добавлении задачи. Проверьте формат.")

def list_command(update: Update, context: CallbackContext):
    """Обработчик команды /list"""
    try:
        tasks = get_tasks(update.message.from_user.id)
        
        if not tasks:
            update.message.reply_text("📭 У вас пока нет предстоящих задач.")
            return

        message = "📋 **Ваши задачи:**\n\n"
        for task_id, description, dt_str in tasks:
            dt = datetime.fromisoformat(dt_str)
            message += f"{task_id:2d}. {description}\n   🕐 {dt.strftime('%d.%m.%Y %H:%M')}\n\n"

        message += "\nИспользуйте /delete номер чтобы удалить задачу"
        update.message.reply_text(message)
        
    except Exception as e:
        logger.error(f"Ошибка в команде /list: {e}")
        update.message.reply_text("❌ Ошибка при получении задач.")

def today_command(update: Update, context: CallbackContext):
    """Обработчик команды /today"""
    try:
        tasks = get_tasks(update.message.from_user.id)
        
        if not tasks:
            update.message.reply_text("📭 На сегодня задач нет!")
            return

        tz = pytz.timezone(TIMEZONE)
        today = datetime.now(tz).date()
        
        today_tasks = []
        for task in tasks:
            task_id, description, dt_str = task
            dt = datetime.fromisoformat(dt_str)
            if dt.date() == today:
                today_tasks.append(task)

        if not today_tasks:
            update.message.reply_text("🎉 На сегодня задач нет!")
            return

        today_str = today.strftime('%d.%m.%Y')
        message = f"📅 **Задачи на сегодня ({today_str}):**\n\n"
        
        for task_id, description, dt_str in today_tasks:
            dt = datetime.fromisoformat(dt_str)
            time_str = dt.strftime('%H:%M')
            message += f"{task_id:2d}. {description}\n   🕐 {time_str}\n\n"

        update.message.reply_text(message)
        
    except Exception as e:
        logger.error(f"Ошибка в команде /today: {e}")
        update.message.reply_text("❌ Ошибка при получении задач на сегодня.")

def delete_command(update: Update, context: CallbackContext):
    """Обработчик команды /delete"""
    try:
        if not context.args:
            # Показываем список задач для удаления
            tasks = get_tasks(update.message.from_user.id)
            
            if not tasks:
                update.message.reply_text("📭 Нет задач для удаления.")
                return

            message = "🗑 **Выберите задачу для удаления:**\n\n"
            for task_id, description, dt_str in tasks[:10]:
                dt = datetime.fromisoformat(dt_str)
                message += f"/{task_id} - {description}\n   {dt.strftime('%d.%m.%Y %H:%M')}\n\n"
            
            message += "Используйте /delete номер или нажмите на команду выше"
            update.message.reply_text(message)
            return

        try:
            task_id = int(context.args[0])
        except ValueError:
            update.message.reply_text("❌ ID задачи должен быть числом!")
            return

        # Удаляем задачу
        success = delete_task(task_id, update.message.from_user.id)
        
        if success:
            update.message.reply_text(f"✅ Задача {task_id} удалена!")
        else:
            update.message.reply_text("❌ Задача не найдена!")
            
    except Exception as e:
        logger.error(f"Ошибка в команде /delete: {e}")
        update.message.reply_text("❌ Ошибка при удалении задачи.")

# ================== ЗАПУСК БОТА ==================
def main():
    """Основная функция запуска бота"""
    try:
        # Инициализация базы данных
        init_db()
        
        # Создание updater
        updater = Updater(TOKEN, use_context=True)
        
        # Получаем dispatcher для регистрации обработчиков
        dp = updater.dispatcher
        
        # Добавление обработчиков команд
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("help", help_command))
        dp.add_handler(CommandHandler("add", add_command))
        dp.add_handler(CommandHandler("list", list_command))
        dp.add_handler(CommandHandler("today", today_command))
        dp.add_handler(CommandHandler("delete", delete_command))
        
        # Запуск бота
        updater.start_polling()
        logger.info("Бот запущен...")
        print("✅ Бот успешно запущен! Остановите его сочетанием клавиш Ctrl+C")
        
        # Ожидание остановки
        updater.idle()
        
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
        print(f"❌ Ошибка запуска: {e}")

if __name__ == "__main__":
    main()