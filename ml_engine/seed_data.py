"""
Seed 90 days of realistic laundry booking history for model training.

Run from the project root:
    python -m ml_engine.seed_data

Use --reset-window to replace existing bookings in the generated date window.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal, engine
from app.models import Base, Booking, Machine, Setting, Shop


SHOP_ID = 1
WINDOW_DAYS = 90
RANDOM_SEED = 42

SERVICE_CONFIG = {
    "Full Service": {"category": "Mixed Laundry", "base_price": 210.0, "min_kg": 5.0, "max_kg": 9.5, "weight": 0.38},
    "Regular Wash": {"category": "Clothes", "base_price": 65.0, "min_kg": 3.0, "max_kg": 7.0, "weight": 0.32},
    "Titan Wash": {"category": "Heavy Load", "base_price": 100.0, "min_kg": 6.0, "max_kg": 11.0, "weight": 0.20},
    "Comforter": {"category": "Beddings", "base_price": 150.0, "min_kg": 4.0, "max_kg": 8.0, "weight": 0.10},
}

CUSTOMER_FIRST_NAMES = [
    "Ana", "Ben", "Carla", "Dan", "Ella", "Francis", "Gia", "Hannah",
    "Ivan", "Jessa", "Karl", "Lara", "Mico", "Nina", "Owen", "Paula",
]
CUSTOMER_LAST_NAMES = [
    "Santos", "Reyes", "Garcia", "Cruz", "Bautista", "Ocampo", "Ramos",
    "Torres", "Flores", "Mendoza", "Castillo", "Aquino",
]


def _ensure_shop(db) -> Shop:
    shop = db.query(Shop).filter(Shop.id == SHOP_ID).first()
    if shop:
        return shop

    shop = Shop(id=SHOP_ID, shop_name="LaundryLink Demo Shop", address="Naga City")
    db.add(shop)
    db.flush()
    return shop


def _ensure_settings(db) -> None:
    settings = db.query(Setting).filter(Setting.shop_id == SHOP_ID).first()
    if settings:
        return

    db.add(
        Setting(
            shop_id=SHOP_ID,
            full_service_price=210.0,
            regular_wash_price=65.0,
            titan_wash_price=100.0,
            comforter_price=150.0,
            electricity_rate=12.0,
            water_rate=50.0,
            detergent_cost_per_load=10.0,
            off_peak_hours="8:00 AM - 11:00 AM",
            operation_start_hour=8,
        )
    )


def _ensure_machines(db) -> tuple[list[Machine], list[Machine]]:
    existing = db.query(Machine).filter(Machine.shop_id == SHOP_ID).all()
    washers = [machine for machine in existing if machine.machine_type.lower() == "washer"]
    dryers = [machine for machine in existing if machine.machine_type.lower() == "dryer"]

    if len(washers) >= 6 and len(dryers) >= 6:
        return washers, dryers

    next_washer = max([machine.machine_number for machine in washers], default=0) + 1
    next_dryer = max([machine.machine_number for machine in dryers], default=0) + 1

    while len(washers) < 6:
        machine = Machine(machine_type="Washer", machine_number=next_washer, status="Available", shop_id=SHOP_ID)
        db.add(machine)
        washers.append(machine)
        next_washer += 1

    while len(dryers) < 6:
        machine = Machine(machine_type="Dryer", machine_number=next_dryer, status="Available", shop_id=SHOP_ID)
        db.add(machine)
        dryers.append(machine)
        next_dryer += 1

    db.flush()
    return washers, dryers


def _booking_count_for_day(day_number: int, current_date: datetime, washer_count: int, dryer_count: int) -> int:
    weekday = current_date.weekday()
    weekend_multiplier = 1.65 if weekday in (5, 6) else 1.0
    friday_monday_bump = 1.25 if weekday in (0, 4) else 1.0
    trend = 1.0 + (day_number / WINDOW_DAYS) * 0.32
    seasonal_wave = 1.0 + 0.10 * math.sin(day_number / 7 * math.pi)

    max_daily_capacity = min(washer_count, dryer_count) * 10
    baseline = 13 * weekend_multiplier * friday_monday_bump * trend * seasonal_wave
    noisy_count = int(round(random.gauss(baseline, 2.2)))
    return max(6, min(noisy_count, max_daily_capacity))


def _random_timestamp_for_day(target_date: datetime) -> datetime:
    business_start = datetime.combine(target_date.date(), time(hour=8), tzinfo=timezone.utc)
    peak_blocks = [(9, 12), (15, 19), (19, 21)]
    start_hour, end_hour = random.choices(peak_blocks, weights=[0.30, 0.50, 0.20], k=1)[0]
    offset_minutes = random.randint(start_hour * 60, end_hour * 60 - 1)
    return business_start + timedelta(minutes=offset_minutes - 8 * 60)


def _build_booking(created_at: datetime, washers: list[Machine], dryers: list[Machine]) -> Booking:
    service_names = list(SERVICE_CONFIG)
    service_weights = [SERVICE_CONFIG[name]["weight"] for name in service_names]
    service_type = random.choices(service_names, weights=service_weights, k=1)[0]
    config = SERVICE_CONFIG[service_type]

    weight = round(random.uniform(config["min_kg"], config["max_kg"]), 2)
    loads = max(1, math.ceil(weight / 7.0))
    add_detergent = random.random() < 0.35
    add_delivery = random.random() < 0.12
    is_rush = random.random() < 0.16

    total_price = float(config["base_price"] * loads)
    if add_detergent:
        total_price += 40.0
    if add_delivery:
        total_price += 70.0
    if is_rush:
        total_price *= 1.40

    washer = random.choice(washers) if washers else None
    dryer = random.choice(dryers) if dryers and service_type in ("Full Service", "Comforter") else None

    return Booking(
        customer_name=f"{random.choice(CUSTOMER_FIRST_NAMES)} {random.choice(CUSTOMER_LAST_NAMES)}",
        service_type=service_type,
        category=config["category"],
        weight=weight,
        loads=loads,
        total_price=round(total_price, 2),
        booking_mode=random.choices(["Walk-in", "Online", "Pickup"], weights=[0.60, 0.30, 0.10], k=1)[0],
        service_duration=60 if service_type in ("Titan Wash", "Comforter") else 45,
        add_detergent=add_detergent,
        add_delivery=add_delivery,
        is_rush=is_rush,
        status=random.choices(["Claimed", "Ready", "In Progress"], weights=[0.88, 0.08, 0.04], k=1)[0],
        washer_id=washer.id if washer else None,
        dryer_id=dryer.id if dryer else None,
        shop_id=SHOP_ID,
        booking_timestamp=created_at,
        created_at=created_at,
    )


def seed_bookings(reset_window: bool = False) -> int:
    random.seed(RANDOM_SEED)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        _ensure_shop(db)
        _ensure_settings(db)
        washers, dryers = _ensure_machines(db)
        db.commit()

        today = datetime.now(timezone.utc).date()
        start_date = today - timedelta(days=WINDOW_DAYS - 1)
        window_start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        window_end = datetime.combine(today, time.max, tzinfo=timezone.utc)

        if reset_window:
            db.query(Booking).filter(
                Booking.shop_id == SHOP_ID,
                Booking.created_at >= window_start,
                Booking.created_at <= window_end,
            ).delete(synchronize_session=False)
            db.commit()

        created = 0
        for day_number in range(WINDOW_DAYS):
            target_date = datetime.combine(start_date + timedelta(days=day_number), time.min, tzinfo=timezone.utc)
            existing_count = db.query(Booking).filter(
                Booking.shop_id == SHOP_ID,
                Booking.created_at >= target_date,
                Booking.created_at < target_date + timedelta(days=1),
            ).count()
            if existing_count:
                continue

            daily_count = _booking_count_for_day(day_number, target_date, len(washers), len(dryers))
            bookings = [
                _build_booking(_random_timestamp_for_day(target_date), washers, dryers)
                for _ in range(daily_count)
            ]
            db.add_all(bookings)
            created += daily_count

        db.commit()
        return created
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed historical booking rows for forecasting.")
    parser.add_argument("--reset-window", action="store_true", help="Delete and replace bookings in the 90-day seed window.")
    args = parser.parse_args()

    created = seed_bookings(reset_window=args.reset_window)
    print(f"Seed complete. Created {created} booking rows.")


if __name__ == "__main__":
    main()
