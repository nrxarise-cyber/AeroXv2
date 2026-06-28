from datetime import datetime

from db import users_col


# =========================
# PREMIUM FUNCTIONS
# =========================

async def is_premium(user_id: int) -> bool:
    user = await users_col.find_one({"user_id": user_id})
    return bool(user and user.get("premium", False))


async def add_premium(user_id: int) -> None:
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"premium": True}},
        upsert=True,
    )


async def remove_premium(user_id: int) -> None:
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"premium": False}},
    )


# =========================
# USER PROFILE
# =========================

async def ensure_user(user_id: int, username: str | None = None, first_name: str | None = None) -> None:
    """Create the user document on first interaction, preserving existing fields."""
    await users_col.update_one(
        {"user_id": user_id},
        {
            "$setOnInsert": {
                "join_date": datetime.utcnow(),
            },
            "$set": {
                "username": username or f"user_{user_id}",
                "first_name": first_name or "",
            },
        },
        upsert=True,
    )


async def get_user(user_id: int) -> dict | None:
    return await users_col.find_one({"user_id": user_id})


# =========================
# USER PROXY FUNCTIONS
# =========================

async def set_proxy(user_id: int, proxy: str) -> None:
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"proxy": proxy}},
        upsert=True,
    )


async def get_proxy(user_id: int) -> str | None:
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        return None
    return user.get("proxy")


async def remove_proxy(user_id: int) -> None:
    await users_col.update_one(
        {"user_id": user_id},
        {"$unset": {"proxy": ""}},
    )