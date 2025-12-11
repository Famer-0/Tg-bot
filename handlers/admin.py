from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler
from decorators import admin_only

ADMIN_MENU, ADMIN_ADD_CODE, ADMIN_ADD_NAME = range(3)

@admin_only
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Добавить курс", callback_data="add_course")]
    ]
    await update.message.reply_text("Меню администратора:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU
