from db import sites_col
import random

async def add_site(url):
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

async def get_random_site():
    sites = await sites_col.find(
        {"status": "alive"}
    ).to_list(length=10000)

    if not sites:
        return None

    return random.choice(sites)["url"]

async def get_all_sites():
    sites = await sites_col.find(
        {"status": "alive"}
    ).to_list(length=10000)

    return [site["url"] for site in sites]

async def remove_site(url):
    await sites_col.delete_one(
        {"url": url}
    )

async def mark_site_dead(url):
    await sites_col.update_one(
        {"url": url},
        {
            "$set": {
                "status": "dead"
            }
        }
    )

async def mark_site_alive(url):
    await sites_col.update_one(
        {"url": url},
        {
            "$set": {
                "status": "alive"
            }
        }
    )

async def site_count():
    return await sites_col.count_documents(
        {"status": "alive"}
    )