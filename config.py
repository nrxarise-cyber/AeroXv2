from dotenv import load_dotenv
import os

load_dotenv()

API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

MONGO_URI = os.getenv("MONGO_URI", "")
CHECKER_API_URL = os.getenv("CHECKER_API_URL", "https://Worker.xb1ns.com")
OWNER_ID = int(os.getenv("OWNER_ID", 0))

_admin_ids_str = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in _admin_ids_str.split(",") if x.strip()]
