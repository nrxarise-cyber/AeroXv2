from datetime import datetime

from db import logs_col


async def save_log(user_id: int, total: int, charged: int, approved: int) -> None:
    """Persist a single bulk-check session result."""
    await logs_col.insert_one(
        {
            "user_id": user_id,
            "total": total,
            "charged": charged,
            "approved": approved,
            "created_at": datetime.utcnow(),
        }
    )


async def get_user_logs(user_id: int) -> list[dict]:
    """Return the last 100 check session logs for a user."""
    return await logs_col.find({"user_id": user_id}).to_list(length=100)


async def get_user_stats(user_id: int) -> dict:
    """Aggregate lifetime stats for a user from their check logs.

    Returns a dict with keys:
        sessions      : total number of check sessions run
        total_checked : total cards checked across all sessions
        total_charged : total charged (paid) hits
        total_approved: total approved (live) hits
        total_hits    : charged + approved combined
        hit_rate      : percentage of cards that were hits (0–100 float)
    """
    pipeline = [
        {"$match": {"user_id": user_id}},
        {
            "$group": {
                "_id": None,
                "sessions": {"$sum": 1},
                "total_checked": {"$sum": "$total"},
                "total_charged": {"$sum": "$charged"},
                "total_approved": {"$sum": "$approved"},
            }
        },
    ]

    results = await logs_col.aggregate(pipeline).to_list(length=1)

    if not results:
        return {
            "sessions": 0,
            "total_checked": 0,
            "total_charged": 0,
            "total_approved": 0,
            "total_hits": 0,
            "hit_rate": 0.0,
        }

    row = results[0]
    total_hits = row["total_charged"] + row["total_approved"]
    total_checked = row["total_checked"]
    hit_rate = round((total_hits / total_checked * 100), 2) if total_checked > 0 else 0.0

    return {
        "sessions": row["sessions"],
        "total_checked": total_checked,
        "total_charged": row["total_charged"],
        "total_approved": row["total_approved"],
        "total_hits": total_hits,
        "hit_rate": hit_rate,
    }


async def get_recent_sessions(user_id: int, limit: int = 5) -> list[dict]:
    """Return the N most recent check sessions for analytics display."""
    return (
        await logs_col.find({"user_id": user_id})
        .sort("created_at", -1)
        .to_list(length=limit)
    )
