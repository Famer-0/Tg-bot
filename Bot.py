import os
import re
import json
import logging
import smtplib
from email.message import EmailMessage
from functools import wraps
from flask import Flask, request

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    ConversationHandler,
    PicklePersistence
)
from telegram.ext.filters import TEXT

from aiosqlite import connect
import asyncio
from dotenv import load_dotenv

# --- Настройка логирования ---
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Загрузка переменных окружения ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com")

if not all([BOT_TOKEN, ADMIN_ID]):
    raise ValueError("Не все переменные окружения установлены")

# --- Flask сервер для webhook ---
app = Flask(__name__)

# --- FSM States (числа для ConversationHandler) ---
(
    COURSE, NAME, EMAIL, CONFIRM,
    ADMIN_MENU, ADMIN_ADD_CODE, ADMIN_ADD_NAME
) = range(7)

# --- Декоратор администратора ---
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            if update.message:
                await update.message.reply_text("🚫 Доступ запрещён")
            elif update.callback_query:
                await update.callback_query.answer("🚫 Доступ запрещён", show_alert=True)
            return
        return await func(update, context)
    return wrapper

# --- База данных ---
async def init_db():
    async with connect("registrations.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course TEXT,
                name TEXT,
                telegram_id INTEGER,
                email TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS courses (
                code TEXT PRIMARY KEY,
                name TEXT
            )
        """)
        await db.execute("DROP INDEX IF EXISTS idx_email")
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_user_email 
            ON users(telegram_id, email)
        """)
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_user_course 
            ON users(telegram_id, course)
        """)
        async with db.execute("SELECT COUNT(*) FROM courses") as cursor:
            count = (await cursor.fetchone())[0]
            if count == 0:
                default_courses = {
                    "html": "HTML & CSS для начинающих",
                    "js": "JavaScript с нуля",
                    "react": "React.js для создания интерфейсов"
                }
                for code, name in default_courses.items():
                    await db.execute("INSERT INTO courses (code, name) VALUES (?, ?)", (code, name))
        await db.commit()

async def get_registered_courses(telegram_id):
    async with connect("registrations.db") as db:
        async with db.execute("SELECT course FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            return [row[0] for row in await cursor.fetchall()]

async def get_courses_from_db():
    async with connect("registrations.db") as db:
        async with db.execute("SELECT code, name FROM courses") as cursor:
            return dict(await cursor.fetchall())

# --- Email ---
def smtp_configured():
    return all([
        os.getenv("SMTP_SERVER"),
        os.getenv("SMTP_PORT"),
        os.getenv("SMTP_USER"),
        os.getenv("SMTP_PASSWORD"),
        os.getenv("FROM_EMAIL")
    ])

async def send_confirmation_email(to_email, course_code):
    COURSES = await get_courses_from_db()
    course_name = COURSES.get(course_code, course_code)

    if not smtp_configured():
        logger.warning("SMTP настройки не полностью заданы")
        return

    SMTP_SERVER = os.getenv("SMTP_SERVER")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER = os.getenv("SMTP_USER")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)

    msg = EmailMessage()
    msg.set_content(f"""
