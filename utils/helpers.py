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
    'ssl error',
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
    'http 500',
    'http 502',
    'http 503',
    'http 504',
    'cloudflare error',
    'cf-error',
    'challenge required',
    'access blocked',
)


def get_price_from_response(raw_response: dict) -> float:
    """Extract a float price from the API response."""
    try:
        price = raw_response.get('Price', '-')
        if price not in ('-', 0, None):
            price_clean = str(price).replace('$', '').replace(',', '').strip()
            return float(price_clean)
    except (ValueError, TypeError, AttributeError):
        pass
    return 0.0


def is_site_dead(response_msg: str, gateway: str, price) -> bool:
    """Full site-dead check: response keywords + gateway + price validation."""
    if not response_msg:
        return True

    if not gateway or gateway == "Unknown":
        return True

    if "Shopify" not in str(gateway):
        return True

    _dead_price_values = {"-", "$-", "$0", "$0.0", "0", "$0.00", "N/A", "0.0", "0.00"}
    if str(price).strip() in _dead_price_values:
        return True

    return is_dead_site_error(response_msg)


def is_dead_site_error(error_msg) -> bool:
    """Check if error message contains any dead site indicators."""
    if error_msg is None:
        return True

    error_str = str(error_msg).strip()

    if not error_str:
        return False

    error_lower = error_str.lower()

    return any(keyword in error_lower for keyword in _DEAD_INDICATORS)


def get_time() -> str:
    """Return current time formatted as DD/MM/YYYY HH:MM:SS."""
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def extract_cc(text: str) -> list:
    """Extract credit card details from text."""
    if not text or not isinstance(text, str):
        return []

    pattern = r'(\d{15,16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})'
    matches = re.findall(pattern, text)
    cards = []

    for match in matches:
        card, month, year, cvv = match

        # Normalize 2-digit year to 4-digit
        if len(year) == 2:
            year = "20" + year

        # Basic validation
        if not (1 <= int(month) <= 12):
            continue

        cards.append(f"{card}|{month}|{year}|{cvv}")

    return cards


def format_elapsed(seconds: int) -> str:
    """Format elapsed seconds into hours, minutes, seconds string."""
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return "0h 0m 0s"

    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    return f"{hours}h {minutes}m {secs}s"


def safe_int(value, default: int = 0) -> int:
    """Safely convert value to int, returning default on failure."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_float(value, default: float = 0.0) -> float:
    """Safely convert value to float, returning default on failure."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def mask_card(card: str) -> str:
    """Mask credit card number, keeping first 6 and last 4 digits visible."""
    if not card or not isinstance(card, str):
        return card

    try:
        parts = card.split("|")

        if len(parts) != 4:
            return card

        cc = parts[0]

        if len(cc) < 10:
            return card

        masked = (
            f"{cc[:6]}"
            f"{'*' * (len(cc) - 10)}"
            f"{cc[-4:]}"
            f"|{parts[1]}|{parts[2]}|***"
        )

        return masked

    except (AttributeError, IndexError):
        return card
