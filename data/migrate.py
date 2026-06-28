from database.users import add_premium
from database.sites import add_site
import asyncio

PREMIUM_FILE = "premium.txt"
SITES_FILE = "sites.txt"


async def migrate_premium():
    try:
        with open(PREMIUM_FILE, "r", encoding="utf-8") as f:
            users = [line.strip() for line in f if line.strip()]

        for user_id in users:
            await add_premium(int(user_id))

        print(f"✅ Migrated {len(users)} premium users")

    except FileNotFoundError:
        print("⚠️ premium.txt not found")


async def migrate_sites():
    try:
        with open(SITES_FILE, "r", encoding="utf-8") as f:
            sites = [line.strip() for line in f if line.strip()]

        for site in sites:
            await add_site(site)

        print(f"✅ Migrated {len(sites)} sites")

    except FileNotFoundError:
        print("⚠️ sites.txt not found")


async def main():
    await migrate_premium()
    await migrate_sites()

    print("🚀 Migration Complete")


if __name__ == "__main__":
    asyncio.run(main())