🎉 Поздравляем с регистрацией на курс {course_name}!
Мы рады приветствовать вас в нашей школе программирования.
Ваша регистрация успешно подтверждена.
С уважением,
Команда школы программирования
""")
    msg['Subject'] = f"✅ Подтверждение регистрации на курс {course_name}"
    msg['From'] = FROM_EMAIL
    msg['To'] = to_email

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info(f"Отправлено подтверждение на email: {to_email}")
    except Exception as e:
        logger.error(f"Ошибка при отправке email: {e}", exc_info=True)

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    COURSES = await get_courses_from_db()
    course_buttons = [[InlineKeyboardButton(text=name, callback_data=f"course_{code}")] for code, name in COURSES.items()]
    webapp_button = [[InlineKeyboardButton(text="📱 Открыть мини-приложение", web_app=WebAppInfo(url=WEBAPP_URL))]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=course_buttons + webapp_button)
    await update.message.reply_text("👋 Добро пожаловать в нашу школу программирования!\nВыберите курс:", reply_markup=keyboard)
    return COURSE

async def process_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    COURSES = await get_courses_from_db()
    query = update.callback_query
    await query.answer()
    course_code = query.data.split("_")[1]
    if course_code not in COURSES:
        await query.answer("❌ Некорректный курс", show_alert=True)
        return COURSE
    telegram_id = query.from_user.id
    registered = await get_registered_courses(telegram_id)
    if course_code in registered:
        await query.answer(f"⚠️ Вы уже зарегистрированы на {COURSES[course_code]}", show_alert=True)
        return COURSE
    context.user_data['course'] = course_code
    await query.edit_message_text(f"📘 Вы выбрали курс: {COURSES[course_code]}\nВведите своё имя:")
    return NAME

async def process_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2 or len(name) > 50:
        await update.message.reply_text("❌ Имя должно быть от 2 до 50 символов")
        return NAME
    context.user_data['name'] = name
    COURSES = await get_courses_from_db()
    course_code = context.user_data['course']
    await update.message.reply_text(
        f"Вы ввели имя: {name}\n🔹 Курс: {COURSES[course_code]}\n\n✅ Подтвердите ввод",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(text="🔄 Изменить имя", callback_data="edit_name")],
            [InlineKeyboardButton(text="➡️ Продолжить", callback_data="confirm_name")]
        ])
    )
    return CONFIRM

async def edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("Введите новое имя:")
    return NAME

async def confirm_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("📧 Введите свой email для регистрации:")
    return EMAIL

async def process_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        await update.message.reply_text("❌ Неверный формат email")
        return EMAIL

    data = context.user_data
    telegram_id = update.message.from_user.id

    async with connect("registrations.db") as db:
        async with db.execute("SELECT * FROM users WHERE email = ? AND telegram_id != ?", (email, telegram_id)) as cursor:
            email_used_by_other = await cursor.fetchone()
        if email_used_by_other:
            await update.message.reply_text("❌ Эта почта уже используется другим пользователем")
            return EMAIL
        async with db.execute("SELECT * FROM users WHERE telegram_id = ? AND course = ?", (telegram_id, data['course'])) as cursor:
            existing_course = await cursor.fetchone()
        if existing_course:
            await update.message.reply_text("❌ Вы уже зарегистрированы на этот курс")
            return ConversationHandler.END
        await db.execute("INSERT INTO users (course, name, telegram_id, email) VALUES (?, ?, ?, ?)",
                         (data['course'], data['name'], telegram_id, email))
        await db.commit()

    await send_confirmation_email(email, data['course'])
    await update.message.reply_text("✅ Регистрация успешна!")
    return ConversationHandler.END

# --- Flask webhook endpoint ---
@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put(update)
    return "OK"

# --- Создание приложения PTB ---
persistence = PicklePersistence(filepath="bot_data")
application = ApplicationBuilder().token(BOT_TOKEN).persistence(persistence).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        COURSE: [CallbackQueryHandler(process_course, pattern=r'^course_')],
        NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, process_name),
            CallbackQueryHandler(edit_name, pattern="edit_name")
        ],
        CONFIRM: [CallbackQueryHandler(confirm_name, pattern="confirm_name")],
        EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_email)],
    },
    fallbacks=[]
)

application.add_handler(conv_handler)

# --- Инициализация базы данных ---
async def main():
    await init_db()
    # Настройка webhook (пример для хоста)
    await application.bot.set_webhook("https://YOUR_DOMAIN/webhook")
    logger.info("Бот готов и webhook установлен")

if __name__ == "__main__":
    asyncio.run(main())
    app.run(port=5000) import os
import re
import json
import logging
import smtplib
from email.message import EmailMessage
from functools import wraps
from flask import Flask, request

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    ConversationHandler,
    PicklePersistence
)
from telegram.ext.filters import TEXT

from aiosqlite import connect
import asyncio
from dotenv import load_dotenv

# --- Настройка логирования ---
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Загрузка переменных окружения ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com")

if not all([BOT_TOKEN, ADMIN_ID]):
    raise ValueError("Не все переменные окружения установлены")

# --- Flask сервер для webhook ---
app = Flask(__name__)

# --- FSM States (числа для ConversationHandler) ---
(
    COURSE, NAME, EMAIL, CONFIRM,
    ADMIN_MENU, ADMIN_ADD_CODE, ADMIN_ADD_NAME
) = range(7)

# --- Декоратор администратора ---
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            if update.message:
                await update.message.reply_text("🚫 Доступ запрещён")
            elif update.callback_query:
                await update.callback_query.answer("🚫 Доступ запрещён", show_alert=True)
            return
        return await func(update, context)
    return wrapper

# --- База данных ---
async def init_db():
    async with connect("registrations.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course TEXT,
                name TEXT,
                telegram_id INTEGER,
                email TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS courses (
                code TEXT PRIMARY KEY,
                name TEXT
            )
        """)
        await db.execute("DROP INDEX IF EXISTS idx_email")
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_user_email 
            ON users(telegram_id, email)
        """)
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_user_course 
            ON users(telegram_id, course)
        """)
        async with db.execute("SELECT COUNT(*) FROM courses") as cursor:
            count = (await cursor.fetchone())[0]
            if count == 0:
                default_courses = {
                    "html": "HTML & CSS для начинающих",
                    "js": "JavaScript с нуля",
                    "react": "React.js для создания интерфейсов"
                }
                for code, name in default_courses.items():
                    await db.execute("INSERT INTO courses (code, name) VALUES (?, ?)", (code, name))
        await db.commit()

