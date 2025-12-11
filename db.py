import aiosqlite
import asyncio

DB_PATH = "registrations.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
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
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_user_email 
            ON users(telegram_id, email)
        """)
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_user_course 
            ON users(telegram_id, course)
        """)
        # Добавление дефолтных курсов
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

async def get_courses():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT code, name FROM courses") as cursor:
            return dict(await cursor.fetchall())

async def get_registered_courses(telegram_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT course FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            return [row[0] for row in await cursor.fetchall()]

async def add_user(course, name, telegram_id, email):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (course, name, telegram_id, email) VALUES (?, ?, ?, ?)",
            (course, name, telegram_id, email)
        )
        await db.commit()
