
import os
import hmac
import json
import hashlib
import urllib.parse
import time
import uuid

from supabase import create_client
from aiogram import Bot
from fastapi import APIRouter, HTTPException, UploadFile, File, Header, Depends
from pydantic import BaseModel

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")

if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    raise RuntimeError("Не настроены SUPABASE_URL и SUPABASE_SECRET_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

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

        return json.loads(data["user"])

    except Exception:
        raise HTTPException(401, "Не удалось подтвердить Telegram")


async def get_user(
    x_telegram_init_data: str | None = Header(default=None)
):
    user = verify_telegram(x_telegram_init_data)

    telegram_id = int(user["id"])
    username = user.get("username")

    try:
        supabase.table("users").upsert(
            {
                "telegram_id": telegram_id,
                "username": username
            },
            on_conflict="telegram_id"
        ).execute()
    except Exception:
        raise HTTPException(500, "Не удалось сохранить пользователя")

    return telegram_id


class ClubData(BaseModel):
    name: str
    logo: str | None = None


class ClubLogoData(BaseModel):
    logo: str


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


class MatchData(BaseModel):
    round_id: int
    home_club_id: int
    away_club_id: int
    match_date: str | None = None


class MatchResultData(BaseModel):
    home_score: int
    away_score: int


@router.get("/api/health")
async def health():
    try:
        supabase.table("rounds").select("id").limit(1).execute()
        return {"status": "ok", "app": "BANDYX", "database": "supabase"}
    except Exception:
        raise HTTPException(503, "Нет соединения с Supabase")


# КЛУБЫ

@router.get("/api/clubs")
async def get_clubs():
    try:
        result = supabase.table("clubs").select("*").order("name").execute()
        return result.data
    except Exception:
        raise HTTPException(500, "Не удалось загрузить клубы")


@router.post("/api/clubs")
async def add_club(
    data: ClubData,
    _: None = Depends(verify_admin)
):
    try:
        result = supabase.table("clubs").insert({
            "name": data.name,
            "logo": data.logo
        }).execute()
        return {"ok": True, "id": result.data[0]["id"]}
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(400, "Клуб уже существует")
        raise HTTPException(500, "Не удалось добавить клуб")


@router.post("/api/clubs/{club_id}/logo")
async def update_club_logo(
    club_id: int,
    data: ClubLogoData,
    _: None = Depends(verify_admin)
):
    try:
        result = supabase.table("clubs").update(
            {"logo": data.logo}
        ).eq("id", club_id).execute()

        if not result.data:
            raise HTTPException(404, "Клуб не найден")

        return {"ok": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Не удалось обновить эмблему")


# ИГРОКИ

@router.get("/api/players")
async def get_players(
    position: str | None = None,
    club_id: int | None = None
):
    try:
        query = supabase.table("players").select("*").eq("active", 1)

        if position:
            query = query.eq("position", position)

        if club_id:
            query = query.eq("club_id", club_id)

        result = query.order("last_name").execute()
        players = result.data

        clubs_result = supabase.table("clubs").select("id,name").execute()
        clubs = {c["id"]: c["name"] for c in clubs_result.data}

        for player in players:
            player["club_name"] = clubs.get(player.get("club_id"))

        return players
    except Exception:
        raise HTTPException(500, "Не удалось загрузить игроков")


@router.post("/api/players")
async def add_player(
    data: PlayerData,
    _: None = Depends(verify_admin)
):
    if data.price < 5000 or data.price > 35000:
        raise HTTPException(400, "Цена должна быть от 5000 до 35000")

    if data.position not in POSITION_LIMITS:
        raise HTTPException(400, "Неверная позиция")

    try:
        result = supabase.table("players").insert({
            "first_name": data.first_name,
            "last_name": data.last_name,
            "position": data.position,
            "price": data.price,
            "club_id": data.club_id,
            "photo": data.photo
        }).execute()

        return {"ok": True, "id": result.data[0]["id"]}
    except Exception:
        raise HTTPException(500, "Не удалось добавить игрока")


# ФОТО И ЭМБЛЕМЫ

@router.post("/api/upload")
async def upload_photo(
    file: UploadFile = File(...),
    _: None = Depends(verify_admin)
):
    allowed = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp"
    }

    if file.content_type not in allowed:
        raise HTTPException(400, "Разрешены только JPG, PNG и WEBP")

    content = await file.read()

    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "Размер изображения не должен превышать 10 МБ")

    extension = allowed[file.content_type]
    filename = f"{uuid.uuid4()}{extension}"

    try:
        supabase.storage.from_("bandyx-images").upload(
            filename,
            content,
            file_options={
                "content-type": file.content_type,
                "upsert": "true"
            }
        )

        public_url = supabase.storage.from_(
            "bandyx-images"
        ).get_public_url(filename)

        return {"url": public_url}
    except Exception:
        raise HTTPException(500, "Не удалось загрузить изображение")


