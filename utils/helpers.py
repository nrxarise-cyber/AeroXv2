import re
from datetime import datetime


_DEAD_INDICATORS = (
    'receipt id is empty',
    'handle is empty',
    'product id is empty',
    'tax amount is empty',
    'payment method identifier is empty',
    'invalid url',
    'error in 1st req',
    'error in 1 req',
    'cloudflare',
    'product_not_found',
    'missing site parameter',
    'not a shopify',
    'connection failed',
    'timed out',
    'access denied',
    'tlsv1 alert',
    'ssl routines',
    'could not resolve',
    'domain name not found',
    'name or service not known',
    'openssl ssl_connect',
    'empty reply from server',
    'httperror504',
    'http error',
    'timeout',
    'unreachable',
    'ssl error',
    '502',
    '503',
    '504',
    'bad gateway',
    'service unavailable',
    'gateway timeout',
    'network error',
    'connection reset',
    'failed to detect product',
    'failed to create checkout',
    'failed to tokenize card',
    'failed to get proposal data',
    'submit rejected',
    'submit rejected:',
    'handle error',
    'http 404',
    'delivery_delivery_line_detail_changed',
    'delivery_address2_required',
    'url rejected',
    'malformed input',
    'amount_too_small',
    'amount too small',
    'site dead',
    'captcha_required',
    'captcha required',
    'site errors',
    'all products sold out',
    'no_session_token',
    'tokenize_fail',
    'failed',
    'not supported',
    'unsupported',
    'site not supported',
    'invalid site',
    'connection refused',
    'forbidden',
    'no response',
    'host not found',
    'domain not found',
    'could not connect',
    'connection error',
    'request timeout',
    'gateway error',
    'internal server error',
    'server error',
    'page not found',
    'not found',
    'http 500',
    'http 502',
    'http 503',
    'http 504',
    'cloudflare error',
    'cf-error',
    'cf-ray',
    'challenge required',
    'blocked',
    'access blocked',
)


def get_price_from_response(raw_response):
    """Extract a float price from the API response."""
    try:
        price = raw_response.get('Price', '-')
        if price != '-' and price != 0:
            price_clean = str(price).replace('$', '').replace(',', '').strip()
            return float(price_clean)
    except Exception:
        pass
    return 0.0


def is_site_dead(response_msg, gateway, price):
    """Full site-dead check: response keywords + gateway + price validation."""
    if not response_msg:
        return True
    if not gateway or gateway == "Unknown":
        return True
    if "Shopify" not in str(gateway):
        return True
    price_str = str(price)
    if price_str in ("-", "$-", "$0", "$0.0", "0", "$0.00", "N/A"):
        return True
    return is_dead_site_error(response_msg)


def is_dead_site_error(error_msg):
    if error_msg is None:
        return True

    if not error_msg:
        return False

    error_msg = str(error_msg).lower()

    return any(
        keyword in error_msg
        for keyword in _DEAD_INDICATORS
    )


def get_time():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def extract_cc(text):
    pattern = r'(\d{15,16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})'
    matches = re.findall(pattern, text)
    cards = []
    for match in matches:
        card, month, year, cvv = match
        if len(year) == 2:
            year = "20" + year
        cards.append(f"{card}|{month}|{year}|{cvv}")
    return cards


def format_elapsed(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    return f"{hours}h {minutes}m {secs}s"


def safe_int(value, default=0):
    try:
        return int(value)
    except:
        return default


def safe_float(value, default=0.0):
    try:
        return float(value)
    except:
        return default


def mask_card(card):
    try:
        parts = card.split("|")

        if len(parts) != 4:
            return card

        cc = parts[0]

        return (
            f"{cc[:6]}"
            f"{'*' * (len(cc) - 10)}"
            f"{cc[-4:]}"
            f"|{parts[1]}|{parts[2]}|***"
        )

    except:
        return card
