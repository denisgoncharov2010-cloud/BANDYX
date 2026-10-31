
import os
import hmac
import json
import hashlib
import urllib.parse
import time
import aiosqlite

from aiogram import Bot
from fastapi import (
    APIRouter, HTTPException, UploadFile, File,
    Header, Depends
)
from pydantic import BaseModel

DB_PATH = "bandyx.db"
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")

router = APIRouter()
bot = None

BUDGET_LIMIT = 225000

POSITION_LIMITS = {
    "forward": 3,
    "midfielder": 4,
    "defender": 3,
    "goalie": 1
}


def set_bot(value: Bot):
    global bot
    bot = value


def verify_admin(x_admin_secret: str | None = Header(default=None)):
    if not ADMIN_SECRET:
        raise HTTPException(503, "Пароль администратора не настроен")
    if not x_admin_secret or not hmac.compare_digest(
        x_admin_secret, ADMIN_SECRET
    ):
        raise HTTPException(403, "Нет доступа")


def verify_telegram(init_data: str | None):
    if not BOT_TOKEN:
        raise HTTPException(503, "Токен бота не настроен")

    if not init_data:
        raise HTTPException(401, "Откройте приложение через Telegram")

    try:
        data = dict(urllib.parse.parse_qsl(
            init_data, keep_blank_values=True
        ))
        received_hash = data.pop("hash")

        auth_date = int(data.get("auth_date", "0"))
        if time.time() - auth_date > 86400 or auth_date > time.time() + 60:
            raise ValueError("Срок авторизации истёк")

        check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(data.items())
        )

        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            raise ValueError("Неверная подпись")

        user = json.loads(data["user"])
        return user

    except Exception:
        raise HTTPException(401, "Не удалось подтвердить Telegram")


