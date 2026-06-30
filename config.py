from dotenv import load_dotenv
import os

load_dotenv()

API_ID = int(os.getenv("API_ID", "12380656"))
API_HASH = os.getenv("API_HASH", "d927c13beaaf5110f25c505b7c071273")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8987193319:AAEWFpOED00_XWdDROwpZPaKEbWX6myBgkI")

MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://Aero:8wP1Y9ggrOf9Msl6@cluster0.l0pwxat.mongodb.net/?appName=Cluster0")
CHECKER_API_URL = os.getenv("CHECKER_API_URL", "https://Worker.xb1ns.com")
OWNER_ID = int(os.getenv("OWNER_ID", "1817159548"))

_admin_ids_str = os.getenv("ADMIN_IDS", "6677260209")
ADMIN_IDS = [int(x.strip()) for x in _admin_ids_str.split(",") if x.strip()]
