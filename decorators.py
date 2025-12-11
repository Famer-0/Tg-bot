from functools import wraps
from config import ADMIN_ID
from telegram import Update
from telegram.ext import ContextTypes

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
