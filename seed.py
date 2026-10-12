"""Create a realistic sample sales database (customers, products, orders, invoices).

Dates are relative to today so questions like "last quarter" always have data.
The random generator is seeded, so the same day always produces the same data.
"""

from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from db import DEFAULT_DB_PATH

SCHEMA = """
CREATE TABLE customers (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    company     TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    country     TEXT NOT NULL,
    segment     TEXT NOT NULL CHECK (segment IN ('SMB', 'Mid-Market', 'Enterprise')),
    created_at  TEXT NOT NULL
);

CREATE TABLE products (
    id          INTEGER PRIMARY KEY,
    sku         TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    unit_price  REAL NOT NULL
);

CREATE TABLE orders (
    id           INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    order_date   TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('completed', 'processing', 'cancelled'))
);

CREATE TABLE order_items (
    id          INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id),
    product_id  INTEGER NOT NULL REFERENCES products(id),
    quantity    INTEGER NOT NULL CHECK (quantity > 0),
    unit_price  REAL NOT NULL
);

CREATE TABLE invoices (
    id           INTEGER PRIMARY KEY,
    order_id     INTEGER NOT NULL UNIQUE REFERENCES orders(id),
    issued_date  TEXT NOT NULL,
    due_date     TEXT NOT NULL,
    amount       REAL NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('paid', 'unpaid', 'overdue')),
    paid_date    TEXT
);

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_invoices_status ON invoices(status);
"""

FIRST_NAMES = [
    "Olivia", "Liam", "Emma", "Noah", "Ava", "Lucas", "Mia", "Ethan", "Sophia", "Mateo",
    "Isla", "Arjun", "Hana", "Daniel", "Chloe", "Rizky", "Grace", "Kenji", "Amelia", "Felix",
]
LAST_NAMES = [
    "Smith", "Johnson", "Muller", "Tan", "Wijaya", "Brown", "Nguyen", "Garcia", "Clarke", "Schmidt",
    "Lim", "Patel", "Wilson", "Santoso", "Kowalski", "Rossi", "Haddad", "Okafor", "Lee", "Martin",
]
COMPANIES = [
    "Northwind Traders", "Bluepeak Logistics", "Cobalt Health", "Lumen Retail", "Harbor & Pine",
    "Atlas Fintech", "Verde Foods", "Kite Analytics", "Summit Legal", "Orbit Media",
    "Pioneer Dental", "Nimbus Cloud Co", "Redwood Realty", "Sagebrush Energy", "Tidal Marine",
    "Quartz Manufacturing", "Maple Education", "Ironclad Security", "Juniper Travel", "Nova Biotech",
    "Brightline Studios", "Copperleaf Hotels", "Driftwood Apparel", "Evergreen Clinics", "Falcon Freight",
    "Granite Construction Co", "Horizon Insurance", "Indigo Software", "Jetstream Airlines", "Keystone Accounting",
    "Lighthouse Nonprofit", "Meridian Pharma", "Northstar Robotics", "Oakridge Farms", "Prism Marketing",
    "Quill Publishing", "Riverbend Schools", "Silverline Telecom", "Trailhead Outdoors", "Upland Coffee Roasters",
]
COUNTRIES = ["US", "US", "US", "GB", "DE", "AU", "CA", "NL", "SG", "ID"]
SEGMENT_WEIGHTS = {"SMB": 0.55, "Mid-Market": 0.3, "Enterprise": 0.15}
SEGMENT_ORDER_WEIGHT = {"SMB": 1, "Mid-Market": 2.5, "Enterprise": 5}
SEGMENT_QTY = {"SMB": (1, 3), "Mid-Market": (2, 8), "Enterprise": (5, 25)}

