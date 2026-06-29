# Premium Custom Emoji IDs
# Bot must be created with a Telegram Premium account for these to render.
# Use @RawDataBot to get custom_emoji_id for any premium emoji.
PREMIUM_EMOJI_IDS = {
    "🐺": "5823543394982435031",   #. 🐺 dragon logo
    "✅": "6023660820544623088",   # ✨ Multi Sparkles / Celebration
    "🔥": "5999340396432333728",   # 🔥 Purple Flame Heart
    "❌": "6037570896766438989",   # 💀 White Skull (Dark Glow)
    "⚡": "6026367225466720832",   # ⚡ Yellow Lightning Bolt
    "💳": "5971944878815317190",   # 💫 Floating Color Dots
    "💠": "5971837723676249096",   # 🌀 Neon Circle Rings
    "📝": "6023660820544623088",   # ✨
    "🌐": "6026367225466720832",   # ⚡
    "🎯": "5974235702701853774",   # 🟠🟡🟢 Triple Ring Loader
    "🤖": "6057466460886799210",   # 😼 Dark Cat Face
    "🤵": "4949560993840629085",   # 🧠 Golden Maze
    "💰": "5971944878815317190",   # 💫
    "⏸️": "6001440193058444284",   # ⚙️ Arc Reactor
    "▶️": "6285315214673975495",   # ➡️ Neon Arrow Right
    "💃": "6226543702534260736",  # Profile
    "🚀": "5800956853462504394",  # User ID / Plan
    "🙂": "5967827495532107050",  # Name
    "☄️": "5084722583853597696",  # Username
    "📆": "5769628576026465566",  # Joined
    "📊": "5929371281781691824",  # Stats
    "📅": "5971837723676249096",  # Total Checks
    "📸": "5967782394080530708",  # Charged
    "🎥": "5273948796986863345",  # Approved
    "😅": "5258217809250372293",  # Total Hits
    "⚽️": "6154522383790114334",  # Hit Rate
    "🐻": "6062026539334109188",  # Powered By
    "🛑": "6172478697161888759",  # Warning / Error
}
}


def premium_emoji(text: str) -> str:
    """Replace Unicode emojis with <tg-emoji emoji-id="..."> tags for
    Telegram Premium custom animated emojis.

    Requires the bot to be created with a Telegram Premium account.
    Uses placeholders internally to avoid double-replacing emoji inside tags.
    """
    if not text:
        return text

    placeholders = []
    result = text

    for i, (emoji, doc_id) in enumerate(PREMIUM_EMOJI_IDS.items()):
        placeholder = f"\x00PE{i:02d}\x00"
        placeholders.append((placeholder, doc_id, emoji))
        result = result.replace(emoji, placeholder)

    for placeholder, doc_id, emoji in placeholders:
        result = result.replace(
            placeholder,
            f'<tg-emoji emoji-id="{doc_id}">{emoji}</tg-emoji>'
        )

    return result