from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI

client = AsyncIOMotorClient(MONGO_URI)

db = client.shopiii

users_col = db.users
proxies_col = db.proxies
sites_col = db.sites
logs_col = db.logs