PRODUCTS = [
    ("Software License", "Analytics Pro - Annual Seat", 480.0),
    ("Software License", "Analytics Starter - Annual Seat", 180.0),
    ("Software License", "Reporting Add-on", 120.0),
    ("Software License", "Data Connector Pack", 260.0),
    ("Software License", "AI Assistant Add-on", 340.0),
    ("Support Plan", "Standard Support (12 months)", 900.0),
    ("Support Plan", "Premium Support (12 months)", 2400.0),
    ("Support Plan", "Onboarding Package", 1500.0),
    ("Hardware", "Edge Gateway Device", 650.0),
    ("Hardware", "Barcode Scanner Kit", 210.0),
    ("Hardware", "Thermal Receipt Printer", 175.0),
    ("Hardware", "POS Terminal", 820.0),
    ("Training", "Admin Training (remote, 1 day)", 750.0),
    ("Training", "Power User Workshop", 1100.0),
    ("Training", "Self-paced Course Bundle", 95.0),
    ("Consulting", "Data Migration (per day)", 1200.0),
    ("Consulting", "Dashboard Design Sprint", 3200.0),
    ("Consulting", "Integration Setup", 1800.0),
    ("Consulting", "Process Audit", 2600.0),
    ("Consulting", "Custom Report Build", 650.0),
]

NUM_CUSTOMERS = 40
NUM_ORDERS = 170
HISTORY_DAYS = 365


def build_database(path: Path, today: date | None = None, seed: int = 42) -> Path:
    today = today or date.today()
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        customers = _customers(rng, today)
        conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?)", customers)

        products = [
            (i, f"{category[:3].upper()}-{i:03d}", name, category, price)
            for i, (category, name, price) in enumerate(PRODUCTS, start=1)
        ]
        conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?)", products)

        orders, items, invoices = _orders(rng, today, customers, products)
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", orders)
        conn.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", items)
        conn.executemany("INSERT INTO invoices VALUES (?, ?, ?, ?, ?, ?, ?)", invoices)
        conn.commit()
    finally:
        conn.close()
    return path


def _customers(rng: random.Random, today: date) -> list[tuple]:
    rows = []
    used_emails = set()
    for cid in range(1, NUM_CUSTOMERS + 1):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        company = COMPANIES[cid - 1]
        domain = company.lower().replace("&", "and").replace(" ", "")
        email = f"{first.lower()}.{last.lower()}@{domain}.com"
        while email in used_emails:
            email = f"{first.lower()}.{last.lower()}{rng.randint(2, 99)}@{domain}.com"
        used_emails.add(email)
        segment = rng.choices(list(SEGMENT_WEIGHTS), weights=list(SEGMENT_WEIGHTS.values()))[0]
        created = today - timedelta(days=rng.randint(HISTORY_DAYS + 30, HISTORY_DAYS + 540))
        rows.append((cid, f"{first} {last}", company, email, rng.choice(COUNTRIES), segment, created.isoformat()))
    return rows


def _orders(rng: random.Random, today: date, customers: list[tuple], products: list[tuple]):
    weights = [SEGMENT_ORDER_WEIGHT[c[5]] for c in customers]
    orders, items, invoices = [], [], []
    item_id = 1
    order_dates = sorted(today - timedelta(days=rng.randint(1, HISTORY_DAYS)) for _ in range(NUM_ORDERS))

    for oid, order_date in enumerate(order_dates, start=1):
        customer = rng.choices(customers, weights=weights)[0]
        age = (today - order_date).days
        status = "processing" if age < 7 and rng.random() < 0.6 else ("cancelled" if rng.random() < 0.06 else "completed")
        orders.append((oid, customer[0], order_date.isoformat(), status))

        qty_low, qty_high = SEGMENT_QTY[customer[5]]
        total = 0.0
        for product in rng.sample(products, k=rng.randint(1, 4)):
            quantity = rng.randint(qty_low, qty_high) if product[3] == "Software License" else rng.randint(1, 3)
            price = round(product[4] * rng.choice([1.0, 1.0, 1.0, 0.9, 0.85]), 2)
            items.append((item_id, oid, product[0], quantity, price))
            item_id += 1
            total += quantity * price

        if status == "cancelled":
            continue
        due = order_date + timedelta(days=30)
        if due >= today:
            paid = rng.random() < 0.4
        else:
            paid = rng.random() < 0.88
        paid_date = (order_date + timedelta(days=rng.randint(3, 40))) if paid else None
        if paid_date and paid_date > today:
            paid_date = today
        inv_status = "paid" if paid else ("overdue" if due < today else "unpaid")
        invoices.append((
            len(invoices) + 1, oid, order_date.isoformat(), due.isoformat(), round(total, 2),
            inv_status, paid_date.isoformat() if paid_date else None,
        ))
    return orders, items, invoices


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Where to write the database")
    args = parser.parse_args()
    path = build_database(args.db)
    print(f"Sample database written to {path}")


if __name__ == "__main__":
    main()
