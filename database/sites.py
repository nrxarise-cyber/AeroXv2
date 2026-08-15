from db import sites_col
import random

async def add_site(url):
    try:
        await sites_col.update_one(
            {"url": url},
            {
                "$set": {
                    "url": url,
                    "status": "alive"
                }
            },
            upsert=True
        )
    except Exception as e:
        print(f"Error adding site: {e}")
        raise

async def get_random_site():
    try:
        count = await sites_col.count_documents({"status": "alive"})
        if not count:
            return None
        random_index = random.randint(0, count - 1)
        site = await sites_col.find(
            {"status": "alive"},
            {"_id": 0, "url": 1}
        ).skip(random_index).limit(1).to_list(length=1)
        return site[0]["url"] if site else None
    except Exception as e:
        print(f"Error getting random site: {e}")
        raise

async def get_all_sites():
    try:
        sites = await sites_col.find(
            {"status": "alive"},
            {"_id": 0, "url": 1}
        ).to_list(length=None)
        return [site["url"] for site in sites]
    except Exception as e:
        print(f"Error getting all sites: {e}")
        raise

async def remove_site(url):
    try:
        await sites_col.delete_one(
            {"url": url}
        )
    except Exception as e:
        print(f"Error removing site: {e}")
        raise

async def mark_site_dead(url):
    try:
        await sites_col.update_one(
            {"url": url},
            {
                "$set": {
                    "status": "dead"
                }
            }
        )
    except Exception as e:
        print(f"Error marking site dead: {e}")
        raise

async def mark_site_alive(url):
    try:
        await sites_col.update_one(
            {"url": url},
            {
                "$set": {
                    "status": "alive"
                }
            }
        )
    except Exception as e:
        print(f"Error marking site alive: {e}")
        raise

async def site_count():
    try:
        return await sites_col.count_documents(
            {"status": "alive"}
        )
    except Exception as e:
        print(f"Error counting sites: {e}")
        raise

async def remove_all_sites():
    try:
        result = await sites_col.delete_many({})
        return result.deleted_count
    except Exception as e:
        print(f"Error removing all sites: {e}")
        raise