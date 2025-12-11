from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from db import get_courses, get_registered_courses, add_user
from email_utils import send_confirmation_email

COURSE, NAME, CONFIRM, EMAIL = range(4)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    COURSES = await get_courses()
    buttons = [[InlineKeyboardButton(text=name, callback_data=f"course_{code}")] for code, name in COURSES.items()]
    keyboard = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Выберите курс:", reply_markup=keyboard)
    return COURSE

async def process_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    course_code = query.data.split("_")[1]
    COURSES = await get_courses()
    if course_code not in COURSES:
        await query.answer("❌ Некорректный курс", show_alert=True)
        return COURSE
    telegram_id = query.from_user.id
    registered = await get_registered_courses(telegram_id)
    if course_code in registered:
        await query.answer(f"⚠️ Вы уже зарегистрированы на {COURSES[course_code]}", show_alert=True)
        return COURSE
    context.user_data['course'] = course_code
    await query.edit_message_text(f"Вы выбрали курс {COURSES[course_code]}. Введите имя:")
    return NAME

async def process_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    context.user_data['name'] = name
    await update.message.reply_text("Введите email:")
    return EMAIL

async def process_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    data = context.user_data
    telegram_id = update.message.from_user.id
    await add_user(data['course'], data['name'], telegram_id, email)
    await send_confirmation_email(email, data['course'])
    await update.message.reply_text("✅ Регистрация успешна!")
    return ConversationHandler.END
