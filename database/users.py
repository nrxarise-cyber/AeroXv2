from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import random
from db import users_col, proxies_col

# ==========================================
# INTERNAL HELPER FUNCTIONS
# ==========================================

async def _check_and_handle_expiry(user: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Internal helper to check if a user's plan is expired and handle it automatically.
    
    If the plan is expired, resets premium, plan, credits, and expires_at fields.
    """
    if not user:
        return None
    
    expires_at = user.get("expires_at")
    # Handle case where expires_at might be stored as string or datetime
    if expires_at:
        if isinstance(expires_at, str):
            try:
                expires_at = datetime.fromisoformat(expires_at)
            except ValueError:
                expires_at = None
                
        if expires_at and expires_at < datetime.utcnow():
            # Plan has expired! Reset plan-related fields.
            user_id = user["user_id"]
            update_data = {
                "premium": False,
                "plan": None,
                "credits": 0,
                "expires_at": None
            }
            await users_col.update_one(
                {"user_id": user_id},
                {"$set": update_data}
            )
            # Update local dict representation for immediate return consistency
            user.update(update_data)
            
    return user


async def reset_expired_users() -> int:
    """
    Scan MongoDB and automatically reset every expired premium user.
    
    Resets premium to False, plan to None, credits to 0, and expires_at to None.
    Returns the number of updated documents.
    """
    result = await users_col.update_many(
        {
            "premium": True,
            "expires_at": {"$lt": datetime.utcnow()}
        },
        {
            "$set": {
                "premium": False,
                "plan": None,
                "credits": 0,
                "expires_at": None
            }
        }
    )
    return result.modified_count


# ==========================================
# USER PROFILE & INITIALIZATION
# ==========================================

async def ensure_user(
    user_id: int, 
    username: Optional[str] = None, 
    first_name: Optional[str] = None
) -> None:
    """
    Ensure the user document exists in MongoDB.
    
    Creates a new user with default fields on first interaction,
    preserving existing fields if they already exist.
    """
    default_username = username or f"user_{user_id}"
    default_first_name = first_name or ""
    
    await users_col.update_one(
        {"user_id": user_id},
        {
            "$setOnInsert": {
                "user_id": user_id,
                "join_date": datetime.utcnow(),
                "premium": False,
                "plan": None,
                "credits": 0,
                "expires_at": None,
                "total_checks": 0,
                "approved": 0,
                "charged": 0,
                "dead": 0,
                "banned": False
            },
            "$set": {
                "username": default_username,
                "first_name": default_first_name,
            }
        },
        upsert=True
    )


async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Retrieve the raw user document from the database.
    
    Automatically processes plan expiry checks before returning.
    """
    user = await users_col.find_one({"user_id": user_id})
    if user:
        user = await _check_and_handle_expiry(user)
    return user


async def get_profile(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Get the complete user profile including plan, credits, and usage stats.
    
    Automatically handles plan expiry checks and formats the plan name for UI presentation.
    """
    user = await get_user(user_id)
    if not user:
        return None
        
    plan = user.get("plan")
    formatted_plan = plan.capitalize() if plan else "Free"
    
    return {
        "user_id": user.get("user_id"),
        "username": user.get("username", f"user_{user_id}"),
        "first_name": user.get("first_name", ""),
        "plan": formatted_plan,
        "premium": user.get("premium", False),
        "credits": user.get("credits", 0),
        "expires_at": user.get("expires_at"),
        "total_checks": user.get("total_checks", 0),
        "approved": user.get("approved", 0),
        "charged": user.get("charged", 0),
        "dead": user.get("dead", 0),
        "banned": user.get("banned", False),
        "join_date": user.get("join_date"),
    }


# ==========================================
# BAN / COMPLIANCE SYSTEM
# ==========================================

async def ban_user(user_id: int) -> None:
    """Ban a user, blocking them from interacting with the bot/system."""
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"banned": True}},
        upsert=True
    )


async def unban_user(user_id: int) -> None:
    """Unban a user, restoring their access."""
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"banned": False}},
        upsert=True
    )


async def is_banned(user_id: int) -> bool:
    """Check if a user is currently banned."""
    user = await users_col.find_one({"user_id": user_id}, {"banned": 1})
    return bool(user and user.get("banned", False))


# ==========================================
# PREMIUM & SUBSCRIPTION SYSTEM
# ==========================================

async def is_premium(user_id: int) -> bool:
    """
    Check if a user has active premium status.
    
    Handles automatic plan expiry checks. Returns True if the user is premium
    and their subscription has not expired.
    """
    user = await get_user(user_id)
    return bool(user and user.get("premium", False))


async def set_plan(user_id: int, plan: str, reset_credits: bool = True) -> None:
    """
    Set a subscription plan for the user (core, nova, or monarch).
    
    Sets the premium flag, calculates a 30-day plan expiration date,
    and optionally resets or sets the respective credit amount.
    
    - core: 8,000 credits
    - nova: 16,000 credits
    - monarch: Unlimited credits (-1)
    """
    plan_lower = plan.strip().lower()
    
    if plan_lower == "core":
        plan_name = "core"
        credits_to_set = 8000
    elif plan_lower == "nova":
        plan_name = "nova"
        credits_to_set = 16000
    elif plan_lower == "monarch":
        plan_name = "monarch"
        credits_to_set = -1
    else:
        raise ValueError(f"Invalid plan type: '{plan}'. Choose from 'core', 'nova', or 'monarch'.")
        
    expires_at = datetime.utcnow() + timedelta(days=30)
    
    update_fields = {
        "premium": True,
        "plan": plan_name,
        "expires_at": expires_at
    }
    
    if reset_credits:
        update_fields["credits"] = credits_to_set
        
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": update_fields},
        upsert=True
    )


async def remove_plan(user_id: int) -> None:
    """
    Remove the subscription plan and premium status from the user.
    
    Resets plan, credits, premium, and expires_at fields to default.
    """
    await users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "premium": False,
                "plan": None,
                "credits": 0,
                "expires_at": None
            }
        }
    )


async def extend_plan(user_id: int, days: int = 30, reset_credits: bool = False) -> None:
    """
    Extend the expiration date of the user's active plan by a number of days.
    
    If the plan is currently expired or has no set expiration, sets it
    relative to the current UTC time. Otherwise, adds to the existing expires_at.
    
    When reset_credits=True, refreshes the credits according to the current active plan.
    """
    user = await users_col.find_one({"user_id": user_id}, {"expires_at": 1, "plan": 1})
    current_expiry = user.get("expires_at") if user else None
    current_plan = user.get("plan") if user else None
    
    # Parse if stored as ISO string
    if isinstance(current_expiry, str):
        try:
            current_expiry = datetime.fromisoformat(current_expiry)
        except ValueError:
            current_expiry = None
            
    base_time = current_expiry if (current_expiry and current_expiry > datetime.utcnow()) else datetime.utcnow()
    new_expiry = base_time + timedelta(days=days)
    
    update_data = {"expires_at": new_expiry}
    
    if reset_credits and current_plan:
        plan_lower = current_plan.strip().lower()
        if plan_lower == "core":
            update_data["credits"] = 8000
        elif plan_lower == "nova":
            update_data["credits"] = 16000
        elif plan_lower == "monarch":
            update_data["credits"] = -1
            
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": update_data},
        upsert=True
    )


# ==========================================
# CREDIT MANAGEMENT SYSTEM
# ==========================================

async def add_credits(user_id: int, amount: int) -> None:
    """
    Add a specified number of credits to a user's account.
    
    If the user has an unlimited plan (Monarch, credits = -1),
    credits remain unlimited.
    """
    if amount < 0:
        raise ValueError("Amount to add must be positive. Use remove_credits to subtract.")
        
    user = await get_user(user_id)
    if not user:
        # Create user if they don't exist
        await ensure_user(user_id)
        user = await get_user(user_id)
        
    current_credits = user.get("credits", 0) if user else 0
    
    # If Monarch/Unlimited, do not modify credits
    if current_credits == -1:
        return
        
    await users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"credits": amount}},
        upsert=True
    )


async def remove_credits(user_id: int, amount: int) -> None:
    """
    Subtract a specified number of credits from a user's account.
    
    If the user has an unlimited plan (Monarch, credits = -1),
    credits remain unlimited. Credits will never go below zero.
    """
    if amount < 0:
        raise ValueError("Amount to remove must be positive.")
        
    user = await get_user(user_id)
    if not user:
        return
        
    current_credits = user.get("credits", 0)
    
    # If Monarch/Unlimited, do not modify credits
    if current_credits == -1:
        return
        
    new_credits = max(0, current_credits - amount)
    
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"credits": new_credits}}
    )


async def set_credits(user_id: int, amount: int) -> None:
    """
    Set user credits to an absolute value.
    
    An amount of -1 represents unlimited credits. Values below -1 are not allowed.
    """
    if amount < -1:
        raise ValueError("Credits cannot be set below -1. Use -1 for unlimited credits.")
        
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"credits": amount}},
        upsert=True
    )


async def consume_credit(user_id: int) -> bool:
    """
    Consume exactly one credit from a user's account for performing a check.
    
    - Returns True if the user has an unlimited plan (Monarch).
    - Returns True and decreases credits by 1 if the user has >= 1 credit.
    - Returns False if the user has 0 credits.
    
    Checks and handles plan expiration automatically.
    """
    user = await get_user(user_id)
    if not user:
        return False
        
    # Check if banned
    if user.get("banned", False):
        return False
        
    current_credits = user.get("credits", 0)
    
    # Unlimited credits (Monarch)
    if current_credits == -1:
        await update_stats(user_id, checks=1)
        return True
        
    # Standard credit checks
    if current_credits > 0:
        await users_col.update_one(
            {"user_id": user_id},
            {"$inc": {"credits": -1}}
        )
        await update_stats(user_id, checks=1)
        return True
        
    return False


# ==========================================
# STATISTICS TRACKING
# ==========================================

async def update_stats(
    user_id: int, 
    checks: int = 1, 
    approved: int = 0, 
    charged: int = 0, 
    dead: int = 0
) -> None:
    """
    Increment statistical counters for user checks and outcome counts.
    
    - checks: Total checks performed
    - approved: Approved checks outcome count
    - charged: Charged checks outcome count
    - dead: Dead checks outcome count
    """
    await users_col.update_one(
        {"user_id": user_id},
        {
            "$inc": {
                "total_checks": checks,
                "approved": approved,
                "charged": charged,
                "dead": dead
            }
        },
        upsert=True
    )


# ==========================================
# PROXY CONFIGURATION
# ==========================================

async def set_proxy(user_id: int, proxy: str) -> None:
    """Add a single proxy for the user (deduplicates by user_id + proxy)."""
    await proxies_col.update_one(
        {"user_id": user_id, "proxy": proxy},
        {"$set": {"user_id": user_id, "proxy": proxy}},
        upsert=True
    )


async def add_proxies_bulk(user_id: int, proxies: list) -> int:
    """Add multiple proxies for the user in bulk. Returns count of proxies processed."""
    if not proxies:
        return 0
    from pymongo import UpdateOne
    ops = [
        UpdateOne(
            {"user_id": user_id, "proxy": p},
            {"$set": {"user_id": user_id, "proxy": p}},
            upsert=True
        )
        for p in proxies
    ]
    await proxies_col.bulk_write(ops)
    return len(proxies)


async def get_proxy(user_id: int) -> Optional[str]:
    """Retrieve a random proxy from the user's proxy pool."""
    proxies = await proxies_col.find({"user_id": user_id}).to_list(length=10000)
    if not proxies:
        return None
    return random.choice(proxies)["proxy"]


async def get_proxy_count(user_id: int) -> int:
    """Count how many proxies a user has stored."""
    return await proxies_col.count_documents({"user_id": user_id})


async def get_all_user_proxies(user_id: int) -> List[str]:
    """Get all proxy strings for a user."""
    docs = await proxies_col.find({"user_id": user_id}).to_list(length=10000)
    return [d["proxy"] for d in docs]


async def remove_proxy(user_id: int) -> int:
    """Remove all proxies for a user. Returns the number of proxies deleted."""
    result = await proxies_col.delete_many({"user_id": user_id})
    return result.deleted_count


async def remove_single_proxy(user_id: int, proxy: str) -> bool:
    """Remove a specific proxy for a user. Returns True if deleted."""
    result = await proxies_col.delete_one({"user_id": user_id, "proxy": proxy})
    return result.deleted_count > 0