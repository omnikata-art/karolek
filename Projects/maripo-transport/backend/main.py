"""
main.py — FastAPI backend for Maripo Transport
"""
from typing import Optional, Union
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import database

# ─── Pydantic models ────────────────────────────────────────────────────────

class CarCreate(BaseModel):
    name: str
    plate: str = ""
    brand: str = ""
    max_capacity_kg: int = 5000

class CarUpdate(BaseModel):
    name: Optional[str] = None
    plate: Optional[str] = None
    brand: Optional[str] = None
    max_capacity_kg: Optional[int] = None
    status: Optional[str] = None
    current_location: Optional[str] = None

class CargoCreate(BaseModel):
    name: str
    weight_kg: int = 0
    description: str = ""
    priority: int = 1
    pickup_address: str = ""
    delivery_address: str = ""

class CargoUpdate(BaseModel):
    name: Optional[str] = None
    weight_kg: Optional[int] = None
    description: Optional[str] = None
    priority: Optional[int] = None
    status: Optional[str] = None
    pickup_address: Optional[str] = None
    delivery_address: Optional[str] = None

class TransportCreate(BaseModel):
    car_id: int
    cargo_id: int
    start_time: str
    end_time: str
    notes: str = ""

class TransportUpdate(BaseModel):
    car_id: Optional[int] = None
    cargo_id: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None

class RescheduleRequest(BaseModel):
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    car_id: Optional[int] = None

# ─── FastAPI app ─────────────────────────────────────────────────────────────

app = FastAPI(title="Maripo Transport API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent.parent

# ─── Helpers ─────────────────────────────────────────────────────────────────

def row_to_dict(row) -> Optional[dict]:
    if row is None:
        return None
    return dict(row)

def get_conn():
    return database.get_conn()

def parse_datetime(val: str) -> datetime:
    val = val.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(val)
    except ValueError:
        return datetime.strptime(val, "%Y-%m-%d")

def check_conflict(conn, car_id: int, start_time: str, end_time: str, exclude_id: Optional[int] = None) -> Optional[dict]:
    """Check if car is already assigned during the given time range."""
    query = """
        SELECT t.id, t.start_time, t.end_time, c.name as car_name, g.name as cargo_name
        FROM transports t
        JOIN cars c ON t.car_id = c.id
        JOIN cargos g ON t.cargo_id = g.id
        WHERE t.car_id = ?
          AND t.status NOT IN ('cancelled', 'completed')
          AND (
            (t.start_time <= ? AND t.end_time > ?) OR
            (t.start_time < ? AND t.end_time >= ?) OR
            (t.start_time >= ? AND t.end_time <= ?)
          )
    """
    args = [car_id, end_time, start_time, end_time, start_time, start_time, end_time]
    if exclude_id:
        query += " AND t.id != ?"
        args.append(exclude_id)

    row = conn.execute(query, args).fetchone()
    if row:
        return {
            "existingId": row["id"],
            "carName": row["car_name"],
            "cargoName": row["cargo_name"],
            "startTime": row["start_time"],
            "endTime": row["end_time"],
        }
    return None

# ─── Board (full state) ──────────────────────────────────────────────────────

def get_board_data():
    conn = get_conn()
    cars = [row_to_dict(r) for r in conn.execute("SELECT * FROM cars ORDER BY id").fetchall()]
    cargos = [row_to_dict(r) for r in conn.execute("SELECT * FROM cargos ORDER BY id DESC").fetchall()]
    transports = [row_to_dict(r) for r in conn.execute("""
        SELECT t.*, c.name as car_name, c.plate as car_plate, c.brand as car_brand,
               g.name as cargo_name, g.weight_kg, g.priority, g.pickup_address, g.delivery_address
        FROM transports t
        JOIN cars c ON t.car_id = c.id
        JOIN cargos g ON t.cargo_id = g.id
        ORDER BY t.start_time
    """).fetchall()]
    conn.close()

    # Find unassigned cargos (not in any active transport)
    assigned_ids = {t["cargo_id"] for t in transports if t["status"] not in ("cancelled", "completed")}
    unassigned_cargos = [c for c in cargos if c["id"] not in assigned_ids]

    # Detect conflicts
    conflicts = []
    for car in cars:
        active = [t for t in transports if t["car_id"] == car["id"] and t["status"] not in ("cancelled", "completed")]
        for i, t1 in enumerate(active):
            for t2 in active[i+1:]:
                s1, e1 = parse_datetime(t1["start_time"]), parse_datetime(t1["end_time"])
                s2, e2 = parse_datetime(t2["start_time"]), parse_datetime(t2["end_time"])
                if s1 <= s2 and e1 > s2 or s2 <= s1 and e2 > s1:
                    conflicts.append({
                        "transportIds": [t1["id"], t2["id"]],
                        "carId": car["id"],
                        "carName": car["name"],
                    })

    return {
        "cars": cars,
        "cargos": cargos,
        "unassignedCargos": unassigned_cargos,
        "transports": transports,
        "conflicts": conflicts,
    }

# ─── Cars ───────────────────────────────────────────────────────────────────

@app.get("/api/cars")
def list_cars():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM cars ORDER BY id").fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]

@app.post("/api/cars")
def create_car(data: CarCreate):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO cars (name, plate, brand, max_capacity_kg) VALUES (?, ?, ?, ?)",
        (data.name, data.plate, data.brand, data.max_capacity_kg)
    )
    car_id = cur.lastrowid
    conn.commit()
    car = row_to_dict(cur.execute("SELECT * FROM cars WHERE id = ?", (car_id,)).fetchone())
    conn.close()
    return car

