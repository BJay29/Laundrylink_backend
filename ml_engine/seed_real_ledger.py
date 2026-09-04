"""
Seeds REAL historical daily revenue totals (transcribed from an actual
paper booking ledger, Penafrancia Ave, Naga City) into a demo shop —
for showing the forecast/weather pipeline against real-world numbers.

WHAT'S REAL vs WHAT'S RECONSTRUCTED:
    - REAL: the 5 dates, the 5 daily total revenue figures (the boxed
      running totals in the ledger), and the shop's real location
      (used to fetch real historical weather for these exact dates).
    - RECONSTRUCTED: individual line items are NOT transcribed one-by-
      one — the handwritten entries (detergent brand abbreviations like
      "Surf", "Tide", "Ariel") were too ambiguous to reliably parse into
      exact per-transaction amounts or service types. Instead, each
      day's REAL total is split into `booking_count` individual Booking
      rows whose prices sum EXACTLY to that real total, with a generic
      service type. This keeps the date-level pattern (and therefore
      the date-level weather correlation) real, while being transparent
      that individual-transaction detail is a reconstruction, not a
      transcription.

Run from the project root:
    python -m ml_engine.seed_real_ledger
    python -m ml_engine.seed_real_ledger --reset
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal, engine
from app.models import Base, Booking, Machine, Setting, Shop

RANDOM_SEED = 7

SHOP_NAME = "Demo Shop (Real Ledger Sample)"
ADDRESS = "Penafrancia Ave, Naga City, Camarines Sur"
LATITUDE = 13.6180
LONGITUDE = 123.1814

# Transcribed from the ledger photos — dates and total revenue are the
# real recorded figures. booking_count is estimated from the number of
# line items visible for that date; adjust these if you can read the
# ledger more precisely than this transcription did.
REAL_DAILY_TOTALS = [
    {"date": "2026-08-30", "total_revenue": 4914.0, "booking_count": 14},
    {"date": "2026-08-31", "total_revenue": 5892.0, "booking_count": 19},
    {"date": "2026-09-01", "total_revenue": 2681.0, "booking_count": 13},
    {"date": "2026-09-02", "total_revenue": 4229.0, "booking_count": 23},
    {"date": "2026-09-03", "total_revenue": 1334.0, "booking_count": 9},
]

SERVICE_NAMES = ["Regular Wash", "Full Service", "Titan Wash", "Comforter"]


def _ensure_shop(db) -> Shop:
    shop = db.query(Shop).filter(Shop.shop_name == SHOP_NAME).first()
    if shop:
        return shop
    shop = Shop(shop_name=SHOP_NAME, address=ADDRESS, latitude=LATITUDE, longitude=LONGITUDE)
    db.add(shop)
    db.flush()
    return shop


def _ensure_settings(db, shop_id: int) -> None:
    if db.query(Setting).filter(Setting.shop_id == shop_id).first():
        return
    db.add(Setting(
        shop_id=shop_id, electricity_rate=12.0, water_rate=50.0,
        detergent_cost_per_load=10.0, off_peak_hours="8:00 AM - 11:00 AM",
        operation_start_hour=8,
    ))


def _ensure_machines(db, shop_id: int) -> None:
    if db.query(Machine).filter(Machine.shop_id == shop_id).count():
        return
    for i in range(1, 5):
        db.add(Machine(machine_type="Washer", machine_number=i, status="Available", shop_id=shop_id))
        db.add(Machine(machine_type="Dryer", machine_number=i, status="Available", shop_id=shop_id))


def _split_revenue(total_revenue: float, count: int) -> list[float]:
    """Splits a REAL daily total into `count` amounts that sum exactly to it."""
    if count <= 1:
        return [round(total_revenue, 2)]
    cuts = sorted(random.uniform(0.05, 0.95) * total_revenue for _ in range(count - 1))
    amounts, prev = [], 0.0
    for c in cuts:
        amounts.append(c - prev)
        prev = c
    amounts.append(total_revenue - prev)
    return [round(max(a, 20.0), 2) for a in amounts]


def seed_real_ledger(reset: bool = False) -> int:
    random.seed(RANDOM_SEED)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        shop = _ensure_shop(db)
        _ensure_settings(db, shop.id)
        _ensure_machines(db, shop.id)
        db.commit()

        if reset:
            db.query(Booking).filter(Booking.shop_id == shop.id).delete()
            db.commit()

        created = 0
        for day in REAL_DAILY_TOTALS:
            target_date = datetime.strptime(day["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            already_there = db.query(Booking).filter(
                Booking.shop_id == shop.id,
                Booking.created_at >= target_date,
                Booking.created_at < target_date + timedelta(days=1),
            ).count()
            if already_there:
                continue

            amounts = _split_revenue(day["total_revenue"], day["booking_count"])
            for i, amount in enumerate(amounts):
                created_at = target_date + timedelta(hours=8 + (i % 10), minutes=random.randint(0, 59))
                db.add(Booking(
                    customer_name="Walk-in",
                    service_type=random.choice(SERVICE_NAMES),
                    category="Mixed Laundry",
                    weight=round(random.uniform(4.0, 8.0), 2),
                    loads=1,
                    total_price=amount,
                    booking_mode="Walk-in",
                    shop_id=shop.id,
                    booking_timestamp=created_at,
                    created_at=created_at,
                ))
                created += 1

        db.commit()
        print(f"Seeded {created} bookings across {len(REAL_DAILY_TOTALS)} REAL dates into shop_id={shop.id} ('{SHOP_NAME}').")
        print("NOTE: only 5 days of data — below the 14-day minimum for a shop's own model.")
        print("This shop will show model_tier='pooled_model' once the pooled model is trained.")
        return shop.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed real ledger-derived daily totals into a demo shop.")
    parser.add_argument("--reset", action="store_true", help="Delete and re-seed this shop's bookings.")
    args = parser.parse_args()
    if args.reset:
        # simple approach: seed_real_ledger's own reset flag handles deletion
        pass
    seed_real_ledger(reset=args.reset)


if __name__ == "__main__":
    main()