"""
database.py — SQLite schema + helpers for Maripo Transport
"""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "maripo.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            plate TEXT DEFAULT '',
            brand TEXT DEFAULT '',
            max_capacity_kg INTEGER NOT NULL DEFAULT 5000,
            status TEXT NOT NULL DEFAULT 'available',
            current_location TEXT DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cargos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            weight_kg INTEGER NOT NULL DEFAULT 0,
            description TEXT DEFAULT '',
            priority INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'new',
            pickup_address TEXT DEFAULT '',
            delivery_address TEXT DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            car_id INTEGER NOT NULL,
            cargo_id INTEGER NOT NULL,
            start_time DATETIME NOT NULL,
            end_time DATETIME NOT NULL,
            status TEXT NOT NULL DEFAULT 'scheduled',
            notes TEXT DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (car_id) REFERENCES cars(id) ON DELETE CASCADE,
            FOREIGN KEY (cargo_id) REFERENCES cargos(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()

def seed_demo():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM cars")
    if cur.fetchone()[0] > 0:
        conn.close()
        return

    cars = [
        ("Sokół 1", "WA 12345", "Mercedes Actros", 20000, "available"),
        ("Sokół 2", "WA 67890", "Volvo FH 500", 18000, "available"),
        ("Sokół 3", "KR 11111", "DAF XF 480", 15000, "in_transit"),
        ("Sokół 4", "GD 22222", "MAN TGX 500", 22000, "available"),
    ]
    cur.executemany(
        "INSERT INTO cars (name, plate, brand, max_capacity_kg, status) VALUES (?, ?, ?, ?, ?)",
        cars
    )

    cargos = [
        ("Palety meblowe", 3500, "Meble z Bielska-Białej", 2, "new", "Bielsko-Biała, ul. Fabryczna 5", "Wrocław, ul. Długa 12"),
        ("Maszyna pakująca", 8000, "Linia pakująca do hurtowni", 3, "new", "Poznań, Park Przemysłowy 3", "Warszawa, ul. Prosta 88"),
        ("Towary spożywcze", 1200, "Produkty suche — kiermasz", 1, "new", "Kraków, hurtownia Społem", "Katowice, sklep Groszek"),
        ("Elementy ogrodowe", 600, "Donice ceramiczne", 1, "new", "Bolesławiec, fabryka ceramiki", "Łódź, centrum ogrodnicze"),
        ("Materiały budowlane", 5000, "Płyty g-k na palecie", 2, "new", "Wrocław, skład budowlany", "Jelenia Góra, market"),
    ]
    cur.executemany(
        "INSERT INTO cargos (name, weight_kg, description, priority, status, pickup_address, delivery_address) VALUES (?, ?, ?, ?, ?, ?, ?)",
        cargos
    )

    # One demo transport
    from datetime import timedelta
    now = datetime.now()
    start = now.replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)
    end = start + timedelta(days=2)
    cur.execute(
        "INSERT INTO transports (car_id, cargo_id, start_time, end_time, status) VALUES (?, ?, ?, ?, ?)",
        (1, 1, start.isoformat(), end.isoformat(), "scheduled")
    )

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    seed_demo()
    print("✓ DB ready at", DB_PATH)