"""
SHOP STATUS (Open / Closed) — iisang source of truth kung bukas ba ang
shop para tumanggap ng booking mula sa mobile app.

Bukas lang ang shop kapag LAHAT ng ito ay totoo:
  1. accepting_bookings == True   (manual na toggle ng shop sa web)
  2. nasa loob ng operating hours (kung may itinakdang opening/closing;
     oras sa Asia/Manila)
  3. konektado ang terminal       (may heartbeat sa loob ng grace period,
                                   o — habang USE_LEGACY_ONLINE_FLAG — ang
                                   dating `is_online` flag)

Ang grace period ang pumipigil sa biglang "sarado" tuwing sandaling
naputol ang wifi, nag-sleep ang tab, o nag-restart ang server.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

# Ilang segundo mula sa huling heartbeat bago ituring na offline ang terminal.
# Nagpapadala ang web ng heartbeat bawat ~60s, kaya 3 miss bago magsara.
HEARTBEAT_GRACE_SECONDS = 180

# Habang hindi pa nasa lahat ng page ng web ang heartbeat (dapat nasa
# app shell/layout), ginagamit pa rin ang dating `Shop.is_online` bilang
# pangalawang signal. Gawing False kapag buo na ang heartbeat sa layout,
# para ang heartbeat lang ang magpasya (at hindi na stuck-"open" ang shop
# kapag nag-crash ang server).
USE_LEGACY_ONLINE_FLAG = True

MANILA = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class ShopStatus:
    is_open: bool
    reason_code: Optional[str]  # None | "paused" | "outside_hours" | "offline"
    message: Optional[str]      # customer-facing, walang teknikal na termino
    terminal_connected: bool
    within_hours: bool


def parse_hhmm(value: Optional[str]) -> Optional[int]:
    """'08:30' -> minuto mula hatinggabi (510). None kung blangko/mali."""
    if not value:
        return None
    try:
        hh, mm = value.split(":")
        hh, mm = int(hh), int(mm)
    except (ValueError, AttributeError):
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh * 60 + mm


def format_12h(value: Optional[str]) -> str:
    minutes = parse_hhmm(value)
    if minutes is None:
        return ""
    hh, mm = divmod(minutes, 60)
    suffix = "AM" if hh < 12 else "PM"
    hh12 = hh % 12 or 12
    return f"{hh12}:{mm:02d} {suffix}"


def is_within_hours(opening: Optional[str], closing: Optional[str], now: datetime) -> bool:
    """Walang itinakdang oras = laging within hours. Kayang humawak ng
    overnight (hal. 20:00 -> 02:00)."""
    o, c = parse_hhmm(opening), parse_hhmm(closing)
    if o is None or c is None or o == c:
        return True
    local = now.astimezone(MANILA)
    t = local.hour * 60 + local.minute
    if o < c:
        return o <= t < c
    return t >= o or t < c


def is_terminal_connected(shop, now: datetime) -> bool:
    seen = getattr(shop, "last_seen_at", None)
    if seen is not None:
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        if (now - seen).total_seconds() <= HEARTBEAT_GRACE_SECONDS:
            return True
    if USE_LEGACY_ONLINE_FLAG and getattr(shop, "is_online", False):
        return True
    return False


def compute_shop_status(shop, now: Optional[datetime] = None) -> ShopStatus:
    now = now or datetime.now(timezone.utc)

    accepting = getattr(shop, "accepting_bookings", True)
    accepting = True if accepting is None else bool(accepting)
    opening = getattr(shop, "opening_time", None)
    closing = getattr(shop, "closing_time", None)

    within = is_within_hours(opening, closing, now)
    connected = is_terminal_connected(shop, now)

    if not accepting:
        return ShopStatus(False, "paused",
                          "The shop isn't accepting new bookings right now.",
                          connected, within)
    if not within:
        o, c = format_12h(opening), format_12h(closing)
        return ShopStatus(False, "outside_hours",
                          f"The shop is closed right now. Open daily {o} – {c}.",
                          connected, within)
    if not connected:
        return ShopStatus(False, "offline",
                          "The shop is offline right now. Please try again later.",
                          connected, within)
    return ShopStatus(True, None, None, connected, within)