# ТУРЫ

@router.post("/api/rounds")
async def add_round(
    name: str,
    _: None = Depends(verify_admin)
):
    try:
        result = supabase.table("rounds").insert({
            "name": name,
            "is_open": 0
        }).execute()

        return {"ok": True, "id": result.data[0]["id"]}
    except Exception:
        raise HTTPException(500, "Не удалось создать тур")


@router.get("/api/rounds")
async def get_rounds():
    try:
        result = supabase.table("rounds").select("*").order(
            "id", desc=True
        ).execute()
        return result.data
    except Exception:
        raise HTTPException(500, "Не удалось загрузить туры")


@router.post("/api/rounds/{round_id}/open")
async def open_round(
    round_id: int,
    _: None = Depends(verify_admin)
):
    try:
        found = supabase.table("rounds").select("id").eq(
            "id", round_id
        ).execute()

        if not found.data:
            raise HTTPException(404, "Тур не найден")

        supabase.table("rounds").update({"is_open": 0}).neq(
            "id", round_id
        ).execute()

        supabase.table("rounds").update({"is_open": 1}).eq(
            "id", round_id
        ).execute()

        return {"ok": True, "message": "Тур открыт"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Не удалось открыть тур")


@router.post("/api/rounds/{round_id}/close")
async def close_round(
    round_id: int,
    _: None = Depends(verify_admin)
):
    try:
        result = supabase.table("rounds").update(
            {"is_open": 0}
        ).eq("id", round_id).execute()

        if not result.data:
            raise HTTPException(404, "Тур не найден")

        return {"ok": True, "message": "Тур закрыт"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Не удалось закрыть тур")


# МАТЧИ

@router.get("/api/matches")
async def get_matches(round_id: int | None = None):
    try:
        query = supabase.table("matches").select("*")

        if round_id is not None:
            query = query.eq("round_id", round_id)

        result = query.order("match_date").execute()
        matches = result.data

        clubs_result = supabase.table("clubs").select("*").execute()
        clubs = {c["id"]: c for c in clubs_result.data}

        rounds_result = supabase.table("rounds").select("id,name").execute()
        rounds = {r["id"]: r["name"] for r in rounds_result.data}

        for match in matches:
            home = clubs.get(match["home_club_id"], {})
            away = clubs.get(match["away_club_id"], {})

            match["round_name"] = rounds.get(match["round_id"])
            match["home_club_name"] = home.get("name")
            match["home_club_logo"] = home.get("logo")
            match["away_club_name"] = away.get("name")
            match["away_club_logo"] = away.get("logo")

        return matches
    except Exception:
        raise HTTPException(500, "Не удалось загрузить матчи")


@router.post("/api/matches")
async def add_match(
    data: MatchData,
    _: None = Depends(verify_admin)
):
    if data.home_club_id == data.away_club_id:
        raise HTTPException(400, "Команды матча должны отличаться")

    try:
        round_check = supabase.table("rounds").select("id").eq(
            "id", data.round_id
        ).execute()

        if not round_check.data:
            raise HTTPException(404, "Тур не найден")

        for club_id in (data.home_club_id, data.away_club_id):
            club_check = supabase.table("clubs").select("id").eq(
                "id", club_id
            ).execute()

            if not club_check.data:
                raise HTTPException(404, "Клуб не найден")

        result = supabase.table("matches").insert({
            "round_id": data.round_id,
            "home_club_id": data.home_club_id,
            "away_club_id": data.away_club_id,
            "match_date": data.match_date
        }).execute()

        return {"ok": True, "id": result.data[0]["id"]}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Не удалось добавить матч")


@router.post("/api/matches/{match_id}/result")
async def set_match_result(
    match_id: int,
    data: MatchResultData,
    _: None = Depends(verify_admin)
):
    if data.home_score < 0 or data.away_score < 0:
        raise HTTPException(400, "Счёт не может быть отрицательным")

    try:
        result = supabase.table("matches").update({
            "home_score": data.home_score,
            "away_score": data.away_score,
            "status": "completed"
        }).eq("id", match_id).execute()

        if not result.data:
            raise HTTPException(404, "Матч не найден")

        return {"ok": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Не удалось сохранить результат")


# СОСТАВ

@router.get("/api/squad")
async def get_squad(
    telegram_id: int = Depends(get_user)
):
    try:
        round_result = supabase.table("rounds").select(
            "id,name"
        ).eq("is_open", 1).order(
            "id", desc=True
        ).limit(1).execute()

        if not round_result.data:
            return {
                "round": None,
                "player_ids": [],
                "message": "Сейчас нет открытого тура"
            }

        round_row = round_result.data[0]

        selections = supabase.table("selections").select(
            "player_id"
        ).eq("telegram_id", telegram_id).eq(
            "round_id", round_row["id"]
        ).execute()

        return {
            "round": round_row,
            "player_ids": [r["player_id"] for r in selections.data]
        }
    except Exception:
        raise HTTPException(500, "Не удалось загрузить состав")


@router.post("/api/squad")
async def save_squad(
    data: SquadData,
    telegram_id: int = Depends(get_user)
):
    if len(data.player_ids) != 11:
        raise HTTPException(400, "В составе должно быть ровно 11 игроков")

    if len(set(data.player_ids)) != 11:
        raise HTTPException(400, "Нельзя выбирать одного игрока дважды")

    try:
        round_result = supabase.table("rounds").select("id").eq(
            "is_open", 1
        ).order("id", desc=True).limit(1).execute()

        if not round_result.data:
            raise HTTPException(400, "Сейчас нет открытого тура")

        round_id = round_result.data[0]["id"]

        players_result = supabase.table("players").select(
            "id,position,price"
        ).eq("active", 1).in_(
            "id", data.player_ids
        ).execute()

        players = players_result.data

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

        supabase.table("selections").delete().eq(
            "telegram_id", telegram_id
        ).eq("round_id", round_id).execute()

        supabase.table("selections").insert([
            {
                "telegram_id": telegram_id,
                "round_id": round_id,
                "player_id": player_id
            }
            for player_id in data.player_ids
        ]).execute()

        return {
            "ok": True,
            "saved": 11,
            "total_cost": total_cost
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Не удалось сохранить состав")


# СТАТИСТИКА

@router.post("/api/stats")
async def add_stats(
    data: StatsData,
    _: None = Depends(verify_admin)
):
    if data.team_result not in ("win", "loss", "draw"):
        raise HTTPException(400, "Неверный результат команды")

    try:
        supabase.table("player_stats").insert({
            "round_id": data.round_id,
            "player_id": data.player_id,
            "goals": data.goals,
            "assists": data.assists,
            "conceded": data.conceded,
            "penalties_saved": data.penalties_saved,
            "team_result": data.team_result
        }).execute()

        return {"ok": True}
    except Exception:
        raise HTTPException(500, "Не удалось сохранить статистику")
