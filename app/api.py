import os
import aiosqlite

from aiogram import Bot
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

DB_PATH = "bandyx.db"
router = APIRouter()
bot = None


def set_bot(value: Bot):
    global bot
    bot = value


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
async def add_club(data: ClubData):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO clubs (name) VALUES (?)",
                (data.name,)
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            raise HTTPException(400, "Клуб уже существует")
    return {"ok": True}


@router.get("/api/players")
async def get_players(position: str | None = None, club_id: int | None = None):
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
async def add_player(data: PlayerData):
    if data.price < 5000 or data.price > 35000:
        raise HTTPException(400, "Цена должна быть от 5000 до 35000")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO players
            (first_name, last_name, position, price, club_id, photo)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (data.first_name, data.last_name, data.position,
             data.price, data.club_id, data.photo)
        )
        await db.commit()
        return {"ok": True, "id": cursor.lastrowid}


@router.post("/api/upload")
async def upload_photo(file: UploadFile = File(...)):
    os.makedirs("uploads", exist_ok=True)
    filename = os.path.basename(file.filename or "photo.jpg")
    path = os.path.join("uploads", filename)
    content = await file.read()
    with open(path, "wb") as output:
        output.write(content)
    return {"url": f"/uploads/{filename}"}


@router.post("/api/rounds")
async def add_round(name: str):
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
        cursor = await db.execute("SELECT * FROM rounds ORDER BY id DESC")
        return [dict(row) for row in await cursor.fetchall()]


@router.post("/api/stats")
async def add_stats(data: StatsData):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO player_stats
            (round_id, player_id, goals, assists, conceded,
             penalties_saved, team_result)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (data.round_id, data.player_id, data.goals, data.assists,
             data.conceded, data.penalties_saved, data.team_result)
        )
        await db.commit()
    return {"ok": True}