@app.patch("/api/cars/{car_id}")
def update_car(car_id: int, data: CarUpdate):
    conn = get_conn()
    cur = conn.cursor()
    fields = []
    values = []
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            fields.append(f"{field} = ?")
            values.append(value)
    if not fields:
        raise HTTPException(400, "No fields to update")
    values.append(car_id)
    cur.execute(f"UPDATE cars SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    car = row_to_dict(cur.execute("SELECT * FROM cars WHERE id = ?", (car_id,)).fetchone())
    conn.close()
    if not car:
        raise HTTPException(404, "Car not found")
    return car

@app.delete("/api/cars/{car_id}")
def delete_car(car_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM cars WHERE id = ?", (car_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    if not deleted:
        raise HTTPException(404, "Car not found")
    return {"ok": True}

# ─── Cargos ─────────────────────────────────────────────────────────────────

@app.get("/api/cargos")
def list_cargos(status: str = Query(None), priority: int = Query(None)):
    conn = get_conn()
    query = "SELECT * FROM cargos WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if priority:
        query += " AND priority = ?"
        params.append(priority)
    query += " ORDER BY id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]

@app.post("/api/cargos")
def create_cargo(data: CargoCreate):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO cargos (name, weight_kg, description, priority, pickup_address, delivery_address) VALUES (?, ?, ?, ?, ?, ?)",
        (data.name, data.weight_kg, data.description, data.priority, data.pickup_address, data.delivery_address)
    )
    cargo_id = cur.lastrowid
    conn.commit()
    cargo = row_to_dict(cur.execute("SELECT * FROM cargos WHERE id = ?", (cargo_id,)).fetchone())
    conn.close()
    return cargo

@app.patch("/api/cargos/{cargo_id}")
def update_cargo(cargo_id: int, data: CargoUpdate):
    conn = get_conn()
    cur = conn.cursor()
    fields = []
    values = []
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            fields.append(f"{field} = ?")
            values.append(value)
    if not fields:
        raise HTTPException(400, "No fields to update")
    values.append(cargo_id)
    cur.execute(f"UPDATE cargos SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    cargo = row_to_dict(cur.execute("SELECT * FROM cargos WHERE id = ?", (cargo_id,)).fetchone())
    conn.close()
    if not cargo:
        raise HTTPException(404, "Cargo not found")
    return cargo

@app.delete("/api/cargos/{cargo_id}")
def delete_cargo(cargo_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM cargos WHERE id = ?", (cargo_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    if not deleted:
        raise HTTPException(404, "Cargo not found")
    return {"ok": True}

# ─── Transports ─────────────────────────────────────────────────────────────

@app.get("/api/transports")
def list_transports():
    conn = get_conn()
    rows = conn.execute("""
        SELECT t.*, c.name as car_name, c.plate as car_plate, c.brand as car_brand,
               g.name as cargo_name, g.weight_kg, g.priority, g.pickup_address, g.delivery_address
        FROM transports t
        JOIN cars c ON t.car_id = c.id
        JOIN cargos g ON t.cargo_id = g.id
        ORDER BY t.start_time
    """).fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]

@app.post("/api/transports")
def create_transport(data: TransportCreate, force: bool = Query(False)):
    conn = get_conn()
    cur = conn.cursor()

    # Check cargo exists
    cargo = cur.execute("SELECT id FROM cargos WHERE id = ?", (data.cargo_id,)).fetchone()
    if not cargo:
        conn.close()
        raise HTTPException(404, "Cargo not found")

    # Check car exists
    car = cur.execute("SELECT id FROM cars WHERE id = ?", (data.car_id,)).fetchone()
    if not car:
        conn.close()
        raise HTTPException(404, "Car not found")

    # Check conflict
    conflict = check_conflict(conn, data.car_id, data.start_time, data.end_time)
    if conflict and not force:
        conn.close()
        return {"conflict": conflict, "transport": None}

    cur.execute(
        "INSERT INTO transports (car_id, cargo_id, start_time, end_time, notes) VALUES (?, ?, ?, ?, ?)",
        (data.car_id, data.cargo_id, data.start_time, data.end_time, data.notes)
    )
    transport_id = cur.lastrowid

    # Update cargo status
    cur.execute("UPDATE cargos SET status = 'planned' WHERE id = ?", (data.cargo_id,))

    conn.commit()
    transport = row_to_dict(cur.execute("""
        SELECT t.*, c.name as car_name, c.plate as car_plate, c.brand as car_brand,
               g.name as cargo_name, g.weight_kg, g.priority
        FROM transports t
        JOIN cars c ON t.car_id = c.id
        JOIN cargos g ON t.cargo_id = g.id
        WHERE t.id = ?
    """, (transport_id,)).fetchone())
    conn.close()
    return {"transport": transport, "conflict": None}

@app.patch("/api/transports/{transport_id}")
def update_transport(transport_id: int, data: TransportUpdate):
    conn = get_conn()
    cur = conn.cursor()
    fields = []
    values = []
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            fields.append(f"{field} = ?")
            values.append(value)
    if not fields:
        conn.close()
        raise HTTPException(400, "No fields to update")
    values.append(transport_id)
    cur.execute(f"UPDATE transports SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    transport = row_to_dict(cur.execute("""
        SELECT t.*, c.name as car_name, c.plate as car_plate, c.brand as car_brand,
               g.name as cargo_name, g.weight_kg, g.priority
        FROM transports t
        JOIN cars c ON t.car_id = c.id
        JOIN cargos g ON t.cargo_id = g.id
        WHERE t.id = ?
    """, (transport_id,)).fetchone())
    conn.close()
    if not transport:
        raise HTTPException(404, "Transport not found")
    return transport

@app.patch("/api/transports/{transport_id}/reschedule")
def reschedule_transport(transport_id: int, data: RescheduleRequest, force: bool = Query(False)):
    conn = get_conn()
    cur = conn.cursor()

    t = cur.execute("SELECT * FROM transports WHERE id = ?", (transport_id,)).fetchone()
    if not t:
        conn.close()
        raise HTTPException(404, "Transport not found")

    new_car = data.car_id if data.car_id is not None else t["car_id"]
    new_start = data.start_time if data.start_time is not None else t["start_time"]
    new_end = data.end_time if data.end_time is not None else t["end_time"]

    conflict = check_conflict(conn, new_car, new_start, new_end, exclude_id=transport_id)
    if conflict and not force:
        conn.close()
        return {"transport": row_to_dict(t), "conflict": conflict}

    cur.execute(
        "UPDATE transports SET car_id=?, start_time=?, end_time=? WHERE id=?",
        (new_car, new_start, new_end, transport_id)
    )
    conn.commit()

    transport = row_to_dict(cur.execute("""
        SELECT t.*, c.name as car_name, c.plate as car_plate, c.brand as car_brand,
               g.name as cargo_name, g.weight_kg, g.priority
        FROM transports t
        JOIN cars c ON t.car_id = c.id
        JOIN cargos g ON t.cargo_id = g.id
        WHERE t.id = ?
    """, (transport_id,)).fetchone())
    conn.close()
    return {"transport": transport, "conflict": None}

@app.delete("/api/transports/{transport_id}")
def delete_transport(transport_id: int):
    conn = get_conn()
    cur = conn.cursor()
    t = cur.execute("SELECT cargo_id FROM transports WHERE id = ?", (transport_id,)).fetchone()
    if not t:
        conn.close()
        raise HTTPException(404, "Transport not found")
    cargo_id = t["cargo_id"]
    cur.execute("DELETE FROM transports WHERE id = ?", (transport_id,))
    cur.execute("UPDATE cargos SET status = 'new' WHERE id = ?", (cargo_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

# ─── Board ───────────────────────────────────────────────────────────────────

@app.get("/api/board")
def get_board():
    return get_board_data()

# ─── Static (single HTML) ────────────────────────────────────────────────────

@app.get("/")
def serve_index():
    return FileResponse(BASE_DIR / "index.html")

# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    database.init_db()
    database.seed_demo()
    print("▶ Maripo Transport: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)