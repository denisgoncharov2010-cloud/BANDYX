import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.api import router, set_bot

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
PORT = int(os.getenv("PORT", "8000"))

dp = Dispatcher()

@dp.message(CommandStart())
async def start(message: Message):
    if not WEBAPP_URL or "your-domain" in WEBAPP_URL:
        await message.answer(
            "Добро пожаловать в BANDYX!\n\n"
            "Сначала настройте WEBAPP_URL в .env и разместите приложение на HTTPS. "
            "После этого кнопка открытия фэнтези-поля появится здесь."
        )
        return
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Открыть BANDYX", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True
    )
    await message.answer(
        "🏑 Добро пожаловать в BANDYX!\n"
        "Собери состав из 11 игроков в бюджете 225 000 и соревнуйся в рейтингах.",
        reply_markup=keyboard
    )

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "BANDYX — фэнтези по хоккею с мячом.\n"
        "/start — открыть приложение\n"
        "Состав: 3 нападающих, 4 полузащитника, 3 защитника и вратарь.\n"
        "Бюджет на тур: 225 000."
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="BANDYX API", lifespan=lifespan)
app.include_router(router)
Path("uploads").mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")

async def run_bot():
    if not BOT_TOKEN:
        raise RuntimeError("Укажите BOT_TOKEN в файле .env")
    bot = Bot(BOT_TOKEN)
    set_bot(bot)
    await dp.start_polling(bot)

async def run_server():
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    await asyncio.gather(run_server(), run_bot())

if __name__ == "__main__":
    asyncio.run(main())
