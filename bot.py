import asyncio
import os
import time
from datetime import datetime

import aiofiles
from telethon import Button, TelegramClient, events

from config import API_ID, API_HASH, BOT_TOKEN, OWNER_ID, ADMIN_IDS
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
    remove_single_proxy,
    set_proxy,
    consume_credit,
    update_stats,
    add_proxies_bulk,
    get_proxy_count,
    get_all_user_proxies,
)

from utils.binlookup import get_bin_info
from utils.checker import check_card_with_retry, test_proxy, test_site
from utils.emojis import premium_emoji
from utils.helpers import extract_cc, format_elapsed

# ─── Bot Client ───────────────────────────────────────────────────────────────

bot = TelegramClient("checker_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Active bulk-checking sessions: {session_key: {'paused': bool}}
active_sessions: dict = {}
# Temporary storage for export buttons
SHOPIFY_SESSION_RESULTS: dict = {}


# ═══════════════════════════════════════════════════════════════════════════════
# INLINE KEYBOARD BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

def _kb_main() -> list:
    return [
        [Button.inline("💳 𝐂ʜᴇᴄᴋᴇʀ", b"menu:checker"),  Button.inline("📡  𝐏ʀᴏx𝐲",   b"menu:proxy")],
        [Button.inline("👤  𝐏ʀᴏғɪ𝐋𝐄", b"menu:profile"),  Button.inline("❓  𝐇ᴇʟᴘ",    b"menu:help")],
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
        [Button.inline("➕ Add Proxy", b"proxy_add"), Button.inline("🔄 Test Proxy", b"proxy_test")],
        [Button.inline("📋 View Proxies", b"proxy_view"), Button.inline("🗑️ Remove All", b"proxy_remove")],
        [Button.inline("🔙 Back", b"menu:main")],
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


def _kb_progress(session_key: str, results: dict = None) -> list:
    charged = len(results['charged']) if results else 0
    approved = len(results['approved']) if results else 0
    dead = len(results['dead']) if results else 0
    errors = len(results.get('errors', [])) if results else 0
    total = results['total'] if results else 0
    checked = results['checked'] if results else 0
    pct = int((checked / total) * 100) if total > 0 else 0

    user_id = session_key.split('_')[0] if session_key else '0'

    return [
        [Button.inline(f"📋 {checked}/{total} ({pct}%)", b"noop")],
        [Button.inline(f"✅ Charged: {charged}", f"export_charged:{user_id}".encode()),
         Button.inline(f"🔥 Approved: {approved}", f"export_approved:{user_id}".encode())],
        [Button.inline(f"⚫ Insuff: 0", b"noop"),
         Button.inline(f"❌ Declined: {dead}", f"export_declined:{user_id}".encode())],
        [Button.inline(f"⚠️ Errors: {errors}", f"export_errors:{user_id}".encode())],
        [Button.inline("⏸️ Pause", b"pause"), Button.inline("▶️ Resume", b"resume")],
        [Button.inline("🛑 Stop", b"stop")],
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
    count = await get_proxy_count(user_id)
    if count > 0:
        status = f"✅ <b>\ud835\udc77\ud835\udc93\ud835\udc90\ud835\udc99\ud835\udc9a \ud835\udc79\ud835\udc86\ud835\udc82\ud835\udc85\ud835\udc9a</b>\n\U0001f4ca {count} proxies loaded"
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

    username = (user or {}).get("username", f"user_{user_id}")
    first_name = (user or {}).get("first_name", "—")
    plan = "⭐ Premium" if (user or {}).get("premium") else "🔓 Free"
    join_raw = (user or {}).get("join_date")
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
        f"📆 <b>𝐉ᴏɪɴᴇ𝐃:</b> {join_date}"
        f"</blockquote>\n"
        "<b>━━━━━━━━━━━━━━━━━</b>\n"
        "<b>📊 𝐒ᴛᴀᴛ𝐬</b>\n\n"
        f"<blockquote>"
        f"📅 <b>𝐓ᴏ𝐓ᴀʟ 𝐂ʜᴇ𝐂ᴋ𝐬:</b> {stats['total_checked']:,}\n"
        f"📸 <b>𝐂ʜᴀʀ𝐠ᴇᴅ:</b> {stats['total_charged']:,}\n"
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
        "<b>\ud83d\udc3a \ud835\udc00\u1d07\u0280\u1d0f\ud835\udc17</b>\n"
        "<b>\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501</b>\n"
        "<b>\u2753 \ud835\udc07\u1d07\ud835\udc0b\u1d18 & \ud835\udc02\u1d0f\u1d0d\u1d0d\u1d00\u0274\u1d05\ud835\udc2c</b>\n\n"
        "<blockquote>Quick Command Reference.</blockquote>\n\n"
        "<b>\ud83d\udcb3 Checker</b>\n"
        "<blockquote>"
        "/sh <code>card|mm|yy|cvv</code> \u2014 Single Check\n"
        "/msh \u2014 Multi Check\n"
        "/shtxt \u2014 Bulk Check"
        "</blockquote>\n\n"
        "<b>📡 Proxy</b>\n"
        "<blockquote>"
        "/proxy \u2014 Open Proxy Menu (Inline Buttons)\n"
        "/addpx <code>ip:port:user:pass</code> \u2014 Add Proxy\n"
        "  \u21b3 Paste multi-line or reply to .txt for bulk\n"
        "/viewpx \u2014 View Proxies (.txt)\n"
        "/rmpx \u2014 Remove Proxies\n"
        "/testpx \u2014 Test Proxy"
        "</blockquote>\n\n"

        "<b>\ud83d\udccc Card Format</b>\n"
        "<blockquote><code>card|mm|yyyy|cvv</code></blockquote>\n"
        "<b>\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501</b>\n"
        '\ud83d\ude35\u200d\ud83d\udcab <b>Bot By ~ <a href="tg://user?id=1817159548">Zeus</a></b>'
    )
# ═══════════════════════════════════════════════════════════════════════════════

async def _ensure_and_check_premium(event) -> bool:
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
    sites = await get_all_sites()
    if not sites:
        await event.reply(
            premium_emoji("❌ No sites available. Please contact admin."),
            parse_mode="html",
        )
        return None, None

    proxies = await get_all_user_proxies(user_id)
    if not proxies:
        await event.reply(
            premium_emoji(
                "❌ No proxy set.\n\nUse <code>/addproxy ip:port:user:pass</code> to add your proxy."
            ),
            parse_mode="html",
        )
        return None, None

    return sites, proxies

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in ADMIN_IDS

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
        f"<blockquote>{emoji} 𝐒ᴛᴀᴛ𝐮𝐬: {status_text}</blockquote>\n"
        f"<blockquote>💳 𝐂ᴀʀᴅ: <code>{result['card']}</code></blockquote>\n"
        f"<blockquote>📝 𝐑ᴇ𝐬ᴘᴏɴ𝐬ᴇ: {result['message'][:150]}</blockquote>\n"
        f"<blockquote>🌐 𝐆ᴀᴛᴇᴡᴀʏ: 🔥 {result.get('gateway','Unknown')} | 💰 {result.get('price','-')}</blockquote>\n"
        f"<b>━━━━━━━━━━━━━━━━━</b>\n"
        f"<b>⚡ 𝐁ɪɴ 𝐈ɴғᴏ</b>\n"
        f"<pre>𝐁ɪɴ : {brand} - {bin_type} - {level}\n"
        f"𝐁ᴀɴᴋ : {bank}\n"
        f"𝐂ᴏᴜɴ𝐓ʀʏ : {country} {flag}</pre>\n"
        f"<b>━━━━━━━━━━━━━━━━━</b>\n\n"
        f'😵‍💫 <b>𝐁ᴏᴛ 𝐁ʏ: <a href="tg://user?id=1817159548">𝐙ᴇ𝐮𝐬</a></b>'
    )


def _build_progress_message(results: dict, checked: int) -> str:
    elapsed = int(time.time() - results["start_time"])
    gateway = (
        results["charged"][0]["gateway"]
        if results["charged"]
        else (results["approved"][0]["gateway"] if results["approved"] else "Unknown")
    )
    last_card = results.get('last_card', 'None')[:16]
    last_resp = results.get('last_response', 'Waiting...')[:16]
    last_price = results.get('last_price', '-')[:7]
    errors_count = len(results.get('errors', []))

    return (
        f"<b>🐺 𝐀ᴇʀᴏ𝐗</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━</b>\n"
        f"<b>⚡💠 𝐏ʀᴏɢʀᴇ𝐬𝐬</b>\n"
        f"<blockquote>"
        f"💳 𝐂ᴀʀᴅ: <code>{last_card}</code>\n"
        f"📝 {last_resp}\n"
        f"💰 {last_price}"
        f"</blockquote>\n"
        f"<blockquote>"
        f"❌ 𝐃ᴇᴄʟɪɴᴇᴅ: {len(results['dead'])}\n"
        f"📊 {checked}/{results['total']}\n"
        f"⏱️ {format_elapsed(elapsed)}"
        f"</blockquote>\n"
        f"<b>━━━━━━━━━━━━━━━━━</b>"
    )

def _build_final_summary(results: dict) -> str:
    elapsed = int(time.time() - results["start_time"])
    gateway = (
        results["charged"][0]["gateway"]
        if results["charged"]
        else (results["approved"][0]["gateway"] if results["approved"] else "Unknown")
    )
    errors_count = len(results.get('errors', []))
    hits_text = ""
    for r in results["charged"][:5]:
        hits_text += f"✅ <code>{r['card']}</code>\n"
    for r in results["approved"][:5]:
        hits_text += f"🔥 <code>{r['card']}</code>\n"
    for r in results.get("insuff", [])[:5]:
        hits_text += f"⚫ <code>{r['card']}</code>\n"
    if not hits_text:
        hits_text = "No hits found"

    return (
        f"<b>🐺 𝐀ᴇʀᴏ𝐗</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━</b>\n"
        f"<b>⚡💠 𝐑ᴇ𝐬ᴜʟ𝐭𝐬</b>\n"
        f"<blockquote>📊 𝐑ᴇ𝐬ᴜʟ𝐭𝐬:\n"
        f"   ┣ ✅ 𝐂ʜᴀʀɢᴇᴅ: {len(results['charged'])}\n"
        f"   ┣ 🔥 𝐀ᴘᴘʀᴏᴠᴇᴅ: {len(results['approved'])}\n"
        f"   ┣ ⚫ 𝐈ɴsᴜғғ: {len(results.get('insuff', []))}\n"
        f"   ┣ ❌ 𝐃ᴇᴄʟɪɴᴇᴅ: {len(results['dead'])}\n"
        f"   ┣ ⚠️ 𝐄ʀʀᴏʀs: {errors_count}\n"
        f"   ┗ 📊 𝐓ᴏᴛᴀʟ: {results['total']}</blockquote>\n"
        f"<blockquote>🌐 𝐆ᴀᴛᴇᴡᴀʏ: 🔥 {gateway}</blockquote>\n"
        f"<blockquote>⏱️ 𝐓ɪᴍᴇ: {format_elapsed(elapsed)}</blockquote>\n"
        f"<b>━━━━━━━━━━━━━━━━━</b>\n"
        f"<b>🎯💠 𝐇ɪᴛ𝐬</b>\n"
        f"<blockquote>{hits_text}</blockquote>\n"
        f"<b>━━━━━━━━━━━━━━━━━</b>\n\n"
        f'😵‍💫 <b>𝐁ᴏᴛ 𝐁ʏ: <a href="tg://user?id=1817159548">𝐙ᴇ𝐮𝐬</a></b>'
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
    session_key = f"{user_id}_{message_id}"
    buttons = _kb_progress(session_key, results)
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
    errors = results.get('errors', [])

    async with aiofiles.open(filename, "w", encoding="utf-8") as f:
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
        await f.write(f"\n⚫ INSUFFICIENT FUNDS ({len(results.get('insuff', []))}):\n" + "-" * 70 + "\n")
        for r in results.get("insuff", []):
            await f.write(f"{r['card']} | {r.get('gateway','Unknown')} | {r.get('price','-')} | {r['message'][:100]} | {r.get('site','Unknown')}\n")
        await f.write(f"\n❌ DECLINED ({len(results['dead'])}):\n" + "-" * 70 + "\n")
        for r in results["dead"]:
            await f.write(f"{r['card']} | {r.get('gateway','Unknown')} | {r.get('price','-')} | {r['message'][:100]} | {r.get('site','Unknown')}\n")
        await f.write(f"\n⚠️ ERRORS ({len(errors)}):\n" + "-" * 70 + "\n")
        for r in errors:
            await f.write(f"{r['card']} | {r.get('gateway','Unknown')} | {r.get('price','-')} | {r['message'][:100]} | {r.get('site','Unknown')}\n")

    # Build final buttons
    buttons = [
        [Button.inline(f"✅ Charged: {len(results['charged'])}", f"export_charged:{user_id}".encode()),
         Button.inline(f"🔥 Approved: {len(results['approved'])}", f"export_approved:{user_id}".encode())],
        [Button.inline(f"⚫ Insuff: {len(results.get('insuff', []))}", f"export_insuff:{user_id}".encode()),
         Button.inline(f"❌ Declined: {len(results['dead'])}", f"export_declined:{user_id}".encode())],
        [Button.inline(f"⚠️ Errors: {len(errors)}", f"export_errors:{user_id}".encode())],
    ]
    if errors:
        buttons.append([Button.inline(f"⚙️ Retry errors ({len(errors)})", f"retry_errors:{user_id}".encode())])

    await bot.send_message(
        user_id,
        premium_emoji(_build_final_summary(results)),
        file=filename,
        buttons=buttons,
        parse_mode="html",
    )
    try:
        os.remove(filename)
    except Exception:
        pass

    # Store results temporarily for export buttons
    SHOPIFY_SESSION_RESULTS[user_id] = results
    # Clean up after 5 minutes
    async def _cleanup():
        await asyncio.sleep(300)
        SHOPIFY_SESSION_RESULTS.pop(user_id, None)
    asyncio.create_task(_cleanup())


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


# ═══════════════════════════════════════════════════════════════════════════════
# CHECKER CALLBACKS (Pause / Resume / Stop)
# ═══════════════════════════════════════════════════════════════════════════════

@bot.on(events.CallbackQuery(pattern=b"pause"))
async def cb_pause(event):
    session_key = f"{event.sender_id}_{event.message_id}"
    if session_key in active_sessions:
        active_sessions[session_key]["paused"] = True
        await event.answer("⏸️ Paused")


@bot.on(events.CallbackQuery(pattern=b"resume"))
async def cb_resume(event):
    session_key = f"{event.sender_id}_{event.message_id}"
    if session_key in active_sessions:
        active_sessions[session_key]["paused"] = False
        await event.answer("▶️ Resumed")


@bot.on(events.CallbackQuery(pattern=b"stop"))
async def cb_stop(event):
    session_key = f"{event.sender_id}_{event.message_id}"
    if session_key in active_sessions:
        del active_sessions[session_key]
        await event.answer("🛑 Stopped")
        await event.edit(
            premium_emoji("😡 <b>Checking stopped by user.</b>"),
            parse_mode="html",
        )


@bot.on(events.CallbackQuery(pattern=r"^export_(charged|approved|insuff|declined|errors):(\d+)"))
async def cb_export_results(event):
    category = event.pattern_match.group(1).decode()
    target_user_id = int(event.pattern_match.group(2).decode())

    if event.sender_id != target_user_id:
        await event.answer("❌ Not your session results!", alert=True)
        return

    if target_user_id not in SHOPIFY_SESSION_RESULTS:
        await event.answer("❌ No results found! Run a check first.", alert=True)
        return

    user_results = SHOPIFY_SESSION_RESULTS[target_user_id]
    
    # map declined to dead
    key = "dead" if category == "declined" else category
    cards_list = user_results.get(key, [])
    
    if not cards_list:
        await event.answer(f"❌ No {category.capitalize()} cards found!", alert=True)
        return

    emoji_map = {
        "charged": "✅",
        "approved": "🔥",
        "insuff": "⚫",
        "declined": "❌",
        "errors": "⚠️"
    }
    emoji = emoji_map.get(category, "❓")
    title = category.upper()
    filename = f"{category}_cards_{target_user_id}.txt"

    content = f"{emoji} {title} CARDS\n"
    content += "=" * 45 + "\n\n"
    for i, item in enumerate(cards_list, 1):
        content += f"[{i}] Card: {item['card']}\n"
        content += f"    Response: {item.get('message', 'N/A')[:150]}\n"
        content += f"    Gateway: {item.get('gateway', 'Unknown')}\n"
        content += f"    Price: {item.get('price', '-')}\n"
        content += "-" * 30 + "\n"
    content += f"\n📊 Total: {len(cards_list)} cards\n"
    content += f"📅 Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    async with aiofiles.open(filename, 'w', encoding='utf-8') as f:
        await f.write(content)

    await event.answer(f"📤 Exporting {len(cards_list)} cards...", alert=False)
    await bot.send_file(
        target_user_id,
        filename,
        caption=premium_emoji(f"<b>{emoji} {category.capitalize()} Cards</b>\n📊 Total: {len(cards_list)} cards")
    )

    try:
        os.remove(filename)
    except Exception:
        pass


@bot.on(events.CallbackQuery(pattern=r"^retry_errors:(\d+)"))
async def cb_retry_errors(event):
    target_user_id = int(event.pattern_match.group(1).decode())

    if event.sender_id != target_user_id:
        await event.answer("❌ Not your session results!", alert=True)
        return

    if target_user_id not in SHOPIFY_SESSION_RESULTS:
        await event.answer("❌ No results found to retry.", alert=True)
        return

    results = SHOPIFY_SESSION_RESULTS[target_user_id]
    errors_list = results.get("errors", [])
    if not errors_list:
        await event.answer("❌ No errors found to retry.", alert=True)
        return

    error_cards = [r["card"] for r in errors_list]
    
    await event.answer("⚙️ Retrying errors...")
    
    try:
        await event.delete()
    except Exception:
        pass

    content = "\n".join(error_cards)
    await _run_bulk_check(event, content, target_user_id)


# ═══════════════════════════════════════════════════════════════════════════════
# /sh — SINGLE CARD CHECK  (alias: /cc)
# ═══════════════════════════════════════════════════════════════════════════════

async def _do_single_check(event):
    user_id = event.sender_id

    if not await _ensure_and_check_premium(event):
        return

    sites, proxies = await _require_sites_and_proxy(event, user_id)
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

    # Consume one credit before checking
    if not await consume_credit(user_id):
        await event.reply(
            premium_emoji("\u274c <b>No credits remaining.</b>\n\nPlease contact admin to refill."),
            parse_mode="html",
        )
        return

    card = cards[0]
    status_msg = await event.reply(
        premium_emoji(
            f"<b>🐺 𝐀ᴇʀᴏ𝐗</b>\n"
            f"<b>━━━━━━━━━━━━━━━━━</b>\n"
            f"<b>⚡💠 𝐂ʜᴇ𝐂ᴋɪɴɢ...</b>\n"
            f"<blockquote>💳 𝐂ᴀʀ𝐃: <code>{card}</code></blockquote>\n"
            f"<b>━━━━━━━━━━━━━━━━━</b>"
        ),
        parse_mode="html",
    )
    try:
        result = await check_card_with_retry(card, sites, proxies, max_retries=20)

        # Track stats based on result
        if result["status"] == "Charged":
            await update_stats(user_id, checks=0, charged=1)
        elif result["status"] in ("Approved", "Insuff"):
            await update_stats(user_id, checks=0, approved=1)
        else:
            await update_stats(user_id, checks=0, dead=1)
        bin_info = await get_bin_info(card.split("|")[0])
        brand, bin_type, level, bank, country, flag = bin_info

        status_map = {
            "Charged": ("✅", "𝐂𝐡𝐚𝐫𝐠𝐞𝐝"),
            "Approved": ("🔥", "𝐋𝐢𝐯𝐞"),
            "Insuff": ("🟢", "𝐈𝐧𝐬𝐮𝐟𝐟𝐢𝐜𝐢𝐞𝐧𝐭 𝐅𝐮𝐧𝐝𝐬"),
        }
        status_emoji, status_text = status_map.get(
            result["status"], ("❌", "𝐃𝐞𝐚𝐝")
        )

        final_resp = (
            f"<b>🐺 𝐀ᴇʀᴏ𝐗</b>\n"
            f"<b>━━━━━━━━━━━━━━━━━</b>\n"
            f"<b>⚡💠 𝐑ᴇ𝐬ᴜ𝐋𝐭𝐬</b>\n"
            f"<blockquote>{status_emoji} 𝐒ᴛᴀᴛ𝐮𝐬: {status_text}</blockquote>\n"
            f"<blockquote>💳 𝐂ᴀʀ𝐃: <code>{result['card']}</code></blockquote>\n"
            f"<blockquote>📝 𝐑ᴇ𝐬ᴘᴏɴ𝐬ᴇ: {result['message'][:150]}</blockquote>\n"
            f"<blockquote>🌐 𝐆ᴀᴛᴇᴡᴀʏ: 🔥 {result.get('gateway','Unknown')} | 💰 {result.get('price','-')}</blockquote>\n"
            f"<b>━━━━━━━━━━━━━━━━━</b>\n"
            f"<b>🎯💠 𝐁ɪɴ 𝐈ɴғᴏ</b>\n"
            f"<pre>"
            f"𝐁ɪɴ : {brand} - {bin_type} - {level}\n"
            f"𝐁ᴀɴᴋ : {bank}\n"
            f"𝐂ᴏᴜɴ𝐓ʀʏ : {country} {flag}"
            f"</pre>\n"
            f"<b>━━━━━━━━━━━━━━━━━</b>\n\n"
            f'😵‍💫 <b>𝐁ᴏᴛ 𝐁ʏ: <a href="tg://user?id=1817159548">𝐙ᴇ𝐮𝐬</a></b>'
        )
        await status_msg.edit(premium_emoji(final_resp), parse_mode="html")
        
    except Exception as exc:
        await status_msg.edit(
            premium_emoji(f"❌ Error: {exc}"),
            parse_mode="html"
        )

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
    sites, proxies = await _require_sites_and_proxy(event, user_id)
    if sites is None:
        return

    cards = extract_cc(content)
    if not cards:
        await event.reply(premium_emoji("😡 No valid cards found."))
        return

    if len(cards) > 5000:
        cards = cards[:5000]

    total_cards = len(cards)
    if hasattr(event, 'reply'):
        status_msg = await event.reply(
            premium_emoji(f"🫦 Starting check for <b>{total_cards}</b> cards..."),
            parse_mode="html",
        )
    else:
        status_msg = await bot.send_message(
            user_id,
            premium_emoji(f"🫦 Starting check for <b>{total_cards}</b> cards..."),
            parse_mode="html",
        )

    session_key = f"{user_id}_{status_msg.id}"
    active_sessions[session_key] = {"paused": False}

    _DECLINE_KEYWORDS = (
        "declined", "generic_error", "generic", "decision_rule_block",
        "incorrect_number", "brand_not_supported",
        "payments_credit_card_base_expired", "card_declined",
        "do_not_honor", "lost_card", "stolen_card", "expired_card",
        "invalid_account", "pickup_card", "restricted_card",
        "security_violation", "transaction_not_allowed",
    )

    all_results = {
        "charged":    [],
        "approved":   [],
        "insuff":     [],
        "dead":       [],
        "errors":     [],
        "total":      total_cards,
        "checked":    0,
        "start_time": time.time(),
        "last_card":  "",
        "last_response": "",
        "last_price": "-",
        "last_gateway": "Unknown",
    }

    try:
        queue: asyncio.Queue = asyncio.Queue()
        for c in cards:
            queue.put_nowait(c)

        last_update = [time.time()]

        async def worker():
            while not queue.empty() and session_key in active_sessions:
                state = active_sessions.get(session_key)
                if not state: break
                while state.get("paused", False):
                    await asyncio.sleep(2)
                    state = active_sessions.get(session_key)
                    if not state: return
                try:
                    card = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                # Consume one credit per card
                if not await consume_credit(user_id):
                    break

                cur_sites = await get_all_sites()
                cur_proxies = await get_all_user_proxies(user_id)
                if not cur_sites or not cur_proxies: break

                res = await check_card_with_retry(card, cur_sites, cur_proxies, max_retries=20)
                all_results["checked"] += 1
                all_results["last_card"] = card
                all_results["last_response"] = res.get('message', '')[:50]
                all_results["last_price"] = res.get('price', '-')
                all_results["last_gateway"] = res.get('gateway', 'Unknown')

                if res["status"] == "Charged":
                    all_results["charged"].append(res)
                    await update_stats(user_id, checks=0, charged=1)
                    await _send_realtime_hit(user_id, res)
                elif res["status"] == "Approved":
                    all_results["approved"].append(res)
                    await update_stats(user_id, checks=0, approved=1)
                    await _send_realtime_hit(user_id, res)
                elif res["status"] == "Insuff":
                    all_results["insuff"].append(res)
                    await update_stats(user_id, checks=0, approved=1)
                    await _send_realtime_hit(user_id, res)
                else:
                    response_lower = res.get('message', '').lower()
                    if any(k in response_lower for k in _DECLINE_KEYWORDS):
                        all_results["dead"].append(res)
                    else:
                        all_results["errors"].append(res)
                    await update_stats(user_id, checks=0, dead=1)

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
                    if not w.done(): w.cancel()
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
            await save_log(user_id=user_id, total=all_results["total"], charged=len(all_results["charged"]), approved=len(all_results["approved"]) + len(all_results["insuff"]))
        except Exception: pass
        try: await status_msg.delete()
        except Exception: pass
        await _send_final_results(user_id, all_results)


async def _handle_txt_check(event):
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

    try: os.remove(file_path)
    except Exception: pass
    try: await status_msg.delete()
    except Exception: pass

    await _run_bulk_check(event, content, user_id)


@bot.on(events.NewMessage(pattern=r"^/shtxt$"))
async def cmd_shtxt(event):
    await _handle_txt_check(event)


@bot.on(events.NewMessage(pattern=r"^/chk$"))
async def cmd_chk(event):
    await _handle_txt_check(event)


# ═══════════════════════════════════════════════════════════════════════════════
# PROXY COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════


def _parse_proxies(text: str) -> list:
    """Parse and validate proxy strings from text. Returns list of valid proxy strings."""
    proxies = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(":")
        if len(parts) >= 2 and all(p.strip() for p in parts[:2]):
            proxies.append(line)
    return proxies


@bot.on(events.NewMessage(pattern=r"^/addpx(?:\s+(.*))?$"))
async def cmd_addpx(event):
    # Check if replying to a .txt file for bulk proxy import
    if event.reply_to_msg_id:
        reply_msg = await event.get_reply_message()
        if reply_msg.file and reply_msg.file.name and reply_msg.file.name.endswith(".txt"):
            status_msg = await event.reply(premium_emoji("\u23f3 Processing proxy file..."), parse_mode="html")
            file_path = await reply_msg.download_media()
            async with aiofiles.open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = await f.read()
            try: os.remove(file_path)
            except Exception: pass

            proxies = _parse_proxies(content)
            if not proxies:
                await status_msg.edit(premium_emoji("\u274c No valid proxies found in file."), parse_mode="html")
                return

            await add_proxies_bulk(event.sender_id, proxies)
            total = await get_proxy_count(event.sender_id)
            await status_msg.edit(
                premium_emoji(f"\u2705 <b>{len(proxies)} proxies added from file!</b>\n\n\U0001f4ca Total proxies: {total}"),
                parse_mode="html",
            )
            return

    # Text input (single or multi-line)
    parts = event.message.text.strip().split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        await event.reply(
            premium_emoji(
                "\u274c <b>Usage:</b>\n\n"
                "<b>Single:</b> <code>/addpx ip:port:user:pass</code>\n\n"
                "<b>Multi:</b>\n<code>/addpx\nproxy1\nproxy2\n...</code>\n\n"
                "<b>File:</b> Reply to a <code>.txt</code> file with <code>/addpx</code>"
            ),
            parse_mode="html",
        )
        return

    body = parts[1].strip()
    proxies = _parse_proxies(body)
    if not proxies:
        await event.reply(
            premium_emoji("\u274c <b>No valid proxies found.</b>\n\nFormat: <code>ip:port:user:pass</code> or <code>ip:port</code>"),
            parse_mode="html",
        )
        return

    if len(proxies) == 1:
        await set_proxy(event.sender_id, proxies[0])
        await event.reply(premium_emoji(f"\u2705 <b>Proxy Added!</b>\n\n<code>{proxies[0]}</code>"), parse_mode="html")
    else:
        await add_proxies_bulk(event.sender_id, proxies)
        total = await get_proxy_count(event.sender_id)
        await event.reply(
            premium_emoji(f"\u2705 <b>{len(proxies)} proxies added!</b>\n\n\U0001f4ca Total proxies: {total}"),
            parse_mode="html",
        )


@bot.on(events.NewMessage(pattern=r"^/viewpx$"))
async def cmd_viewpx(event):
    count = await get_proxy_count(event.sender_id)
    if count == 0:
        await event.reply(premium_emoji("\u274c No proxies set.\n\nUse <code>/addpx ip:port:user:pass</code>"), parse_mode="html")
        return
    proxies = await get_all_user_proxies(event.sender_id)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"proxies_{event.sender_id}_{timestamp}.txt"
    async with aiofiles.open(filename, "w", encoding="utf-8") as f:
        await f.write("\n".join(proxies))
        
    await event.reply(
        premium_emoji(f"\U0001f4cb <b>Your Proxies ({count}):</b>"), 
        file=filename,
        parse_mode="html"
    )
    try:
        os.remove(filename)
    except Exception:
        pass

@bot.on(events.NewMessage(pattern=r"^/rmpx(?:\s+(.*))?$"))
async def cmd_rmpx(event):
    arg = event.pattern_match.group(1)
    
    count = await get_proxy_count(event.sender_id)
    if count == 0:
        await event.reply(premium_emoji("❌ You have no proxies set."), parse_mode="html")
        return
        
    proxies = await get_all_user_proxies(event.sender_id)
    
    if not arg:
        # Show list with serial numbers
        lines = []
        for i, p in enumerate(proxies[:100], start=1):
            lines.append(f"{i}. <code>{p}</code>")
        msg = "\n".join(lines)
        if count > 100:
            msg += f"\n\n... and {count - 100} more."
        
        await event.reply(
            premium_emoji(f"🗑️ <b>Proxy Removal System</b>\n\nTo remove a proxy, use <code>/rmpx [number]</code>\nTo remove all, use <code>/rmpx all</code>\n\n<b>Your Proxies:</b>\n\n{msg}"),
            parse_mode="html"
        )
        return
        
    arg = arg.strip().lower()
    if arg == "all":
        await remove_proxy(event.sender_id)
        await event.reply(premium_emoji(f"✅ <b>{count} proxies removed!</b>"), parse_mode="html")
        return
        
    try:
        idx = int(arg) - 1
        if idx < 0 or idx >= count:
            await event.reply(premium_emoji("❌ Invalid proxy number."), parse_mode="html")
            return
            
        proxy_to_remove = proxies[idx]
        await remove_single_proxy(event.sender_id, proxy_to_remove)
        await event.reply(premium_emoji(f"✅ <b>Proxy removed!</b>\n\n<code>{proxy_to_remove}</code>"), parse_mode="html")
    except ValueError:
        await event.reply(premium_emoji("❌ Please provide a valid proxy number or 'all'."), parse_mode="html")


@bot.on(events.NewMessage(pattern=r"^/testpx$"))
async def cmd_testpx(event):
    proxies = await get_all_user_proxies(event.sender_id)
    if not proxies:
        await event.reply(premium_emoji("❌ No proxies set.\n\nUse <code>/addpx ip:port:user:pass</code> first."), parse_mode="html")
        return

    status_msg = await event.reply(
        premium_emoji(
            f"<b>🐺 𝐀ᴇʀᴏ𝐗</b>\n"
            f"<b>━━━━━━━━━━━━━━━━━</b>\n"
            f"🔄 <b>Testing Proxies...</b>\n\n"
            f"<blockquote>"
            f"Total: {len(proxies)}\n"
            f"Checking IP, Fraud, and Shopify..."
            f"</blockquote>\n"
            f"<b>━━━━━━━━━━━━━━━━━</b>"
        ), 
        parse_mode="html"
    )
    
    alive, dead = [], []
    alive_blocks = []
    
    for i in range(0, len(proxies), 10):
        batch = proxies[i : i + 10]
        tasks = [test_proxy(p) for p in batch]
        results = await asyncio.gather(*tasks)
        
        for p, res in zip(batch, results):
            if res.get("alive"):
                alive.append(p)
                if len(alive_blocks) < 10:
                    shopify_s = "✅ YES" if res.get("shopify") else "❌ NO"
                    fs = res.get("fraud_score")
                    if fs is not None:
                        if fs <= 20: fs_str = f"✅ {fs}/100 (Clean)"
                        elif fs <= 50: fs_str = f"⚠️ {fs}/100 (Medium)"
                        else: fs_str = f"❌ {fs}/100 (Risky)"
                    else: 
                        fs_str = "─"
                        
                    ip_display = res.get('ip', '?')
                    cc_display = res.get('country_code') or res.get('country') or '?'
                    shop_ms = res.get('shopify_ms') or res.get('ms')
                    
                    alive_blocks.append(
                        f"<blockquote>"
                        f"✅ <code>{p}</code>\n"
                        f"🌍 <b>IP:</b> <code>{ip_display}</code> | <code>{cc_display}</code>\n"
                        f"🛡️ <b>Fraud:</b> {fs_str}\n"
                        f"🛍️ <b>Shopify:</b> {shopify_s} ({shop_ms}ms)"
                        f"</blockquote>"
                    )
            else:
                dead.append(p)
                await remove_single_proxy(event.sender_id, p)
        
        await status_msg.edit(
            premium_emoji(
                f"<b>🐺 𝐀ᴇʀᴏ𝐗</b>\n"
                f"<b>━━━━━━━━━━━━━━━━━</b>\n"
                f"🔄 <b>Testing Proxies...</b>\n\n"
                f"<blockquote>"
                f"<b>Checked:</b> {len(alive)+len(dead)}/{len(proxies)}\n"
                f"<b>Alive:</b> {len(alive)}\n"
                f"<b>Dead (Removed):</b> {len(dead)}"
                f"</blockquote>\n"
                f"<b>━━━━━━━━━━━━━━━━━</b>"
            ),
            parse_mode="html"
        )
        
    final_text = (
        f"<b>🐺 𝐀ᴇʀᴏ𝐗</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━</b>\n"
        f"✅ <b>Proxy Check Complete!</b>\n\n"
        f"<blockquote>"
        f"<b>Total Checked:</b> {len(proxies)}\n"
        f"<b>Alive:</b> {len(alive)}\n"
        f"<b>Dead (Removed):</b> {len(dead)}"
        f"</blockquote>\n"
        f"<b>━━━━━━━━━━━━━━━━━</b>\n"
    )
    if alive_blocks:
        final_text += "\n<b>🌟 Top Alive Proxies:</b>\n" + "\n".join(alive_blocks)
        if len(alive) > 10:
            final_text += f"\n\n<i>... and {len(alive) - 10} more</i>\n"
            
    final_text += "\n🐻 <b>𝑷𝒐𝒘𝒆𝒓𝒆𝒅 𝒃𝒚 𝑨𝒆𝒓𝒐𝑿</b>"
            
    await status_msg.edit(premium_emoji(final_text), parse_mode="html")

@bot.on(events.NewMessage(pattern=r"^/proxy$"))
async def cmd_proxy_menu(event):
    txt = await _txt_proxy(event.sender_id)
    await event.respond(txt, buttons=_kb_proxy(), parse_mode="html")

@bot.on(events.CallbackQuery(pattern=b"^proxy_add$"))
async def cb_proxy_add(event):
    await event.answer("To add proxies, send:\n/addpx ip:port:user:pass\n(or reply to a .txt file)", alert=True)

@bot.on(events.CallbackQuery(pattern=b"^proxy_test$"))
async def cb_proxy_test(event):
    await event.answer("Starting proxy test...")
    await cmd_testpx(event)

@bot.on(events.CallbackQuery(pattern=b"^proxy_view$"))
async def cb_proxy_view(event):
    await event.answer("Generating proxy file...")
    await cmd_viewpx(event)

@bot.on(events.CallbackQuery(pattern=b"^proxy_remove$"))
async def cb_proxy_remove(event):
    count = await get_proxy_count(event.sender_id)
    if count == 0:
        await event.answer("You don't have any proxies to remove.", alert=True)
        return
    await remove_proxy(event.sender_id)
    await event.answer(f"✅ {count} proxies removed!", alert=True)
    txt = await _txt_proxy(event.sender_id)
    await event.edit(txt, buttons=_kb_proxy(), parse_mode="html")

@bot.on(events.NewMessage(pattern=r"^/help$"))
async def cmd_help(event):
    await event.respond(premium_emoji(_txt_help()), parse_mode="html")


# ═══════════════════════════════════════════════════════════════════════════════
# SITE MANAGEMENT COMMANDS (Admin)
# ═══════════════════════════════════════════════════════════════════════════════

@bot.on(events.NewMessage(pattern=r"^/addsite\s+"))
async def cmd_addsite(event):
    if not is_owner(event.sender_id):
        await event.reply(premium_emoji("\u274c <b>Owner Only.</b> You don't have permission."), parse_mode="html")
        return
    url = event.message.text.split(" ", 1)[1].strip()
    if not url:
        await event.reply(premium_emoji("\u274c Usage: <code>/addsite https://example.com</code>"), parse_mode="html")
        return

    proxy = await get_proxy(event.sender_id)
    if not proxy:
        await event.reply(premium_emoji("\u274c <b>No proxy set.</b> Use <code>/addpx ip:port:user:pass</code> first."), parse_mode="html")
        return

    status_msg = await event.reply(premium_emoji(f"🔄 <b>Testing Site:</b> <code>{url}</code>"), parse_mode="html")
    
    from utils.checker import test_site
    result = await test_site(url, proxy)
    
    if result["status"] == "alive":
        await add_site(url)
        count = await site_count()
        await status_msg.edit(premium_emoji(f"\u2705 <b>Site Added!</b>\n\n<code>{url}</code>\n\n\U0001f4ca Total alive sites: {count}"), parse_mode="html")
    else:
        err = result.get("error", "Dead/Offline")
        await status_msg.edit(premium_emoji(f"\u274c <b>Site Rejected (Dead)</b>\n\n<code>{url}</code>\n<b>Reason:</b> {err}"), parse_mode="html")


@bot.on(events.NewMessage(pattern=r"^/addsites$"))
async def cmd_addsites(event):
    if not is_owner(event.sender_id):
        await event.reply(premium_emoji("\u274c <b>Owner Only.</b> You don't have permission."), parse_mode="html")
        return

    proxy = await get_proxy(event.sender_id)
    if not proxy:
        await event.reply(premium_emoji("\u274c <b>No proxy set.</b> Use <code>/addpx ip:port:user:pass</code> first."), parse_mode="html")
        return

    if not event.reply_to_msg_id:
        await event.reply(
            premium_emoji("\u274c Reply to a <code>.txt</code> file containing site URLs (one per line)."),
            parse_mode="html",
        )
        return

    reply_msg = await event.get_reply_message()
    if not reply_msg.file or not reply_msg.file.name or not reply_msg.file.name.endswith(".txt"):
        await event.reply(premium_emoji("\u274c Please reply to a <code>.txt</code> file."), parse_mode="html")
        return

    status_msg = await event.reply(premium_emoji("\u23f3 Processing sites file..."), parse_mode="html")
    file_path = await reply_msg.download_media()

    async with aiofiles.open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = await f.read()

    try: os.remove(file_path)
    except Exception: pass

    urls = [line.strip() for line in content.splitlines() if line.strip()]
    if not urls:
        await status_msg.edit(premium_emoji("\u274c No URLs found in the file."), parse_mode="html")
        return

    await status_msg.edit(premium_emoji(f"🔄 <b>Testing {len(urls)} Sites...</b>"), parse_mode="html")
    
    from utils.checker import test_site
    import asyncio
    alive_urls = []
    dead_urls = []
    alive_lines = []
    dead_lines = []
    
    for i in range(0, len(urls), 20):
        batch = urls[i:i+20]
        tasks = [test_site(u, proxy) for u in batch]
        results = await asyncio.gather(*tasks)
        
        for res in results:
            site_url = res["site"].replace("https://", "").replace("http://", "").rstrip("/")
            if res["status"] == "alive":
                alive_urls.append(res["site"])
                price = res.get("price", "N/A")
                msg = res.get("msg", "")
                if msg:
                    alive_lines.append(f"{site_url} ${price} | Order declined: {msg}")
                else:
                    alive_lines.append(f"{site_url} ${price} | Alive")
            else:
                dead_urls.append(res["site"])
                msg = res.get("msg", "Site error")
                dead_lines.append(f"{site_url} | {msg}")
                
        disp_alive = "\n".join([f"<code>{x}</code>" for x in alive_lines[-10:]])
        disp_dead = "\n".join([f"<code>{x}</code>" for x in dead_lines[-10:]])
        
        txt = (
            f"🛒 <b>Site Add Results</b>\n"
            f"✅ Valid: {len(alive_urls)} | ❌ Dead: {len(dead_urls)}\n\n"
        )
        if disp_alive:
            txt += f"✅ <b>Valid ({len(alive_urls)}):</b>\n{disp_alive}\n\n"
        if disp_dead:
            txt += f"❌ <b>Dead ({len(dead_urls)}):</b>\n{disp_dead}\n\n"
            
        txt += f"<i>Testing... {len(alive_urls)+len(dead_urls)}/{len(urls)}</i>"
        await status_msg.edit(premium_emoji(txt), parse_mode="html")

    for url in alive_urls:
        await add_site(url)

    count = await site_count()
    
    full_text = (
        f"🛒 Site Add Results\n"
        f"✅ Valid Added: {len(alive_urls)} | ❌ Dead Rejected: {len(dead_urls)}\n\n"
    )
    if alive_lines:
        full_text += f"✅ Valid ({len(alive_urls)}):\n" + "\n".join(alive_lines) + "\n\n"
    if dead_lines:
        full_text += f"❌ Dead ({len(dead_urls)}):\n" + "\n".join(dead_lines) + "\n\n"
        
    filename = f"add_result_{event.sender_id}.txt"
    async with aiofiles.open(filename, "w", encoding="utf-8") as f:
        await f.write(full_text)

    disp_alive = "\n".join([f"<code>{x}</code>" for x in alive_lines[-10:]])
    disp_dead = "\n".join([f"<code>{x}</code>" for x in dead_lines[-10:]])
    
    final_txt = (
        f"🛒 <b>Site Add Results</b>\n"
        f"✅ Valid Added: {len(alive_urls)} | ❌ Dead Rejected: {len(dead_urls)}\n"
        f"📊 Total Alive Sites: {count}\n\n"
    )
    if disp_alive:
        final_txt += f"✅ <b>Valid ({len(alive_urls)}):</b>\n{disp_alive}\n\n"
    if disp_dead:
        final_txt += f"❌ <b>Dead ({len(dead_urls)}):</b>\n{disp_dead}\n\n"
        
    final_txt += f"📎 <b>Full results sent as .txt file.</b>"
    
    await event.reply(premium_emoji(final_txt), file=filename, parse_mode="html")
    await status_msg.delete()
    try: os.remove(filename)
    except: pass


@bot.on(events.NewMessage(pattern=r"^/rm\s+"))
async def cmd_rm(event):
    if not is_owner(event.sender_id):
        await event.reply(premium_emoji("\u274c <b>Owner Only.</b> You don't have permission."), parse_mode="html")
        return
    url = event.message.text.split(" ", 1)[1].strip()
    if not url:
        await event.reply(premium_emoji("\u274c Usage: <code>/rm https://site.com</code> or <code>/rm all</code>"), parse_mode="html")
        return

    if url.lower() == "all":
        from database.sites import remove_all_sites
        count = await remove_all_sites()
        await event.reply(premium_emoji(f"\u2705 <b>All Sites Removed!</b>\n\nDeleted {count} sites."), parse_mode="html")
        return

    await remove_site(url)
    await event.reply(premium_emoji(f"\u2705 <b>Site Removed!</b>\n\n<code>{url}</code> has been deleted."), parse_mode="html")

def _kb_sites(page: int, total_pages: int):
    buttons = []
    nav = []
    if page > 1:
        nav.append(Button.inline("⬅️ Previous", data=f"sitepage_{page-1}"))
    if page < total_pages:
        nav.append(Button.inline("Next ➡️", data=f"sitepage_{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([Button.inline("❌ Close", data="stop")])
    return buttons

async def _txt_sites(page: int, sites: list):
    per_page = 20
    total_pages = max(1, (len(sites) + per_page - 1) // per_page)
    if page > total_pages: page = total_pages
    
    start = (page - 1) * per_page
    end = start + per_page
    current_sites = sites[start:end]
    
    txt = f"🌐 <b>Saved Sites (Page {page}/{total_pages})</b>\n\n"
    for i, site in enumerate(current_sites, start=start+1):
        txt += f"<b>{i}.</b> <code>{site}</code>\n"
        
    txt += f"\n📊 <b>Total Sites:</b> {len(sites)}"
    return txt, _kb_sites(page, total_pages)

@bot.on(events.NewMessage(pattern=r"^/viewsites$"))
async def cmd_viewsites(event):
    if not is_owner(event.sender_id):
        await event.reply(premium_emoji("\u274c <b>Owner Only.</b>"), parse_mode="html")
        return
    
    sites = await get_all_sites()
    if not sites:
        await event.reply(premium_emoji("❌ No sites in database."), parse_mode="html")
        return
        
    txt, kb = await _txt_sites(1, sites)
    await event.reply(premium_emoji(txt), buttons=kb, parse_mode="html")

@bot.on(events.CallbackQuery(pattern=r"^sitepage_(\d+)$"))
async def cb_site_page(event):
    if not is_owner(event.sender_id):
        await event.answer("Owner Only.", alert=True)
        return
    page = int(event.pattern_match.group(1))
    sites = await get_all_sites()
    if not sites:
        await event.answer("No sites.", alert=True)
        return
        
    txt, kb = await _txt_sites(page, sites)
    await event.edit(premium_emoji(txt), buttons=kb, parse_mode="html")


@bot.on(events.NewMessage(pattern=r"^/testsites$"))
async def cmd_site(event):
    if not is_owner(event.sender_id):
        await event.reply(premium_emoji("\u274c <b>Owner Only.</b>"), parse_mode="html")
        return
    user_id = event.sender_id
    if not await _ensure_and_check_premium(event): return
    proxy = await get_proxy(user_id)
    if not proxy:
        await event.reply(premium_emoji("❌ No proxy set. Use <code>/addproxy ip:port:user:pass</code> first."), parse_mode="html")
        return

    sites = await get_all_sites()
    if not sites:
        await event.reply(premium_emoji("❌ No sites in database. Nothing to check."), parse_mode="html")
        return

    status_msg = await event.reply(premium_emoji(f"🛒 <b>Site Test Results</b>\n\n\u23f3 Starting..."), parse_mode="html")
    alive, dead = [], []
    alive_lines, dead_lines = [], []
    try:
        for i in range(0, len(sites), 10):
            batch   = sites[i : i + 10]
            tasks   = [test_site(site, proxy) for site in batch]
            results = await asyncio.gather(*tasks)
            for res in results:
                site_url = res["site"].replace("https://", "").replace("http://", "").rstrip("/")
                if res["status"] == "alive": 
                    alive.append(res["site"])
                    price = res.get("price", "N/A")
                    msg = res.get("msg", "")
                    if msg:
                        alive_lines.append(f"{site_url} ${price} | Order declined: {msg}")
                    else:
                        alive_lines.append(f"{site_url} ${price} | Alive")
                else:
                    dead.append(res["site"])
                    msg = res.get("msg", "Site error")
                    dead_lines.append(f"{site_url} | {msg}")
                    await mark_site_dead(res["site"])
                    
            disp_alive = "\n".join([f"<code>{x}</code>" for x in alive_lines[-10:]])
            disp_dead = "\n".join([f"<code>{x}</code>" for x in dead_lines[-10:]])
            
            txt = (
                f"🛒 <b>Site Test Results</b>\n"
                f"✅ Valid: {len(alive)} | ❌ Dead: {len(dead)}\n\n"
            )
            if disp_alive:
                txt += f"✅ <b>Valid ({len(alive)}):</b>\n{disp_alive}\n\n"
            if disp_dead:
                txt += f"❌ <b>Dead ({len(dead)}):</b>\n{disp_dead}\n\n"
                
            txt += f"<i>Testing... {len(alive)+len(dead)}/{len(sites)}</i>"
            await status_msg.edit(premium_emoji(txt), parse_mode="html")
            
        full_text = (
            f"🛒 Site Test Results\n"
            f"✅ Valid: {len(alive)} | ❌ Dead: {len(dead)}\n\n"
        )
        if alive_lines:
            full_text += f"✅ Valid ({len(alive)}):\n" + "\n".join(alive_lines) + "\n\n"
        if dead_lines:
            full_text += f"❌ Dead ({len(dead)}):\n" + "\n".join(dead_lines) + "\n\n"
            
        filename = f"sites_result_{event.sender_id}.txt"
        async with aiofiles.open(filename, "w", encoding="utf-8") as f:
            await f.write(full_text)
            
        disp_alive = "\n".join([f"<code>{x}</code>" for x in alive_lines[-10:]])
        disp_dead = "\n".join([f"<code>{x}</code>" for x in dead_lines[-10:]])
        
        final_txt = (
            f"🛒 <b>Site Test Results</b>\n"
            f"✅ Valid: {len(alive)} | ❌ Dead: {len(dead)}\n\n"
        )
        if disp_alive:
            final_txt += f"✅ <b>Valid ({len(alive)}):</b>\n{disp_alive}\n\n"
        if disp_dead:
            final_txt += f"❌ <b>Dead ({len(dead)}):</b>\n{disp_dead}\n\n"
            
        final_txt += f"📎 <b>Full results sent as .txt file.</b>"
        
        await event.reply(premium_emoji(final_txt), file=filename, parse_mode="html")
        await status_msg.delete()
        try: os.remove(filename)
        except: pass
        
    except Exception as exc:
        await status_msg.edit(premium_emoji(f"❌ Error during site check: {exc}"), parse_mode="html")

def _kb_admin():
    return [
        [Button.inline("➕ Add Site", data="admin_addsite"), Button.inline("📋 View Sites", data="admin_viewsites")],
        [Button.inline("🔄 Test Sites", data="admin_testsites"), Button.inline("🗑 Remove All Sites", data="admin_rm_all")],
        [Button.inline("👑 Elevate User", data="admin_elevate"), Button.inline("🚫 Demote User", data="admin_demote")],
        [Button.inline("❌ Close", data="stop")]
    ]

def _txt_admin_panel():
    return (
        "👑 <b>Admin Control Panel</b>\n\n"
        "<b>Admin Commands:</b>\n"
        "<code>/addsite [url]</code> - Add a site\n"
        "<code>/addsites</code> - Bulk add via .txt\n"
        "<code>/testsites</code> - Test all sites\n"
        "<code>/viewsites</code> - View saved sites\n"
        "<code>/rm [url]</code> - Remove a site\n"
        "<code>/rm all</code> - Remove all sites\n\n"
        "<b>Owner Commands:</b>\n"
        "<code>/elevate [id] [plan]</code> - Grant premium\n"
        "<code>/demote [id]</code> - Revoke premium\n\n"
        "<i>Or use the interactive buttons below:</i>"
    )

@bot.on(events.NewMessage(pattern=r"^/admin$"))
async def cmd_admin(event):
    if not is_owner(event.sender_id):
        await event.reply(premium_emoji("\u274c <b>Owner Only.</b>"), parse_mode="html")
        return
    await event.reply(premium_emoji(_txt_admin_panel()), buttons=_kb_admin(), parse_mode="html")

@bot.on(events.CallbackQuery(pattern=r"^admin_(\w+)$"))
async def cb_admin_menu(event):
    if not is_owner(event.sender_id):
        await event.answer("Owner Only.", alert=True)
        return
        
    action = event.pattern_match.group(1).decode("utf-8")
    
    if action == "addsite":
        await event.edit(premium_emoji("<b>To add sites, use the following commands:</b>\n\n<code>/addsite https://site.com</code>\n\nOr to add in bulk, reply to a <code>.txt</code> file with:\n<code>/addsites</code>"), buttons=[[Button.inline("🔙 Back", data="admin_back")]], parse_mode="html")
        
    elif action == "viewsites":
        sites = await get_all_sites()
        if not sites:
            await event.answer("❌ No sites in database.", alert=True)
            return
        txt, kb = await _txt_sites(1, sites)
        await event.edit(premium_emoji(txt), buttons=kb, parse_mode="html")
        
    elif action == "testsites":
        await event.edit(premium_emoji("<b>To test all sites, run the command:</b>\n\n<code>/testsites</code>"), buttons=[[Button.inline("🔙 Back", data="admin_back")]], parse_mode="html")
        
    elif action == "rm_all":
        from database.sites import remove_all_sites
        count = await remove_all_sites()
        await event.answer(f"✅ All {count} Sites Removed!", alert=True)
        await event.edit(premium_emoji(f"👑 <b>Admin Control Panel</b>\n\n\u2705 <b>All Sites Removed!</b> (Deleted {count} sites)"), buttons=_kb_admin(), parse_mode="html")
        
    elif action == "elevate":
        if event.sender_id != OWNER_ID:
            await event.answer("Owner Only (Not Admin).", alert=True)
            return
        await event.edit(premium_emoji("<b>To grant premium, use:</b>\n\n<code>/elevate user_id core</code>\n<code>/elevate user_id nova</code>\n<code>/elevate user_id monarch</code>"), buttons=[[Button.inline("🔙 Back", data="admin_back")]], parse_mode="html")
        
    elif action == "demote":
        if event.sender_id != OWNER_ID:
            await event.answer("Owner Only (Not Admin).", alert=True)
            return
        await event.edit(premium_emoji("<b>To revoke premium, use:</b>\n\n<code>/demote user_id</code>"), buttons=[[Button.inline("🔙 Back", data="admin_back")]], parse_mode="html")
        
    elif action == "back":
        await event.edit(premium_emoji(_txt_admin_panel()), buttons=_kb_admin(), parse_mode="html")
# ══════════════
# ADMIN COMMANDS
# ══════════════

@bot.on(events.NewMessage(pattern=r"^/elevate\s+"))
async def cmd_elevate(event):
    if event.sender_id != OWNER_ID: return
    try:
        args = event.raw_text.split()
        if len(args) != 3:
            await event.reply("Usage:\n<code>/elevate user_id core</code>\n<code>/elevate user_id nova</code>\n<code>/elevate user_id monarch</code>", parse_mode="html")
            return
        user_id = int(args[1])
        plan = args[2].lower()
        if plan not in ["core", "nova", "monarch"]:
            await event.reply("❌ Invalid plan.\n\nUse: core / nova / monarch", parse_mode="html")
            return
        await set_plan(user_id, plan)
        await event.reply(f"✅ Premium activated.\n\n👤 User: <code>{user_id}</code>\n📦 Plan: <b>{plan.capitalize()}</b>", parse_mode="html")
    except Exception as e:
        await event.reply(f"❌ Error:\n<code>{e}</code>", parse_mode="html")


@bot.on(events.NewMessage(pattern=r"^/demote\s+"))
async def cmd_demote(event):
    if event.sender_id != OWNER_ID: return
    try:
        args = event.raw_text.split()
        if len(args) != 2:
            await event.reply("Usage: <code>/demote user_id</code>", parse_mode="html")
            return
        user_id = int(args[1])
        await remove_plan(user_id)
        await event.reply(f"\u2705 Premium removed.\n\n\U0001f464 User: <code>{user_id}</code>", parse_mode="html")
    except Exception as e:
        await event.reply(f"\u274c Error:\n<code>{e}</code>", parse_mode="html")


# ══════════════════════
# ENTRY POINT
# ══════════════════════

async def startup():
    print("Checking admin permissions in DB...")
    # Give owner and admins premium monarch plan on fresh db
    for uid in [OWNER_ID] + ADMIN_IDS:
        if not await is_premium(uid):
            await set_plan(uid, "monarch")
            print(f"Granted premium 'monarch' to Admin/Owner ID: {uid}")

bot.loop.run_until_complete(startup())
print("Bot started successfully!")
bot.run_until_disconnected()
