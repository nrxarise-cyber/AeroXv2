import asyncio
import os
import time
from datetime import datetime

import aiofiles
from telethon import Button, TelegramClient, events

from config import API_ID, API_HASH, BOT_TOKEN, OWNER_ID
from database.logs import get_recent_sessions, get_user_stats, save_log
from database.sites import (
    add_site,
    get_all_sites,
    mark_site_dead,
    remove_site,
    site_count,
)
from database.users import (
    ensure_user,
    get_proxy,
    get_user,
    get_profile,
    is_premium,
    set_plan,
    remove_plan,
    add_credits,
    remove_credits,
    extend_plan,
    remove_proxy,
    set_proxy,
)

from utils.binlookup import get_bin_info
from utils.checker import check_card_with_retry, test_proxy, test_site
from utils.emojis import premium_emoji
from utils.helpers import extract_cc, format_elapsed

# ─── Bot Client ───────────────────────────────────────────────────────────────

bot = TelegramClient("checker_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Active bulk-checking sessions: {session_key: {'paused': bool}}
active_sessions: dict = {}


# ═══════════════════════════════════════════════════════════════════════════════
# INLINE KEYBOARD BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

def _kb_main() -> list:
    return [
        [Button.inline("💳 𝐂ʜᴇᴄᴋᴇʀ", b"menu:checker"),  Button.inline("📡  𝐏ʀᴏxʏ",   b"menu:proxy")],
        [Button.inline("👤  𝐏ʀᴏғɪʟᴇ", b"menu:profile"),  Button.inline("❓  𝐇ᴇʟᴘ",    b"menu:help")],
    ]


def _kb_checker() -> list:
    return [
        [Button.inline("🛒  𝘚𝘩𝘰𝘱𝘪𝘧𝘺",              b"menu:shopify")],
        [Button.inline("💳  𝘚𝘵𝘳𝘪𝘱𝘦 (Coming Soon)", b"noop"),
         Button.inline("🟣  𝘙𝘢𝘻𝘰𝘳𝘱𝘢𝘺  (Coming Soon)", b"noop")],
        [Button.inline("🔙  Back", b"menu:main")],
    ]


def _kb_shopify() -> list:
    return [
        [Button.inline("⚡ 𝘚𝘪𝘯𝘨𝘭𝘦  /sh",    b"noop"),
         Button.inline("📋 𝘔𝘶𝘵𝘪   /msh",   b"noop")],
        [Button.inline("📂 T𝘹𝘵 𝘍𝘪𝘭𝘦  /shtxt", b"noop")],
        [Button.inline("🔙  𝘉𝘢𝘤𝘬", b"menu:checker")],
    ]


def _kb_proxy() -> list:
    return [
        [Button.inline("➕  𝘚𝘦𝘵 Proxy", b"proxy:set"),
         Button.inline("👁  𝘝𝘪𝘦𝘸 𝘗𝘳𝘰𝘹𝘺", b"proxy:view")],

        [Button.inline("🗑  𝘙𝘦𝘮𝘰𝘷𝘦 𝘗𝘳𝘰𝘹𝘺", b"proxy:remove"),
         Button.inline("🔄  𝘊𝘩𝘦𝘤𝘬 𝘗𝘳𝘰𝘹𝘺", b"proxy:check")],

        [Button.inline("🔙  𝘉𝘢𝘤𝘬", b"menu:main")],
    ]


def _kb_profile() -> list:
    return [
        [Button.inline("📊  𝘈𝘯𝘢𝘭𝘺𝘵𝘪𝘤𝘴", b"menu:analytics")],
        [Button.inline("🔙  𝘉𝘢𝘤𝘬",      b"menu:main")],
    ]


def _kb_back_main() -> list:
    return [[Button.inline("🔙  𝘉𝘢𝘤𝘬", b"menu:main")]]


def _kb_back_profile() -> list:
    return [[Button.inline("🔙  𝘉𝘢𝘤𝘬", b"menu:profile")]]


def _kb_progress(session_key: str) -> list:
    return [
        [Button.inline("⏸️  Pause", b"pause"), Button.inline("▶️  Resume", b"resume")],
        [Button.inline("🛑  Stop",  b"stop")],
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# MESSAGE TEXT BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

def _txt_main(first_name: str) -> str:
    return (
        f"<b>🐺 𝑨 𝑬 𝑹 𝑶 𝑿 𝑨 𝑼 𝑻 𝑯</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━</b>\n"
        f"<b>👋 Welcome back, {first_name}!</b>\n\n"
        f"<blockquote>Select an option from the menu below to get started.</blockquote>\n"
        f"<b>━━━━━━━━━━━━━━━━━</b>\n"
        f'🤖 <b>Bot By: <a href="tg://user?id=1817159548"> ZEUSｌ</a></b>'
    )


def _txt_checker() -> str:
    return (
        "<b>🐺 𝑨 𝑬 𝑹 𝑶 𝑿 𝑨 𝑼 𝑻 𝑯 </b>\n"
        "<b>━━━━━━━━━━━━━━━━━</b>\n"
        "<b> 𝑮𝑨𝑻𝑬𝑾𝑨𝒀𝑺 </b>\n\n"
        "<blockquote>𝑺𝒆𝒍𝒆𝒄𝒕 𝒀𝒐𝒖𝒓 𝑷𝒓𝒆𝒇𝒆𝒓𝒓𝒆𝒅 𝑮𝒂𝒕𝒆𝒘𝒂𝒚 𝑻𝒐 𝑩𝒆𝒈𝒊𝒏 𝑪𝒉𝒆𝒄𝒌𝒊𝒏𝒈.</blockquote>"
        "<b>━━━━━━━━━━━━━━━━━</b>"
    )


def _txt_shopify() -> str:
    return (
        "<b>🐺 𝑨 𝑬 𝑹 𝑶 𝑿 𝑨 𝑼 𝑻 𝑯</b>\n"
        "<b>━━━━━━━━━━━━━━━━━</b>\n"
        "<b>𝑺𝑯𝑶𝑷𝑰𝑭𝒀</b>\n\n"
        "<blockquote>"
        "⚡ <b>/sh</b> <code>card|mm|yy|cvv</code>\n"
        "   𝑺𝒊𝒏𝒈𝒍𝒆 𝑪𝒂𝒓𝒅 𝑪𝒉𝒆𝒄𝒌\n\n"
        "📋 <b>/msh</b>\n"
        " 𝑷𝒂𝒔𝒕𝒆 𝑴𝒖𝒕𝒊𝒑𝒍𝒆 𝑪𝒂𝒓𝒅𝒔 (one per line)\n\n"
        "📂 <b>/shtxt</b>\n"
        " 𝑹𝒆𝒑𝒍𝒚 𝑻𝒐 𝒂 <code>.𝒕𝒙𝒕</code> 𝑭𝒊𝒍𝒆 𝑻𝒐 𝑩𝒖𝒍𝒌-𝑪𝒉𝒆𝒄𝒌"
        "</blockquote>\n"
        "<b>━━━━━━━━━━━━━━━━━</b>"
    )


async def _txt_proxy(user_id: int) -> str:
    proxy = await get_proxy(user_id)
    if proxy:
        parts = proxy.split(":")
        display = f"<code>{parts[0]}:{parts[1]}:***:***</code>" if len(parts) >= 2 else f"<code>{proxy}</code>"
        status = f"✅ <b>𝑷𝒓𝒐𝒙𝒚 𝑹𝒆𝒂𝒅𝒚</b>\n{display}"
    else:
        status = "❌ <b>𝑵𝒐 𝑷𝒓𝒐𝒙𝒚 𝑺𝒆𝒕</b>"

    return (
        "<b>🐺 𝑨 𝑬 𝑹 𝑶 𝑿 𝑨 𝑼 𝑻 𝑯</b>\n"
        "<b>━━━━━━━━━━━━━━━━━</b>\n"
        "<b>📡 𝑷𝑹𝑶𝑿𝒀 𝑽𝑨𝑼𝑳𝑻 </b>\n\n"
        "<blockquote>𝑪𝒐𝒏𝒇𝒊𝒈𝒖𝒓𝒆 𝒀𝒐𝒖𝒓 𝑷𝒓𝒊𝒗𝒂𝒕𝒆 𝑷𝒓𝒐𝒙𝒚 𝑭𝒐𝒓 𝑶𝒑𝒕𝒊𝒎𝒂𝒍 𝑷𝒆𝒓𝒇𝒐𝒓𝒎𝒂𝒏𝒄𝒆.</blockquote>"
        f"<blockquote>Status: {status}</blockquote>\n"
        "<b>━━━━━━━━━━━━━━━━━</b>"
    )


async def _txt_profile(user_id: int) -> str:
    user = await get_user(user_id)
    stats = await get_user_stats(user_id)

    username  = (user or {}).get("username", f"user_{user_id}")
    first_name = (user or {}).get("first_name", "—")
    plan      = "⭐ Premium" if (user or {}).get("premium") else "🔓 Free"
    join_raw  = (user or {}).get("join_date")
    join_date = join_raw.strftime("%d %b %Y") if join_raw else "—"
return (
    "<b>🐺 𝐀ᴇʀᴏ𝐗</b>\n"
    "<b>━━━━━━━━━━━━━━━━━</b>\n"
    "<b>💃 𝐏ʀᴏғɪʟᴇ</b>\n\n"
    f"<blockquote>"
    f"🚀 <b>𝐔𝐬ᴇʀ 𝐈𝐃:</b> <code>{user_id}</code>\n"
    f"🙂 <b>𝐍ᴀᴍᴇ:</b> {first_name}\n"
    f"☄️ <b>𝐔𝐬ᴇʀɴᴀᴍᴇ:</b> @{username}\n"
    f"🚀 <b>𝐏ʟᴀɴ:</b> {plan}\n"
    f"📆 <b>𝐉ᴏɪɴᴇᴅ:</b> {join_date}"
    f"</blockquote>\n"
    "<b>━━━━━━━━━━━━━━━━━</b>\n"
    "<b>📊 𝐒ᴛᴀᴛ𝐬</b>\n\n"
    f"<blockquote>"
    f"📅 <b>𝐓ᴏᴛᴀʟ 𝐂ʜᴇᴄᴋ𝐬:</b> {stats['total_checked']:,}\n"
    f"📸 <b>𝐂ʜᴀʀɢᴇᴅ:</b> {stats['total_charged']:,}\n"
    f"🎥 <b>𝐀ᴘᴘʀᴏᴠᴇᴅ:</b> {stats['total_approved']:,}\n"
    f"😅 <b>𝐓ᴏᴛᴀʟ 𝐇ɪᴛ𝐬:</b> {stats['total_hits']:,}\n"
    f"⚽️ <b>𝐇ɪᴛ 𝐑ᴀᴛᴇ:</b> {stats['hit_rate']}%"
    f"</blockquote>\n"
    "<b>━━━━━━━━━━━━━━━━━</b>\n\n"
    "<b>🐻 𝑷𝒐𝒘𝒆𝒓𝒆𝒅 𝒃𝒚 𝑨𝒆𝒓𝒐𝑿</b>"
)


async def _txt_analytics(user_id: int) -> str:
    stats   = await get_user_stats(user_id)
    recent  = await get_recent_sessions(user_id, limit=5)

    sessions_text = ""
    if recent:
        for i, s in enumerate(recent, 1):
            date = s.get("created_at", datetime.utcnow()).strftime("%d/%m %H:%M")
            charged  = s.get("charged", 0)
            approved = s.get("approved", 0)
            total    = s.get("total", 0)
            sessions_text += f"  {i}. {date} — {total} cards | ✅{charged} 🔥{approved}\n"
    else:
        sessions_text = "  No sessions yet."

    bar_filled  = int(stats["hit_rate"] / 10)
    bar_empty   = 10 - bar_filled
    hit_bar     = "█" * bar_filled + "░" * bar_empty

    return (
        "<b>🐺 𝑨 𝑬 𝑹 𝑶 𝑿 𝑨 𝑼 𝑻 𝑯</b>\n"
        "<b>━━━━━━━━━━━━━━━━━</b>\n"
        "<b>📊 𝐀𝐧𝐚𝐥𝐲𝐭𝐢𝐜𝐬</b>\n\n"
        f"<blockquote>"
        f"📦 <b>Sessions:</b> {stats['sessions']}\n"
        f"🔍 <b>Cards Checked:</b> {stats['total_checked']:,}\n"
        f"📷 <b>Charged:</b> {stats['total_charged']:,}\n"
        f"🎥 <b>Approved:</b> {stats['total_approved']:,}\n"
        f"😅 <b>Total Hits:</b> {stats['total_hits']:,}\n"
        f"⚽ <b>Hit Rate:</b> {stats['hit_rate']}%\n"
        f"<code>[{hit_bar}] {stats['hit_rate']}%</code>"
        f"</blockquote>\n"
        "<b>━━━━━━━━━━━━━━━━━</b>\n"
        "<b>🕐 𝐑𝐞𝐜𝐞𝐧𝐭 𝐒𝐞𝐬𝐬𝐢𝐨𝐧𝐬</b>\n\n"
        f"<blockquote>{sessions_text}</blockquote>\n"
        "<b>━━━━━━━━━━━━━━━━━</b>"
    )

def _txt_help() -> str:
    return (
    "<b>🐺 𝐀ᴇʀᴏ𝐗</b>\n"
    "<b>━━━━━━━━━━━━━━━━━</b>\n"
    "<b>❓ 𝐇ᴇʟᴘ & 𝐂ᴏᴍᴍᴀɴᴅ𝐬</b>\n\n"

    "<blockquote>𝑸𝒖𝒊𝒄𝒌 𝐂ᴏᴍᴍᴀɴᴅ 𝐑ᴇғᴇʀᴇɴᴄᴇ.</blockquote>\n\n"

    "<b>💳 𝐂ʜᴇᴄᴋᴇʀ</b>\n"
    "<blockquote>"
    "/sh <code>card|mm|yy|cvv</code> — 𝐒ɪɴɢʟᴇ 𝐂ʜᴇᴄᴋ\n"
    "/msh — 𝐌ᴜʟᴛɪ 𝐂ʜᴇᴄᴋ\n"
    "/shtxt — 𝐁ᴜʟᴋ 𝐂ʜᴇᴄᴋ"
    "</blockquote>\n\n"

    "<b>📡 𝐏ʀᴏxʏ</b>\n"
    "<blockquote>"
    "/addproxy <code>ip:port:user:pass</code> — 𝐒ᴇᴛ 𝐏ʀᴏxʏ\n"
    "/getproxy — 𝐕ɪᴇᴡ 𝐏ʀᴏxʏ\n"
    "/rmproxy — 𝐑ᴇᴍᴏᴠᴇ 𝐏ʀᴏxʏ\n"
    "/chkproxy — 𝐓ᴇ𝐬ᴛ 𝐏ʀᴏxʏ"
    "</blockquote>\n\n"

    "<b>🌐 𝐒ɪᴛᴇ𝐬 (𝐀ᴅᴍɪɴ)</b>\n"
    "<blockquote>"
    "/addsite <code>url</code> — 𝐀ᴅᴅ 𝐒ɪᴛᴇ\n"
    "/rm <code>url</code> — 𝐑ᴇᴍᴏᴠᴇ 𝐒ɪᴛᴇ\n"
    "/site — 𝐂ʜᴇᴄᴋ 𝐒ɪᴛᴇ𝐬"
    "</blockquote>\n\n"

    "<b>📌 𝐂ᴀʀᴅ 𝐅ᴏʀᴍᴀᴛ</b>\n"
    "<blockquote><code>card|mm|yyyy|cvv</code></blockquote>\n"

    "<b>━━━━━━━━━━━━━━━━━</b>\n"
    '😵‍💫 <b>𝐁ᴏᴛ 𝐁ʏ ~ <a href="tg://user?id=1817159548">𝐙ᴇᴜ𝐬</a></b>'
)
# ═══════════════════════════════════════════════════════════════════════════════
# SHARED GUARDS
# ═══════════════════════════════════════════════════════════════════════════════

async def _ensure_and_check_premium(event) -> bool:
    """Register user on first interaction and verify premium status.

    For NewMessage events: replies with a denial message and returns False.
    Returns True if the user is premium.
    """
    sender = event.sender
    try:
        if sender is None:
            sender = await event.get_sender()
        await ensure_user(
            event.sender_id,
            username=getattr(sender, "username", None),
            first_name=getattr(sender, "first_name", None),
        )
    except Exception:
        pass

    if not await is_premium(event.sender_id):
        await event.reply(
            premium_emoji("❌ <b>Access Denied</b>\n\nOnly premium users can use this bot."),
            parse_mode="html",
        )
        return False
    return True


async def _require_sites_and_proxy(event, user_id: int):
    """Ensure active sites exist and user has a proxy configured.

    Returns (sites, proxy) on success, or (None, None) after sending an error reply.
    """
    sites = await get_all_sites()
    if not sites:
        await event.reply(
            premium_emoji("❌ No sites available. Please contact admin."),
            parse_mode="html",
        )
        return None, None

    proxy = await get_proxy(user_id)
    if not proxy:
        await event.reply(
            premium_emoji(
                "❌ No proxy set.\n\nUse <code>/addproxy ip:port:user:pass</code> to add your proxy."
            ),
            parse_mode="html",
        )
        return None, None

    return sites, proxy

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID
# ═══════════════════════════════════════════════════════════════════════════════
# RESULT MESSAGE BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

def _build_hit_message(result: dict, bin_info: tuple) -> str:
    brand, bin_type, level, bank, country, flag = bin_info
    emoji       = "✅" if result["status"] == "Charged" else "🔥"
    status_text = "𝐂𝐡𝐚𝐫𝐠𝐞𝐝" if result["status"] == "Charged" else "𝐋𝐢𝐯𝐞"
return (
    f"<b>🐺 𝐀ᴇʀᴏ𝐗</b>\n"
    f"<b>━━━━━━━━━━━━━━━━━</b>\n"
    f"<b>⚡ 𝐇ɪᴛ 𝐅ᴏᴜɴᴅ!</b>\n"
    f"<blockquote>{emoji} 𝐒ᴛᴀᴛᴜ𝐬: {status_text}</blockquote>\n"
    f"<blockquote>💳 𝐂ᴀʀᴅ: <code>{result['card']}</code></blockquote>\n"
    f"<blockquote>📝 𝐑ᴇ𝐬ᴘᴏɴ𝐬ᴇ: {result['message'][:150]}</blockquote>\n"
    f"<blockquote>🌐 𝐆ᴀᴛᴇᴡᴀʏ: 🔥 {result.get('gateway','Unknown')} | 💰 {result.get('price','-')}</blockquote>\n"
    f"<b>━━━━━━━━━━━━━━━━━</b>\n"
    f"<b>⚡ 𝐁ɪɴ 𝐈ɴғᴏ</b>\n"
    f"<pre>𝐁ɪɴ : {brand} - {bin_type} - {level}\n"
    f"𝐁ᴀɴᴋ : {bank}\n"
    f"𝐂ᴏᴜɴᴛʀʏ : {country} {flag}</pre>\n"
    f"<b>━━━━━━━━━━━━━━━━━</b>\n\n"
    f'😵‍💫 <b>𝐁ᴏᴛ 𝐁ʏ: <a href="tg://user?id=1817159548">𝐙ᴇᴜ𝐬</a></b>'
)


def _build_progress_message(results: dict, checked: int) -> str:
    elapsed = int(time.time() - results["start_time"])
    gateway = (
        results["charged"][0]["gateway"]
        if results["charged"]
        else (results["approved"][0]["gateway"] if results["approved"] else "Unknown")
    )
    return (
    f"<b>🐺 𝐀ᴇʀᴏ𝐗</b>\n"
    f"<b>━━━━━━━━━━━━━━━━━</b>\n"
    f"<b>⚡💠 𝐏ʀᴏɢʀᴇ𝐬𝐬</b>\n"
    f"<blockquote>"
    f"💳 𝐓ᴏᴛᴀʟ: {results['total']} | "
    f"✅ {len(results['charged'])} | "
    f"🔥 {len(results['approved'])} | "
    f"❌ {len(results['dead'])}"
    f"</blockquote>\n"
    f"<blockquote>📊 𝐂ʜᴇᴄᴋᴇᴅ: {checked}/{results['total']}</blockquote>\n"
    f"<blockquote>🌐 𝐆ᴀᴛᴇᴡᴀʏ: 🔥 {gateway}</blockquote>\n"
    f"<blockquote>⏱️ 𝐓ɪᴍᴇ: {format_elapsed(elapsed)}</blockquote>\n"
    f"<b>━━━━━━━━━━━━━━━━━</b>"
)

def _build_final_summary(results: dict) -> str:
    elapsed = int(time.time() - results["start_time"])
    gateway = (
        results["charged"][0]["gateway"]
        if results["charged"]
        else (results["approved"][0]["gateway"] if results["approved"] else "Unknown")
    )
    hits_text = ""
    for r in results["charged"][:5]:
        hits_text += f"✅ <code>{r['card']}</code>\n"
    for r in results["approved"][:5]:
        hits_text += f"🔥 <code>{r['card']}</code>\n"
    if not hits_text:
        hits_text = "No hits found"

    return (
    f"<b>🐺 𝐀ᴇʀᴏ𝐗</b>\n"
    f"<b>━━━━━━━━━━━━━━━━━</b>\n"
    f"<b>⚡💠 𝐑ᴇ𝐬ᴜʟᴛ𝐬</b>\n"
    f"<blockquote>💳 𝐓ᴏᴛᴀʟ: {results['total']} | ✅ {len(results['charged'])} | "
    f"🔥 {len(results['approved'])} | ❌ {len(results['dead'])}</blockquote>\n"
    f"<blockquote>🌐 𝐆ᴀᴛᴇᴡᴀʏ: 🔥 {gateway}</blockquote>\n"
    f"<blockquote>⏱️ 𝐓ɪᴍᴇ: {format_elapsed(elapsed)}</blockquote>\n"
    f"<b>━━━━━━━━━━━━━━━━━</b>\n"
    f"<b>🎯💠 𝐇ɪᴛ𝐬</b>\n"
    f"<blockquote>{hits_text}</blockquote>\n"
    f"<b>━━━━━━━━━━━━━━━━━</b>\n\n"
    f'😵‍💫 <b>𝐁ᴏᴛ 𝐁ʏ: <a href="tg://user?id=1817159548">𝐙ᴇᴜ𝐬</a></b>'
)

# ═══════════════════════════════════════════════════════════════════════════════
# NOTIFICATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

async def _send_realtime_hit(user_id: int, result: dict) -> None:
    bin_info = await get_bin_info(result["card"].split("|")[0])
    try:
        await bot.send_message(
            user_id,
            premium_emoji(_build_hit_message(result, bin_info)),
            parse_mode="html",
        )
    except Exception:
        pass


async def _update_progress(user_id: int, message_id: int, results: dict, checked: int) -> None:
    buttons = _kb_progress(f"{user_id}_{message_id}")
    try:
        await bot.edit_message(
            user_id,
            message_id,
            premium_emoji(_build_progress_message(results, checked)),
            buttons=buttons,
            parse_mode="html",
        )
    except Exception:
        pass


async def _send_final_results(user_id: int, results: dict) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = f"shopiii_{user_id}_{timestamp}.txt"

    async with aiofiles.open(filename, "w") as f:
        await f.write("=" * 70 + "\n")
        await f.write("⚡💳 CC CHECKER RESULTS 💳⚡\n")
        await f.write("Format: CC | Gateway | Price | Message | Site\n")
        await f.write("=" * 70 + "\n\n")
        await f.write(f"✅ CHARGED ({len(results['charged'])}):\n" + "-" * 70 + "\n")
        for r in results["charged"]:
            await f.write(f"{r['card']} | {r.get('gateway','Unknown')} | {r.get('price','-')} | {r['message'][:100]} | {r.get('site','Unknown')}\n")
        await f.write(f"\n🔥 APPROVED ({len(results['approved'])}):\n" + "-" * 70 + "\n")
        for r in results["approved"]:
            await f.write(f"{r['card']} | {r.get('gateway','Unknown')} | {r.get('price','-')} | {r['message'][:100]} | {r.get('site','Unknown')}\n")
        await f.write(f"\n❌ DEAD ({len(results['dead'])}):\n" + "-" * 70 + "\n")
        for r in results["dead"]:
            await f.write(f"{r['card']} | {r.get('gateway','Unknown')} | {r.get('price','-')} | {r['message'][:100]} | {r.get('site','Unknown')}\n")

    await bot.send_message(
        user_id,
        premium_emoji(_build_final_summary(results)),
        file=filename,
        parse_mode="html",
    )
    try:
        os.remove(filename)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# /start — MAIN MENU
# ═══════════════════════════════════════════════════════════════════════════════

@bot.on(events.NewMessage(pattern="/start"))
async def cmd_start(event):
    sender = event.sender
    try:
        if sender is None:
            sender = await event.get_sender()
        await ensure_user(
            event.sender_id,
            username=getattr(sender, "username", None),
            first_name=getattr(sender, "first_name", None),
        )
    except Exception:
        pass

    first_name = getattr(sender, "first_name", None) or "User"
    await event.reply(
        premium_emoji(_txt_main(first_name)),
        buttons=_kb_main(),
        parse_mode="html",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACK QUERY — MENU NAVIGATION
# ═══════════════════════════════════════════════════════════════════════════════

@bot.on(events.CallbackQuery(pattern=b"menu:main"))
async def cb_menu_main(event):
    sender = await event.get_sender()
    first_name = getattr(sender, "first_name", None) or "User"
    await event.edit(
        premium_emoji(_txt_main(first_name)),
        buttons=_kb_main(),
        parse_mode="html",
    )


@bot.on(events.CallbackQuery(pattern=b"menu:checker"))
async def cb_menu_checker(event):
    await event.edit(
        premium_emoji(_txt_checker()),
        buttons=_kb_checker(),
        parse_mode="html",
    )


@bot.on(events.CallbackQuery(pattern=b"menu:shopify"))
async def cb_menu_shopify(event):
    await event.edit(
        premium_emoji(_txt_shopify()),
        buttons=_kb_shopify(),
        parse_mode="html",
    )


@bot.on(events.CallbackQuery(pattern=b"menu:proxy"))
async def cb_menu_proxy(event):
    text = await _txt_proxy(event.sender_id)
    await event.edit(
        premium_emoji(text),
        buttons=_kb_proxy(),
        parse_mode="html",
    )


@bot.on(events.CallbackQuery(pattern=b"menu:profile"))
async def cb_menu_profile(event):
    text = await _txt_profile(event.sender_id)
    await event.edit(
        premium_emoji(text),
        buttons=_kb_profile(),
        parse_mode="html",
    )


@bot.on(events.CallbackQuery(pattern=b"menu:analytics"))
async def cb_menu_analytics(event):
    text = await _txt_analytics(event.sender_id)
    await event.edit(
        premium_emoji(text),
        buttons=_kb_back_profile(),
        parse_mode="html",
    )


@bot.on(events.CallbackQuery(pattern=b"menu:help"))
async def cb_menu_help(event):
    await event.edit(
        premium_emoji(_txt_help()),
        buttons=_kb_back_main(),
        parse_mode="html",
    )


@bot.on(events.CallbackQuery(pattern=b"noop"))
async def cb_noop(event):
    await event.answer("🚧 Coming Soon!", alert=False)


# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACK QUERY — PROXY INLINE ACTIONS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.on(events.CallbackQuery(pattern=b"proxy:set"))
async def cb_proxy_set(event):
    await event.answer()
    await bot.send_message(
        event.sender_id,
        premium_emoji(
            "📡 <b>Set Your Proxy</b>\n\n"
            "Send your proxy using the command:\n"
            "<code>/addproxy ip:port:user:pass</code>"
        ),
        parse_mode="html",
    )


@bot.on(events.CallbackQuery(pattern=b"proxy:view"))
async def cb_proxy_view(event):
    proxy = await get_proxy(event.sender_id)
    if proxy:
        parts = proxy.split(":")
        display = f"<code>{parts[0]}:{parts[1]}:***:***</code>" if len(parts) >= 2 else f"<code>{proxy}</code>"
        msg = f"📡 <b>Your Proxy:</b>\n\n{display}"
    else:
        msg = "❌ <b>No proxy set.</b>\n\nUse <code>/addproxy ip:port:user:pass</code>"
    await event.answer()
    await bot.send_message(event.sender_id, premium_emoji(msg), parse_mode="html")


@bot.on(events.CallbackQuery(pattern=b"proxy:remove"))
async def cb_proxy_remove(event):
    proxy = await get_proxy(event.sender_id)
    if not proxy:
        await event.answer("❌ No proxy set!", alert=False)
        return

    await remove_proxy(event.sender_id)

    # Refresh the proxy menu inline
    text = await _txt_proxy(event.sender_id)
    await event.edit(
        premium_emoji(text),
        buttons=_kb_proxy(),
        parse_mode="html",
    )
    await event.answer("✅ Proxy removed!")


@bot.on(events.CallbackQuery(pattern=b"proxy:check"))
async def cb_proxy_check(event):
    proxy = await get_proxy(event.sender_id)
    if not proxy:
        await event.answer("❌ No proxy set!", alert=True)
        return

    await event.answer("🔄 Testing your proxy…")
    result = await test_proxy(proxy)

    if result["status"] == "alive":
        msg = f"✅ <b>Proxy is ALIVE!</b>\n\n<code>{proxy}</code>"
    else:
        msg = f"❌ <b>Proxy is DEAD!</b>\n\n<code>{proxy}</code>"

    await bot.send_message(event.sender_id, premium_emoji(msg), parse_mode="html")


# ═══════════════════════════════════════════════════════════════════════════════
# CHECKER CALLBACKS (Pause / Resume / Stop)
# ═══════════════════════════════════════════════════════════════════════════════

@bot.on(events.CallbackQuery(pattern=b"pause"))
async def cb_pause(event):
    session_key = f"{event.sender_id}_{event.message_id}"
    if session_key in active_sessions:
        active_sessions[session_key]["paused"] = True
        await event.answer(premium_emoji("⏸️ Paused"))


@bot.on(events.CallbackQuery(pattern=b"resume"))
async def cb_resume(event):
    session_key = f"{event.sender_id}_{event.message_id}"
    if session_key in active_sessions:
        active_sessions[session_key]["paused"] = False
        await event.answer(premium_emoji("▶️ Resumed"))


@bot.on(events.CallbackQuery(pattern=b"stop"))
async def cb_stop(event):
    session_key = f"{event.sender_id}_{event.message_id}"
    if session_key in active_sessions:
        del active_sessions[session_key]
        await event.answer(premium_emoji("🛑 Stopped"))
        await event.edit(
            premium_emoji("😡 <b>Checking stopped by user.</b>"),
            parse_mode="html",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# /sh — SINGLE CARD CHECK  (alias: /cc)
# ═══════════════════════════════════════════════════════════════════════════════

async def _do_single_check(event):
    """Shared logic for /sh and /cc commands."""
    user_id = event.sender_id

    if not await _ensure_and_check_premium(event):
        return

    sites, proxy = await _require_sites_and_proxy(event, user_id)
    if sites is None:
        return

    raw_input = event.message.text.split(" ", 1)
    if len(raw_input) < 2 or not raw_input[1].strip():
        await event.reply(
            premium_emoji("❌ Usage: <code>/sh card|mm|yy|cvv</code>"),
            parse_mode="html",
        )
        return

    cards = extract_cc(raw_input[1].strip())
    if not cards:
        await event.reply(
            premium_emoji("❌ Invalid CC format. Use: <code>card|mm|yy|cvv</code>"),
            parse_mode="html",
        )
        return

    card = cards[0]
    status_msg = await event.reply(
        premium_emoji(
        f"<b>🐺 𝐀ᴇʀᴏ𝐗</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━</b>\n"
        f"<b>⚡💠 𝐂ʜᴇᴄᴋɪɴɢ...</b>\n"
        f"<blockquote>💳 𝐂ᴀʀᴅ: <code>{card}</code></blockquote>\n"
        f"<b>━━━━━━━━━━━━━━━━━</b>"
    
        ),
        parse_mode="html",
    )

    try:
        result   = await check_card_with_retry(card, sites, proxy, max_retries=3)
        bin_info = await get_bin_info(card.split("|")[0])
        brand, bin_type, level, bank, country, flag = bin_info

        status_map = {
            "Charged":  ("✅", "𝐂𝐡𝐚𝐫𝐠𝐞𝐝"),
            "Approved": ("🔥", "𝐋𝐢𝐯𝐞"),
        }
        status_emoji, status_text = status_map.get(result["status"], ("❌", "𝐃𝐞𝐚𝐝"))

    final_resp = (
    f"<b>🐺 𝐀ᴇʀᴏ𝐗</b>\n"
    f"<b>━━━━━━━━━━━━━━━━━</b>\n"
    f"<b>⚡💠 𝐑ᴇ𝐬ᴜʟᴛ𝐬</b>\n"
    f"<blockquote>{status_emoji} 𝐒ᴛᴀᴛᴜ𝐬: {status_text}</blockquote>\n"
    f"<blockquote>💳 𝐂ᴀʀᴅ: <code>{result['card']}</code></blockquote>\n"
    f"<blockquote>📝 𝐑ᴇ𝐬ᴘᴏɴ𝐬ᴇ: {result['message'][:150]}</blockquote>\n"
    f"<blockquote>🌐 𝐆ᴀᴛᴇᴡᴀʏ: 🔥 {result.get('gateway','Unknown')} | 💰 {result.get('price','-')}</blockquote>\n"
    f"<b>━━━━━━━━━━━━━━━━━</b>\n"
    f"<b>🎯💠 𝐁ɪɴ 𝐈ɴғᴏ</b>\n"
    f"<pre>"
    f"𝐁ɪɴ : {brand} - {bin_type} - {level}\n"
    f"𝐁ᴀɴᴋ : {bank}\n"
    f"𝐂ᴏᴜɴᴛʀʏ : {country} {flag}"
    f"</pre>\n"
    f"<b>━━━━━━━━━━━━━━━━━</b>\n\n"

        )
        await status_msg.edit(premium_emoji(final_resp), parse_mode="html")

    except Exception as exc:
        await status_msg.edit(premium_emoji(f"❌ Error: {exc}"), parse_mode="html")


@bot.on(events.NewMessage(pattern=r"^/sh\s+"))
async def cmd_sh(event):
    await _do_single_check(event)


@bot.on(events.NewMessage(pattern=r"^/cc\s+"))
async def cmd_cc(event):
    await _do_single_check(event)


# ═══════════════════════════════════════════════════════════════════════════════
# /msh — MULTI-CARD CHECK FROM TEXT
# ═══════════════════════════════════════════════════════════════════════════════

@bot.on(events.NewMessage(pattern=r"^/msh"))
async def cmd_msh(event):
    user_id = event.sender_id

    if not await _ensure_and_check_premium(event):
        return

    text = event.message.text
    # Cards come after the command on the same message (one per line)
    body = text.split("\n", 1)[1].strip() if "\n" in text else ""
    if not body:
        await event.reply(
            premium_emoji(
                "❌ <b>Usage:</b>\n"
                "<code>/msh\n"
                "card1|mm|yy|cvv\n"
                "card2|mm|yy|cvv\n"
                "...</code>"
            ),
            parse_mode="html",
        )
        return

    await _run_bulk_check(event, body, user_id)


# ═══════════════════════════════════════════════════════════════════════════════
# /shtxt — BULK CHECK FROM .TXT FILE  (alias: /chk)
# ═══════════════════════════════════════════════════════════════════════════════

async def _run_bulk_check(event, content: str, user_id: int):
    """Core bulk-check logic shared by /msh and /shtxt."""
    sites, proxy = await _require_sites_and_proxy(event, user_id)
    if sites is None:
        return

    cards = extract_cc(content)
    if not cards:
        await event.reply(premium_emoji("😡 No valid cards found."))
        return

    if len(cards) > 5000:
        cards = cards[:5000]

    total_cards = len(cards)
    status_msg = await event.reply(
        premium_emoji(f"🫦 Starting check for <b>{total_cards}</b> cards..."),
        parse_mode="html",
    )

    session_key = f"{user_id}_{status_msg.id}"
    active_sessions[session_key] = {"paused": False}

    all_results = {
        "charged":    [],
        "approved":   [],
        "dead":       [],
        "total":      total_cards,
        "checked":    0,
        "start_time": time.time(),
    }

    try:
        queue: asyncio.Queue = asyncio.Queue()
        for c in cards:
            queue.put_nowait(c)

        last_update = [time.time()]

        async def worker():
            while not queue.empty() and session_key in active_sessions:
                state = active_sessions.get(session_key)
                if not state:
                    break
                while state.get("paused", False):
                    await asyncio.sleep(1)
                    state = active_sessions.get(session_key)
                    if not state:
                        return
                try:
                    card = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                cur_sites = await get_all_sites()
                cur_proxy = await get_proxy(user_id)
                if not cur_sites or not cur_proxy:
                    break

                res = await check_card_with_retry(card, cur_sites, cur_proxy, max_retries=1)
                all_results["checked"] += 1

                if res["status"] == "Charged":
                    all_results["charged"].append(res)
                    await _send_realtime_hit(user_id, res)
                elif res["status"] == "Approved":
                    all_results["approved"].append(res)
                    await _send_realtime_hit(user_id, res)
                else:
                    all_results["dead"].append(res)

                queue.task_done()

                now = time.time()
                if now - last_update[0] >= 1.0:
                    last_update[0] = now
                    if session_key in active_sessions:
                        await _update_progress(user_id, status_msg.id, all_results, all_results["checked"])

        workers = [asyncio.create_task(worker()) for _ in range(10)]
        while workers:
            if session_key not in active_sessions:
                for w in workers:
                    if not w.done():
                        w.cancel()
                break
            done, pending = await asyncio.wait(workers, timeout=1.0)
            workers = list(pending)

        if session_key in active_sessions:
            await _update_progress(user_id, status_msg.id, all_results, all_results["checked"])

    except Exception as exc:
        await bot.send_message(user_id, premium_emoji(f"An error occurred: {exc}"))

    finally:
        if session_key in active_sessions:
            del active_sessions[session_key]
        try:
            await save_log(
                user_id=user_id,
                total=all_results["total"],
                charged=len(all_results["charged"]),
                approved=len(all_results["approved"]),
            )
        except Exception:
            pass
        try:
            await status_msg.delete()
        except Exception:
            pass
        await _send_final_results(user_id, all_results)


async def _handle_txt_check(event):
    """Shared logic for /shtxt and /chk."""
    user_id = event.sender_id

    if not await _ensure_and_check_premium(event):
        return

    if not event.reply_to_msg_id:
        await event.reply(premium_emoji("😡 Please reply to a <code>.txt</code> file containing cards."), parse_mode="html")
        return

    reply_msg = await event.get_reply_message()
    if not reply_msg.file or not reply_msg.file.name.endswith(".txt"):
        await event.reply(premium_emoji("😡 Please reply to a <code>.txt</code> file."), parse_mode="html")
        return

    status_msg = await event.reply(premium_emoji("🫆 Processing your file..."))
    file_path  = await reply_msg.download_media()

    async with aiofiles.open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = await f.read()

    try:
        os.remove(file_path)
    except Exception:
        pass

    try:
        await status_msg.delete()
    except Exception:
        pass

    await _run_bulk_check(event, content, user_id)


@bot.on(events.NewMessage(pattern="/shtxt"))
async def cmd_shtxt(event):
    await _handle_txt_check(event)


@bot.on(events.NewMessage(pattern="/chk"))
async def cmd_chk(event):
    await _handle_txt_check(event)


# ═══════════════════════════════════════════════════════════════════════════════
# PROXY COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.on(events.NewMessage(pattern=r"^/addproxy"))
async def cmd_addproxy(event):
    if not await _ensure_and_check_premium(event):
        return

    parts = event.message.text.strip().split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        await event.reply(
            premium_emoji("❌ Usage: <code>/addproxy ip:port:user:pass</code>"),
            parse_mode="html",
        )
        return

    proxy = parts[1].strip().splitlines()[0].strip()
    await set_proxy(event.sender_id, proxy)
    await event.reply(
        premium_emoji(f"✅ <b>Proxy Set!</b>\n\n<code>{proxy}</code>"),
        parse_mode="html",
    )


@bot.on(events.NewMessage(pattern=r"^/getproxy$"))
async def cmd_getproxy(event):
    if not await _ensure_and_check_premium(event):
        return

    proxy = await get_proxy(event.sender_id)
    if not proxy:
        await event.reply(
            premium_emoji("❌ No proxy set.\n\nUse <code>/addproxy ip:port:user:pass</code>"),
            parse_mode="html",
        )
        return
    await event.reply(
        premium_emoji(f"📋 <b>Your Proxy:</b>\n\n<code>{proxy}</code>"),
        parse_mode="html",
    )


@bot.on(events.NewMessage(pattern=r"^/rmproxy$"))
async def cmd_rmproxy(event):
    if not await _ensure_and_check_premium(event):
        return

    if not await get_proxy(event.sender_id):
        await event.reply(premium_emoji("❌ You have no proxy set."), parse_mode="html")
        return
    await remove_proxy(event.sender_id)
    await event.reply(premium_emoji("✅ <b>Proxy Removed!</b>"), parse_mode="html")


@bot.on(events.NewMessage(pattern=r"^/chkproxy$"))
async def cmd_chkproxy(event):
    if not await _ensure_and_check_premium(event):
        return

    proxy = await get_proxy(event.sender_id)
    if not proxy:
        await event.reply(
            premium_emoji("❌ No proxy set.\n\nUse <code>/addproxy ip:port:user:pass</code> first."),
            parse_mode="html",
        )
        return

    status_msg = await event.reply(
        premium_emoji(f"🔄 Testing proxy: <code>{proxy}</code>..."),
        parse_mode="html",
    )
    result = await test_proxy(proxy)

    if result["status"] == "alive":
        await status_msg.edit(
            premium_emoji(f"✅ <b>Proxy is ALIVE!</b>\n\n<code>{proxy}</code>"),
            parse_mode="html",
        )
    else:
        await status_msg.edit(
            premium_emoji(f"❌ <b>Proxy is DEAD!</b>\n\n<code>{proxy}</code>"),
            parse_mode="html",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SITE MANAGEMENT COMMANDS (Admin)
# ═══════════════════════════════════════════════════════════════════════════════

@bot.on(events.NewMessage(pattern=r"^/addsite\s+"))
async def cmd_addsite(event):
    if not await _ensure_and_check_premium(event):
        return

    url = event.message.text.split(" ", 1)[1].strip()
    if not url:
        await event.reply(
            premium_emoji("❌ Usage: <code>/addsite https://example.com</code>"),
            parse_mode="html",
        )
        return

    await add_site(url)
    count = await site_count()
    await event.reply(
        premium_emoji(
            f"✅ <b>Site Added!</b>\n\n<code>{url}</code>\n\n📊 Total alive sites: {count}"
        ),
        parse_mode="html",
    )


@bot.on(events.NewMessage(pattern=r"^/rm\s+"))
async def cmd_rm(event):
    if not await _ensure_and_check_premium(event):
        return

    url = event.message.text.split(" ", 1)[1].strip()
    if not url:
        await event.reply(
            premium_emoji("❌ Usage: <code>/rm https://site.com</code>"),
            parse_mode="html",
        )
        return

    await remove_site(url)
    await event.reply(
        premium_emoji(f"✅ <b>Site Removed!</b>\n\n<code>{url}</code> has been deleted."),
        parse_mode="html",
    )


@bot.on(events.NewMessage(pattern="/site"))
async def cmd_site(event):
    user_id = event.sender_id

    if not await _ensure_and_check_premium(event):
        return

    proxy = await get_proxy(user_id)
    if not proxy:
        await event.reply(
            premium_emoji("❌ No proxy set. Use <code>/addproxy ip:port:user:pass</code> first."),
            parse_mode="html",
        )
        return

    sites = await get_all_sites()
    if not sites:
        await event.reply(premium_emoji("❌ No sites in database. Nothing to check."))
        return

    status_msg = await event.reply(
        premium_emoji(f"🔥 Checking <b>{len(sites)}</b> sites..."),
        parse_mode="html",
    )

    alive, dead = [], []

    try:
        for i in range(0, len(sites), 10):
            batch   = sites[i : i + 10]
            tasks   = [test_site(site, proxy) for site in batch]
            results = await asyncio.gather(*tasks)

            for res in results:
                if res["status"] == "alive":
                    alive.append(res["site"])
                else:
                    dead.append(res["site"])
                    await mark_site_dead(res["site"])

            await status_msg.edit(
                premium_emoji(
                    f"🔥 Checking sites...\n\n"
                    f"<b>Checked:</b> {len(alive)+len(dead)}/{len(sites)}\n"
                    f"<b>Alive:</b> {len(alive)}\n"
                    f"<b>Dead:</b> {len(dead)}"
                ),
                parse_mode="html",
            )

        await status_msg.edit(
            premium_emoji(
                f"✅ <b>Site Check Complete!</b>\n\n"
                f"<b>Total:</b> {len(sites)}\n"
                f"<b>Alive:</b> {len(alive)}\n"
                f"<b>Marked Dead:</b> {len(dead)}"
            ),
            parse_mode="html",
        )

    except Exception as exc:
        await status_msg.edit(premium_emoji(f"❌ Error during site check: {exc}"))


# ══════════════
# ADMIN COMMANDS
# ══════════════

@bot.on(events.NewMessage(pattern=r"^/elevate\s+"))
async def cmd_elevate(event):
    if not is_owner(event.sender_id):
        return

    try:
        args = event.raw_text.split()

        if len(args) != 3:
            await event.reply(
                "Usage:\n"
                "<code>/elevate user_id core</code>\n"
                "<code>/elevate user_id nova</code>\n"
                "<code>/elevate user_id monarch</code>",
                parse_mode="html",
            )
            return

        user_id = int(args[1])
        plan = args[2].lower()

        if plan not in ["core", "nova", "monarch"]:
            await event.reply(
                "❌ Invalid plan.\n\nUse: core / nova / monarch",
                parse_mode="html",
            )
            return

        await set_plan(user_id, plan)

        await event.reply(
            f"✅ Premium activated.\n\n"
            f"👤 User: <code>{user_id}</code>\n"
            f"📦 Plan: <b>{plan.capitalize()}</b>",
            parse_mode="html",
        )

    except Exception as e:
        await event.reply(
            f"❌ Error:\n<code>{e}</code>",
            parse_mode="html",
        )



# ══════════════════════
# ENTRY POINT
# ══════════════════════

print("✅ Bot started successfully!")
bot.run_until_disconnected()
