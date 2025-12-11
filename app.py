import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, PicklePersistence
from config import BOT_TOKEN
from db import init_db
from handlers.start import start, process_course, process_name, process_email
from telegram.ext import CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler

app = Flask(__name__)

persistence = PicklePersistence(filepath="bot_data")
application = ApplicationBuilder().token(BOT_TOKEN).persistence(persistence).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        0: [CallbackQueryHandler(process_course, pattern=r'^course_')],
        1: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_name)],
        2: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_email)]
    },
    fallbacks=[]
)
application.add_handler(conv_handler)

@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put(update)
    return "OK"

async def main():
    await init_db()
    await application.bot.set_webhook("https://YOUR_DOMAIN/webhook")
    print("Бот готов и webhook установлен")

if __name__ == "__main__":
    asyncio.run(main())
    app.run(port=5000)
