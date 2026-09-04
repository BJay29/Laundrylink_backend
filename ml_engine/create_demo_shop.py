"""
Creates a NEW, DELIBERATELY EMPTY demo shop — for demonstrating the
cold-start / new-shop forecast state (Tier 2 pooled_model, or Tier 3
weather_only if the pooled model hasn't been trained yet).

Unlike ml_engine/seed_data.py (which fills a shop with 90 days of
fake booking history), this script creates:
    - a Shop row, with real latitude/longitude so weather works
    - a Setting row (factory defaults)
    - a few ServiceType rows (so average_ticket isn't the ₱150 fallback)
    - one Owner User account to log in with

It NEVER touches the Booking table — the shop stays at zero bookings
on purpose, every time you run it, so you always get a clean
"brand-new shop" state to demo without manually clicking through the
registration UI and Optimization Settings each time.

Run from the project root:
    python -m ml_engine.create_demo_shop
    python -m ml_engine.create_demo_shop --reset
    python -m ml_engine.create_demo_shop --shop-name "Sparkle Wash" --owner-email owner2@demo.com

Default coordinates are Naga City, Camarines Sur.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from passlib.context import CryptContext

from app.database import SessionLocal, engine
from app.models import Base, Shop, Setting, User, ServiceType

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEFAULT_SHOP_NAME = "LaundryLink Cold-Start Demo"
DEFAULT_OWNER_EMAIL = "coldstart-demo@laundrylink.test"
DEFAULT_OWNER_PASSWORD = "Demo12345"
DEFAULT_OWNER_NAME = "Demo Owner"

# Naga City, Camarines Sur — same region as the seeded shop, so both
# demo accounts pull weather from a realistic, comparable location.
DEFAULT_LATITUDE = 13.6218
DEFAULT_LONGITUDE = 123.1948

# A small starter catalog so the new shop's average_ticket reflects
# real prices instead of the ₱150 system fallback. Mirrors the pricing
# already used by ml_engine/seed_data.py and app/services/ai_engine.py
# so all three demo data sources agree with each other.
DEFAULT_SERVICES = [
    {"name": "Regular Wash", "price": 65.0, "duration_minutes": 45, "pricing_unit": "load"},
    {"name": "Full Service", "price": 210.0, "duration_minutes": 60, "pricing_unit": "load"},
    {"name": "Titan Wash", "price": 100.0, "duration_minutes": 60, "pricing_unit": "load"},
    {"name": "Comforter", "price": 150.0, "duration_minutes": 60, "pricing_unit": "piece"},
]


def create_demo_shop(
    shop_name: str = DEFAULT_SHOP_NAME,
    owner_email: str = DEFAULT_OWNER_EMAIL,
    owner_password: str = DEFAULT_OWNER_PASSWORD,
    owner_name: str = DEFAULT_OWNER_NAME,
    latitude: float = DEFAULT_LATITUDE,
    longitude: float = DEFAULT_LONGITUDE,
    reset: bool = False,
) -> int:
    """
    Creates the empty demo shop + owner account. Returns the new shop_id.
    If --reset is passed and a shop with this owner_email already exists,
    it is deleted first (cascades to its Settings/ServiceTypes/etc. via
    the ORM relationships already defined on Shop) so you always get a
    truly clean zero-bookings state on every dry run.
    """
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing_owner = db.query(User).filter(User.email == owner_email).first()

        if existing_owner:
            if not reset:
                print(
                    f"An account with email '{owner_email}' already exists "
                    f"(shop_id={existing_owner.shop_id}). Re-run with --reset "
                    f"to wipe and recreate it, or use a different --owner-email."
                )
                return existing_owner.shop_id

            existing_shop = db.query(Shop).filter(Shop.id == existing_owner.shop_id).first()
            if existing_shop:
                db.delete(existing_shop)  # cascades via Shop's relationships
                db.commit()
                print(f"Reset: deleted existing shop_id={existing_shop.id} and its data.")

        shop = Shop(
            shop_name=shop_name,
            address="Naga City, Camarines Sur",
            latitude=latitude,
            longitude=longitude,
            is_published=True,
            has_delivery=False,
            delivery_fee=0.0,
        )
        db.add(shop)
        db.flush()  # need shop.id before creating dependent rows

        db.add(
            Setting(
                shop_id=shop.id,
                electricity_rate=12.0,
                water_rate=50.0,
                detergent_cost_per_load=10.0,
                minimum_weight_kg=6.0,
                off_peak_hours="8:00 AM - 11:00 AM",
                operation_start_hour=8,
            )
        )

        for service in DEFAULT_SERVICES:
            db.add(
                ServiceType(
                    shop_id=shop.id,
                    name=service["name"],
                    price=service["price"],
                    is_active=True,
                    duration_minutes=service["duration_minutes"],
                    pricing_unit=service["pricing_unit"],
                )
            )

        owner = User(
            email=owner_email,
            hashed_password=pwd_context.hash(owner_password),
            role="owner",
            full_name=owner_name,
            shop_id=shop.id,
            is_active=True,
        )
        db.add(owner)

        db.commit()

        print(f"Created empty demo shop: '{shop_name}' (shop_id={shop.id})")
        print(f"  Owner login: {owner_email} / {owner_password}")
        print(f"  Location: ({latitude}, {longitude})")
        print(f"  Services configured: {len(DEFAULT_SERVICES)}")
        print(f"  Bookings: 0 (deliberately empty — this is the point)")
        return shop.id

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an empty demo shop for cold-start forecast demos.")
    parser.add_argument("--shop-name", default=DEFAULT_SHOP_NAME)
    parser.add_argument("--owner-email", default=DEFAULT_OWNER_EMAIL)
    parser.add_argument("--owner-password", default=DEFAULT_OWNER_PASSWORD)
    parser.add_argument("--owner-name", default=DEFAULT_OWNER_NAME)
    parser.add_argument("--latitude", type=float, default=DEFAULT_LATITUDE)
    parser.add_argument("--longitude", type=float, default=DEFAULT_LONGITUDE)
    parser.add_argument("--reset", action="store_true", help="Delete and recreate if this owner_email already exists.")
    args = parser.parse_args()

    create_demo_shop(
        shop_name=args.shop_name,
        owner_email=args.owner_email,
        owner_password=args.owner_password,
        owner_name=args.owner_name,
        latitude=args.latitude,
        longitude=args.longitude,
        reset=args.reset,
    )


if __name__ == "__main__":
    main()