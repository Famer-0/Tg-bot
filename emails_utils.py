import smtplib
from email.message import EmailMessage
import logging
from config import SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, FROM_EMAIL
from db import get_courses
import asyncio

logger = logging.getLogger(__name__)

def smtp_configured():
    return all([SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, FROM_EMAIL])

async def send_confirmation_email(to_email, course_code):
    COURSES = await get_courses()
    course_name = COURSES.get(course_code, course_code)

    if not smtp_configured():
        logger.warning("SMTP настройки не полностью заданы")
        return

    msg = EmailMessage()
    msg.set_content(f"""
🎉 Поздравляем с регистрацией на курс {course_name}!
Ваша регистрация успешно подтверждена.
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