async def get_user(
    x_telegram_init_data: str | None = Header(default=None)
):
    user = verify_telegram(x_telegram_init_data)

    telegram_id = int(user["id"])
    username = user.get("username")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (telegram_id, username)
            VALUES (?, ?)
            ON CONFLICT(telegram_id)
            DO UPDATE SET username = excluded.username
            """,
            (telegram_id, username)
        )
        await db.commit()

    return telegram_id


class ClubData(BaseModel):
    name: str


class PlayerData(BaseModel):
    first_name: str
    last_name: str
    position: str
    price: int
    club_id: int | None = None
    photo: str | None = None


class StatsData(BaseModel):
    round_id: int
    player_id: int
    goals: int = 0
    assists: int = 0
    conceded: int = 0
    penalties_saved: int = 0
    team_result: str = "draw"


class SquadData(BaseModel):
    player_ids: list[int]


@router.get("/api/health")
async def health():
    return {"status": "ok", "app": "BANDYX"}


@router.get("/api/clubs")
async def get_clubs():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM clubs ORDER BY name")
        return [dict(row) for row in await cursor.fetchall()]


@router.post("/api/clubs")
async def add_club(
    data: ClubData,
    _: None = Depends(verify_admin)
):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO clubs (name) VALUES (?)", (data.name,)
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            raise HTTPException(400, "Клуб уже существует")
    return {"ok": True}


@router.get("/api/players")
async def get_players(
    position: str | None = None,
    club_id: int | None = None
):
    query = """
        SELECT players.*, clubs.name AS club_name
        FROM players
        LEFT JOIN clubs ON players.club_id = clubs.id
        WHERE players.active = 1
    """
    params = []

    if position:
        query += " AND players.position = ?"
        params.append(position)

    if club_id:
        query += " AND players.club_id = ?"
        params.append(club_id)

    query += " ORDER BY players.last_name"

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        return [dict(row) for row in await cursor.fetchall()]


@router.post("/api/players")
async def add_player(
    data: PlayerData,
    _: None = Depends(verify_admin)
):
    if data.price < 5000 or data.price > 35000:
        raise HTTPException(400, "Цена должна быть от 5000 до 35000")

    if data.position not in POSITION_LIMITS:
        raise HTTPException(400, "Неверная позиция")

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO players
            (first_name, last_name, position, price, club_id, photo)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                data.first_name, data.last_name, data.position,
                data.price, data.club_id, data.photo
            )
        )
        await db.commit()
        return {"ok": True, "id": cursor.lastrowid}


@router.post("/api/upload")
async def upload_photo(
    file: UploadFile = File(...),
    _: None = Depends(verify_admin)
):
    os.makedirs("uploads", exist_ok=True)
    filename = os.path.basename(file.filename or "photo.jpg")
    path = os.path.join("uploads", filename)

    content = await file.read()
    with open(path, "wb") as output:
        output.write(content)

    return {"url": f"/uploads/{filename}"}


@router.post("/api/rounds")
async def add_round(
    name: str,
    _: None = Depends(verify_admin)
):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO rounds (name) VALUES (?)", (name,)
        )
        await db.commit()
        return {"ok": True, "id": cursor.lastrowid}


@router.get("/api/rounds")
async def get_rounds():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM rounds ORDER BY id DESC"
        )
        return [dict(row) for row in await cursor.fetchall()]


@router.get("/api/squad")
async def get_squad(telegram_id: int = Depends(get_user)):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            "SELECT id, name FROM rounds WHERE is_open = 1 ORDER BY id DESC LIMIT 1"
        )
        round_row = await cursor.fetchone()

        if not round_row:
            return {
                "round": None,
                "player_ids": [],
                "message": "Сейчас нет открытого тура"
            }

        cursor = await db.execute(
            """
            SELECT player_id FROM selections
            WHERE telegram_id = ? AND round_id = ?
            """,
            (telegram_id, round_row["id"])
        )
        rows = await cursor.fetchall()

        return {
            "round": dict(round_row),
            "player_ids": [row["player_id"] for row in rows]
        }


@router.post("/api/squad")
async def save_squad(
    data: SquadData,
    telegram_id: int = Depends(get_user)
):
    if len(data.player_ids) != 11:
        raise HTTPException(400, "В составе должно быть ровно 11 игроков")

    if len(set(data.player_ids)) != 11:
        raise HTTPException(400, "Нельзя выбирать одного игрока дважды")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            "SELECT id FROM rounds WHERE is_open = 1 ORDER BY id DESC LIMIT 1"
        )
        round_row = await cursor.fetchone()

        if not round_row:
            raise HTTPException(400, "Сейчас нет открытого тура")

        placeholders = ",".join("?" for _ in data.player_ids)
        cursor = await db.execute(
            f"""
            SELECT id, position, price FROM players
            WHERE active = 1 AND id IN ({placeholders})
            """,
            data.player_ids
        )
        players = await cursor.fetchall()

        if len(players) != 11:
            raise HTTPException(400, "Некоторые игроки не найдены или недоступны")

        counts = {position: 0 for position in POSITION_LIMITS}
        total_cost = 0

        for player in players:
            position = player["position"]

            if position not in counts:
                raise HTTPException(400, "Неверная позиция игрока")

            counts[position] += 1
            total_cost += player["price"]

        if counts != POSITION_LIMITS:
            raise HTTPException(
                400,
                "Нужно выбрать 3 нападающих, 4 полузащитников, 3 защитников и 1 вратаря"
            )

        if total_cost > BUDGET_LIMIT:
            raise HTTPException(400, "Превышен бюджет 225 000")

        await db.execute(
            "DELETE FROM selections WHERE telegram_id = ? AND round_id = ?",
            (telegram_id, round_row["id"])
        )

        await db.executemany(
            """
            INSERT INTO selections (telegram_id, round_id, player_id)
            VALUES (?, ?, ?)
            """,
            [
                (telegram_id, round_row["id"], player_id)
                for player_id in data.player_ids
            ]
        )

        await db.commit()

    return {
        "ok": True,
        "saved": 11,
        "total_cost": total_cost
    }


@router.post("/api/stats")
async def add_stats(
    data: StatsData,
    _: None = Depends(verify_admin)
):
    if data.team_result not in ("win", "loss", "draw"):
        raise HTTPException(400, "Неверный результат команды")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO player_stats
            (round_id, player_id, goals, assists, conceded,
             penalties_saved, team_result)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.round_id, data.player_id, data.goals,
                data.assists, data.conceded,
                data.penalties_saved, data.team_result
            )
        )
        await db.commit()

    return {"ok": True}
