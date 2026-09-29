"""
demo_data.py - Fill the separate DEMO database with realistic sample data.

Used only with `python main.py --demo`. Your real database is never touched.
All entries go through the normal business rules in logic.py (including FEFO).
"""

import random
from datetime import date, datetime, time, timedelta

import db
import logic

# name, unit, reorder level, typical quantity per dispensing
DEMO_MEDICINES = [
    ("Paracetamol 500mg", "tablets", 200, 20),
    ("Amoxicillin 500mg", "capsules", 100, 21),
    ("Ibuprofen 400mg", "tablets", 150, 15),
    ("Metformin 500mg", "tablets", 120, 30),
    ("Amlodipine 5mg", "tablets", 60, 30),
    ("ORS sachets", "sachets", 50, 6),
    ("Cough syrup 100ml", "bottles", 20, 1),
    ("Artemether/Lumefantrine 20/120", "packs", 30, 1),
    ("Ciprofloxacin 500mg", "tablets", 80, 10),
    ("Omeprazole 20mg", "capsules", 60, 14),
    ("Salbutamol inhaler", "inhalers", 10, 1),
    ("Vitamin B complex", "tablets", 100, 30),
    ("Ferrous sulphate 200mg", "tablets", 100, 30),
    ("Diclofenac gel", "tubes", 15, 1),
    ("Cetirizine 10mg", "tablets", 50, 10),
    ("Insulin (vial)", "vials", 5, 1),
]

PRESCRIBERS = ["Dr Mensah", "Dr Owusu", "Nurse Adjei", "Dr Boateng", "Dr Asante"]


def seed_demo(conn, today: date | None = None) -> bool:
    """Add sample data if the demo database is empty. Returns True if data was added."""
    if db.list_medicines(conn):
        return False
    today = today or date.today()
    rng = random.Random(2024)
    start = today - timedelta(days=100)

    def stamp(d: date) -> datetime:
        return datetime.combine(d, time(8 + rng.randrange(9), rng.randrange(60)))

    # 1) Stock deliveries: 2-3 batches per medicine with different expiry dates.
    for i, (name, unit, reorder, per_dose) in enumerate(DEMO_MEDICINES):
        n_batches = 3 if i % 3 == 0 else 2
        for b in range(n_batches):
            received_on = start + timedelta(days=rng.randrange(0, 30) + b * 25)
            received_on = min(received_on, today)
            if name.startswith("Insulin"):
                qty = 6
            else:
                qty = per_dose * rng.randrange(12, 30)
            # Mostly long expiry, a few expiring soon or already expired for the alerts.
            if i == 2 and b == 0:
                expiry = today - timedelta(days=12)       # expired, still has stock
            elif i % 4 == 1 and b == 0:
                expiry = today + timedelta(days=rng.randrange(20, 80))  # expiring soon
            else:
                expiry = today + timedelta(days=rng.randrange(150, 900))
            if expiry <= received_on:
                expiry = received_on + timedelta(days=5)
            logic.add_stock(conn, received_on, name, qty, f"{1000 + i * 10 + b:05d}", expiry,
                            unit=unit, reorder_level=reorder, today=today,
                            now=stamp(received_on))

    # 2) Daily dispensing for the last ~70 days (more on weekdays).
    day = start + timedelta(days=30)
    patient_no = 1
    while day <= today:
        entries = rng.randrange(4, 12) if day.weekday() < 5 else rng.randrange(0, 4)
        for _ in range(entries):
            name, _unit, _reorder, per_dose = rng.choice(DEMO_MEDICINES)
            qty = max(1, int(per_dose * rng.uniform(0.5, 1.5)))
            prescriber = rng.choice(PRESCRIBERS) if rng.random() > 0.05 else ""
            try:
                logic.dispense(conn, day, name, qty, patient_id=f"P{patient_no:05d}",
                               prescriber=prescriber, today=today, now=stamp(day))
                patient_no += 1
            except logic.InsufficientStockError:
                pass  # ran out - that's fine, it makes the LOW / OUT alerts interesting
        day += timedelta(days=1)
    return True