async def get_registered_courses(telegram_id):
    async with connect("registrations.db") as db:
        async with db.execute("SELECT course FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            return [row[0] for row in await cursor.fetchall()]

async def get_courses_from_db():
    async with connect("registrations.db") as db:
        async with db.execute("SELECT code, name FROM courses") as cursor:
            return dict(await cursor.fetchall())

# --- Email ---
def smtp_configured():
    return all([
        os.getenv("SMTP_SERVER"),
        os.getenv("SMTP_PORT"),
        os.getenv("SMTP_USER"),
        os.getenv("SMTP_PASSWORD"),
        os.getenv("FROM_EMAIL")
    ])

async def send_confirmation_email(to_email, course_code):
    COURSES = await get_courses_from_db()
    course_name = COURSES.get(course_code, course_code)

    if not smtp_configured():
        logger.warning("SMTP настройки не полностью заданы")
        return

    SMTP_SERVER = os.getenv("SMTP_SERVER")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER = os.getenv("SMTP_USER")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)

    msg = EmailMessage()
    msg.set_content(f"""
🎉 Поздравляем с регистрацией на курс {course_name}!
Мы рады приветствовать вас в нашей школе программирования.
Ваша регистрация успешно подтверждена.
С уважением,
Команда школы программирования
""")
    msg['Subject'] = f"✅ Подтверждение регистрации на курс {course_name}"
    msg['From'] = FROM_EMAIL
    msg['To'] = to_email

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info(f"Отправлено подтверждение на email: {to_email}")
    except Exception as e:
        logger.error(f"Ошибка при отправке email: {e}", exc_info=True)

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    COURSES = await get_courses_from_db()
    course_buttons = [[InlineKeyboardButton(text=name, callback_data=f"course_{code}")] for code, name in COURSES.items()]
    webapp_button = [[InlineKeyboardButton(text="📱 Открыть мини-приложение", web_app=WebAppInfo(url=WEBAPP_URL))]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=course_buttons + webapp_button)
    await update.message.reply_text("👋 Добро пожаловать в нашу школу программирования!\nВыберите курс:", reply_markup=keyboard)
    return COURSE

async def process_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    COURSES = await get_courses_from_db()
    query = update.callback_query
    await query.answer()
    course_code = query.data.split("_")[1]
    if course_code not in COURSES:
        await query.answer("❌ Некорректный курс", show_alert=True)
        return COURSE
    telegram_id = query.from_user.id
    registered = await get_registered_courses(telegram_id)
    if course_code in registered:
        await query.answer(f"⚠️ Вы уже зарегистрированы на {COURSES[course_code]}", show_alert=True)
        return COURSE
    context.user_data['course'] = course_code
    await query.edit_message_text(f"📘 Вы выбрали курс: {COURSES[course_code]}\nВведите своё имя:")
    return NAME

async def process_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2 or len(name) > 50:
        await update.message.reply_text("❌ Имя должно быть от 2 до 50 символов")
        return NAME
    context.user_data['name'] = name
    COURSES = await get_courses_from_db()
    course_code = context.user_data['course']
    await update.message.reply_text(
        f"Вы ввели имя: {name}\n🔹 Курс: {COURSES[course_code]}\n\n✅ Подтвердите ввод",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(text="🔄 Изменить имя", callback_data="edit_name")],
            [InlineKeyboardButton(text="➡️ Продолжить", callback_data="confirm_name")]
        ])
    )
    return CONFIRM

async def edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("Введите новое имя:")
    return NAME

async def confirm_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("📧 Введите свой email для регистрации:")
    return EMAIL

async def process_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        await update.message.reply_text("❌ Неверный формат email")
        return EMAIL

    data = context.user_data
    telegram_id = update.message.from_user.id

    async with connect("registrations.db") as db:
        async with db.execute("SELECT * FROM users WHERE email = ? AND telegram_id != ?", (email, telegram_id)) as cursor:
            email_used_by_other = await cursor.fetchone()
        if email_used_by_other:
            await update.message.reply_text("❌ Эта почта уже используется другим пользователем")
            return EMAIL
        async with db.execute("SELECT * FROM users WHERE telegram_id = ? AND course = ?", (telegram_id, data['course'])) as cursor:
            existing_course = await cursor.fetchone()
        if existing_course:
            await update.message.reply_text("❌ Вы уже зарегистрированы на этот курс")
            return ConversationHandler.END
        await db.execute("INSERT INTO users (course, name, telegram_id, email) VALUES (?, ?, ?, ?)",
                         (data['course'], data['name'], telegram_id, email))
        await db.commit()

    await send_confirmation_email(email, data['course'])
    await update.message.reply_text("✅ Регистрация успешна!")
    return ConversationHandler.END

# --- Flask webhook endpoint ---
@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put(update)
    return "OK"

# --- Создание приложения PTB ---
persistence = PicklePersistence(filepath="bot_data")
application = ApplicationBuilder().token(BOT_TOKEN).persistence(persistence).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        COURSE: [CallbackQueryHandler(process_course, pattern=r'^course_')],
        NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, process_name),
            CallbackQueryHandler(edit_name, pattern="edit_name")
        ],
        CONFIRM: [CallbackQueryHandler(confirm_name, pattern="confirm_name")],
        EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_email)],
    },
    fallbacks=[]
)

application.add_handler(conv_handler)

# --- Инициализация базы данных ---
async def main():
    await init_db()
    # Настройка webhook (пример для хоста)
    await application.bot.set_webhook("https://YOUR_DOMAIN/webhook")
    logger.info("Бот готов и webhook установлен")

if __name__ == "__main__":
    asyncio.run(main())
    app.run(port=5000)
