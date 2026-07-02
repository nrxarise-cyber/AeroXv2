from dotenv import load_dotenv
import os

load_dotenv()

def _get_int(key, default=0):
    val = os.getenv(key)
    if not val or not val.strip():
        return default
    try:
        return int(val.strip())
    except ValueError:
        return default

def _get_admin_ids():
    val = os.getenv("ADMIN_IDS", "")
    if not val or not val.strip():
        return []
    # Clean brackets, braces, and quotes in case user pasted [123, 456]
    cleaned = val.replace("[", "").replace("]", "").replace("'", "").replace('"', "").replace("{", "").replace("}", "").strip()
    ids = []
    for x in cleaned.split(","):
        x = x.strip()
        if x.isdigit():
            ids.append(int(x))
    return ids

API_ID = _get_int("API_ID", 0)
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

MONGO_URI = os.getenv("MONGO_URI", "")
CHECKER_API_URL = os.getenv("CHECKER_API_URL", "")
OWNER_ID = _get_int("OWNER_ID", 0)

ADMIN_IDS = _get_admin_ids()
