from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3

app = Flask(__name__)
CORS(app)

DB = "database.db"

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

# ---------------- INIT DATABASE ----------------
def init_db():
    db = get_db()

    db.execute("""
    CREATE TABLE IF NOT EXISTS users(
        username TEXT PRIMARY KEY,
        password TEXT,
        role TEXT
    )
    """)

    db.execute("""
    CREATE TABLE IF NOT EXISTS equipment(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        type TEXT,
        location TEXT,
        price REAL,
        owner TEXT,
        available INTEGER DEFAULT 1
    )
    """)

    db.execute("""
    CREATE TABLE IF NOT EXISTS bookings(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id INTEGER,
    equipment_name TEXT,
    farmer TEXT,
    owner TEXT,
    booking_date TEXT,
    start_time TEXT,
    hours INTEGER,
    status TEXT DEFAULT 'Pending',
    rating INTEGER DEFAULT 0
    )
    """)
    db.execute("""
    CREATE TABLE IF NOT EXISTS payments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER,
    farmer TEXT,
    owner TEXT,
    equipment_name TEXT,
    amount REAL,
    transaction_id TEXT,
    payment_date TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    db.execute("""
    CREATE TABLE IF NOT EXISTS gps_locations(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id INTEGER,
    latitude REAL,
    longitude REAL,
    time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    db.execute("""
    CREATE TABLE IF NOT EXISTS ratings(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER,
    equipment_id INTEGER,
    farmer TEXT,
    rating INTEGER,
    review TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    db.commit()

init_db()

from datetime import datetime, timedelta

def auto_complete_bookings():

    db = get_db()

    bookings = db.execute("""
        SELECT id, equipment_id, booking_date, start_time, hours
        FROM bookings
        WHERE status='Paid'
    """).fetchall()

    now = datetime.now()

    for b in bookings:

        # Clean Flutter date
        date_only = b["booking_date"].split(" ")[0]

        start = datetime.strptime(
            date_only + " " + b["start_time"],
            "%Y-%m-%d %I:%M %p"
        )

        end = start + timedelta(hours=b["hours"])

        if now > end:

            db.execute(
                "UPDATE bookings SET status='Completed' WHERE id=?",
                (b["id"],)
            )

            db.execute(
                "UPDATE equipment SET available=1 WHERE id=?",
                (b["equipment_id"],)
            )

    db.commit()

# ---------------- REGISTER ----------------
@app.route("/register", methods=["POST"])
def register():
    data = request.json
    db = get_db()

    if db.execute("SELECT * FROM users WHERE username=?",
                  (data["username"],)).fetchone():
        return jsonify({"msg": "exists"}), 409

    db.execute("INSERT INTO users VALUES (?,?,?)",
               (data["username"], data["password"], data["role"]))
    db.commit()
    return jsonify({"msg": "ok"})

# ---------------- LOGIN ----------------
@app.route("/login", methods=["POST"])
def login():
    data = request.json
    user = get_db().execute(
        "SELECT role FROM users WHERE username=? AND password=?",
        (data["username"], data["password"])
    ).fetchone()

    if user:
        return jsonify({"role": user["role"]})
    return jsonify({"msg": "invalid"}), 401

# ---------------- ADD EQUIPMENT ----------------
@app.route("/equipment", methods=["POST"])
def add_equipment():
    d = request.json
    db = get_db()

    db.execute(
        "INSERT INTO equipment(name, type, location, price, owner, available) VALUES (?, ?, ?, ?, ?, 1)",
        (d["name"], d["type"], d["location"], d["price"], d["owner"])
    )

    db.commit()
    return jsonify({"msg": "added"})

# ---------------- LIST AVAILABLE EQUIPMENT ----------------
@app.route("/equipment", methods=["GET"])
def list_equipment():
    auto_complete_bookings()
    rows = get_db().execute(
        "SELECT * FROM equipment WHERE available=1"
    ).fetchall()

    return jsonify([dict(r) for r in rows])

# ---------------- OWNER EQUIPMENT ----------------
@app.route("/owner_equipment", methods=["GET"])
def owner_equipment():
    owner = request.args.get("owner")

    rows = get_db().execute("""
        SELECT * FROM equipment
        WHERE owner=?
    """, (owner,)).fetchall()

    return jsonify([dict(r) for r in rows])


# ---------------- SEARCH ----------------
@app.route("/search", methods=["GET"])
def search_equipment():
    q = request.args.get("q", "").lower()
    db = get_db()

    rows = db.execute("""
        SELECT 
        e.*, 
        IFNULL(AVG(r.rating), 0) as avg_rating,
        COUNT(r.id) as total_reviews
        FROM equipment e
        LEFT JOIN bookings b ON e.id=b.equipment_id
        LEFT JOIN ratings r ON b.id = r.booking_id
        WHERE e.available=1
        AND (LOWER(e.name) LIKE ? OR LOWER(e.location) LIKE ?)
        GROUP BY e.id
        ORDER BY avg_rating DESC
        """, (f"%{q}%", f"%{q}%")).fetchall()

    return jsonify([dict(r) for r in rows])

# ---------------- BOOK EQUIPMENT ----------------
from datetime import datetime, timedelta

@app.route("/book", methods=["POST"])
def book_equipment():
    data = request.json
    db = get_db()

    if not data.get("owner"):
        return jsonify({"msg":"Owner missing"}),400
    booking_date=data["booking_date"].split(" ")[0]


    # Convert start time and calculate end time
    start_time = datetime.strptime(data["start_time"], "%I:%M %p")
    hours = int(data["hours"])
    end_time = start_time + timedelta(hours=hours)


    # Check existing bookings for same equipment and date
    existing = db.execute("""
        SELECT start_time, hours
        FROM bookings
        WHERE equipment_id=?
        AND booking_date=?
        AND status!='Rejected'
    """, (
        data["equipment_id"],
        data["booking_date"]
    )).fetchall()


    # Check time overlap
    for b in existing:

        existing_start = datetime.strptime(b["start_time"], "%I:%M %p")
        existing_end = existing_start + timedelta(hours=b["hours"])

        if start_time < existing_end and end_time > existing_start:
            return jsonify({
                "msg":"Equipment already booked in this time"
            }),400


    # Insert booking if no conflict
    db.execute("""
        INSERT INTO bookings(
            equipment_id,
            equipment_name,
            farmer,
            owner,
            booking_date,
            start_time,
            hours,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending')
    """, (
        data["equipment_id"],
        data["equipment_name"],
        data["farmer"],
        data["owner"],
        data["booking_date"],
        data["start_time"],
        data["hours"]
    ))

    db.commit()

    return jsonify({"msg": "booking request sent"})

# ---------------- MY BOOKINGS ----------------
@app.route("/mybookings", methods=["GET"])
def my_bookings():
    
    user = request.args.get("user")
    auto_complete_bookings()

    rows = get_db().execute("""
SELECT 
    b.id,
    b.equipment_id,
    b.farmer,
    b.owner,
    b.booking_date,
    b.start_time,
    b.hours,
    b.status,
    e.name AS equipment_name,
    e.price,

    COALESCE((
    SELECT r.rating 
    FROM ratings r 
    WHERE r.booking_id = b.id
), 0) AS rating,

COALESCE((
    SELECT r.review
    FROM ratings r
    WHERE r.booking_id = b.id
), '') AS review
FROM bookings b
JOIN equipment e ON b.equipment_id = e.id
WHERE b.farmer=?
""", (user,)).fetchall()
    print([dict(r) for r in rows])
    print("RATINGS TABLE:", get_db().execute("SELECT * FROM ratings").fetchall())
    print("BOOKINGS:", get_db().execute("SELECT id FROM bookings").fetchall())
    print("RESULT:", [dict(r) for r in rows])

    return jsonify([dict(r) for r in rows])

# ---------------- OWNER BOOKINGS ----------------
@app.route("/owner_bookings", methods=["GET"])
def owner_bookings():
    auto_complete_bookings()
    owner = request.args.get("owner")
    rows = get_db().execute("""
        SELECT * FROM bookings
        WHERE owner=?
    """, (owner,)).fetchall()

    return jsonify([dict(r) for r in rows])

#---------------OWNER APPROVE/ REJECT API ------------
@app.route("/update_booking", methods=["POST"])
def update_booking():
    data = request.json
    db = get_db()

    db.execute("""
        UPDATE bookings
        SET status=?
        WHERE id=?
    """, (data["status"], data["booking_id"]))

    # If approved → mark equipment unavailable
    if data["status"] == "Approved":
        db.execute("""
            UPDATE equipment
            SET available=0
            WHERE id=?
        """, (data["equipment_id"],))

    db.commit()
    return jsonify({"msg": "updated"})

# ---------------- MARK AS PAID ----------------
@app.route("/pay_booking", methods=["POST"])
def pay_booking():
    data = request.json
    db = get_db()

    # Only allow payment if booking is Approved
    booking = db.execute("""
        SELECT * FROM bookings WHERE id=?
    """, (data["booking_id"],)).fetchone()

    if not booking:
        return jsonify({"msg": "Booking not found"}), 404

    if booking["status"] != "Approved":
        return jsonify({"msg": "Booking not approved yet"}), 400

    # Update status to Paid
    db.execute("""
        UPDATE bookings
        SET status='Paid'
        WHERE id=?
    """, (data["booking_id"],))

    db.commit()
    return jsonify({"msg": "Payment successful"})

# ---------------- MAKE PAYMENT ----------------
import uuid
from datetime import datetime

@app.route("/pay", methods=["POST"])
def pay():
    data = request.json
    db = get_db()

    booking = db.execute("""
        SELECT * FROM bookings WHERE id=?
    """, (data["booking_id"],)).fetchone()

    if not booking:
        return jsonify({"msg": "Booking not found"}), 404

    transaction_id = str(uuid.uuid4())[:8]

    db.execute("""
        INSERT INTO payments(
            booking_id,
            farmer,
            owner,
            equipment_name,
            amount,
            transaction_id,
            payment_date
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        booking["id"],
        booking["farmer"],
        booking["owner"],
        booking["equipment_name"],
        data["amount"],
        transaction_id,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    # Update booking status
    db.execute("""
        UPDATE bookings
        SET status='Paid'
        WHERE id=?
    """, (booking["id"],))

    db.commit()

    return jsonify({
        "msg": "Payment successful",
        "transaction_id": transaction_id
    })



# ---------------- FARMER PAYMENTS ----------------
@app.route("/my_payments", methods=["GET"])
def my_payments():
    farmer = request.args.get("farmer")

    rows = get_db().execute("""
        SELECT * FROM payments
        WHERE farmer=?
    """, (farmer,)).fetchall()

    return jsonify([dict(r) for r in rows])


@app.route("/payments", methods=["GET"])
def get_payments():
    farmer = request.args.get("farmer")

    rows = get_db().execute("""
        SELECT * FROM payments
        WHERE farmer=?
    """, (farmer,)).fetchall()

    return jsonify([dict(r) for r in rows])

@app.route("/gps", methods=["POST"])
def receive_gps():

    data = request.json
    print("GPS RECEIVED:",data)
    db = get_db()

    db.execute("""
    INSERT INTO gps_locations(equipment_id, latitude, longitude)
    VALUES(?,?,?)
    """, (
        data["equipment_id"],
        data["lat"],
        data["lon"]
    ))

    db.commit()

    return jsonify({"msg":"location saved"})

@app.route("/track/<int:eid>")
def track(eid):

    row = get_db().execute("""
    SELECT latitude, longitude
    FROM gps_locations
    WHERE equipment_id=?
    ORDER BY time DESC
    LIMIT 1
    """,(eid,)).fetchone()

    if row:
        return jsonify({
            "latitude": row["latitude"],
            "longitude": row["longitude"]
        })

    return jsonify({
        "latitude": None,
        "longitude": None
    })

@app.route("/mobile_gps", methods=["POST"])
def mobile_gps():
    data = request.json
    db = get_db()

    db.execute("""
    INSERT INTO gps_locations(equipment_id, latitude, longitude)
    VALUES(?,?,?)
    """, (
        data["equipment_id"],
        data["lat"],
        data["lon"]
    ))

    db.commit()

    return jsonify({"msg": "mobile gps saved"})

@app.route("/complete_booking", methods=["POST"])
def complete_booking():

    data = request.json
    db = get_db()

    booking = db.execute("""
    SELECT equipment_id FROM bookings WHERE id=?
    """, (data["booking_id"],)).fetchone()

    if not booking:
        return jsonify({"msg":"Booking not found"}),404

    # Update booking status
    db.execute("""
    UPDATE bookings
    SET status='Completed'
    WHERE id=?
    """,(data["booking_id"],))

    # Make equipment available again
    db.execute("""
    UPDATE equipment
    SET available=1
    WHERE id=?
    """,(booking["equipment_id"],))

    db.commit()

    return jsonify({"msg":"Booking completed"})

@app.route("/route/<int:eid>")
def route(eid):

    rows = get_db().execute("""
    SELECT latitude, longitude
    FROM gps_locations
    WHERE equipment_id=?
    ORDER BY time ASC
    """,(eid,)).fetchall()

    return jsonify([
        {"lat": r["latitude"], "lon": r["longitude"]}
        for r in rows
    ])

@app.route("/active_equipment/<farmer>")
def active_equipment(farmer):

    db = get_db()

    row = db.execute("""
    SELECT equipment_id
    FROM bookings
    WHERE farmer=?
    AND status='Paid'
    ORDER BY id DESC
    LIMIT 1
    """,(farmer,)).fetchone()

    if row:
        return jsonify({"equipment_id": row["equipment_id"]})

    return jsonify({"equipment_id": None})

@app.route("/track_active/<farmer>")
def track_active(farmer):

    db = get_db()

    booking = db.execute("""
        SELECT equipment_id
        FROM bookings
        WHERE farmer=? AND status='Paid'
        ORDER BY id DESC
        LIMIT 1
    """,(farmer,)).fetchone()

    if not booking:
        return jsonify({"msg":"No active equipment"})

    eid = booking["equipment_id"]

    location = db.execute("""
        SELECT latitude, longitude
        FROM gps_locations
        WHERE equipment_id=?
        ORDER BY time DESC
        LIMIT 1
    """,(eid,)).fetchone()

    if location:
        return jsonify({
            "latitude": location["latitude"],
            "longitude": location["longitude"]
        })

    return jsonify({
        "latitude": 13.0827,
        "longitude": 80.2707
    })

@app.route("/rate", methods=["POST"])
def rate():
    data = request.get_json()

    booking_id = data.get("booking_id")
    rating = data.get("rating")
    review = data.get("review")

    if not booking_id or not rating:
        return jsonify({"error": "Missing data"}), 400

    db = get_db()

    existing = db.execute(
        "SELECT * FROM ratings WHERE booking_id=?",
        (booking_id,)
    ).fetchone()

    if existing:
        db.execute(
            "UPDATE ratings SET rating=?, review=? WHERE booking_id=?",
            (rating, review, booking_id)
        )
    else:
        db.execute(
            "INSERT INTO ratings (booking_id, rating, review) VALUES (?, ?, ?)",
            (booking_id, rating, review)
        )

    db.commit()

    return jsonify({"message": "Rating saved"})
@app.route("/equipment_with_rating", methods=["GET"])
def equipment_with_rating():

    rows = get_db().execute("""
    SELECT e.*, 
    IFNULL(AVG(r.rating),0) as avg_rating,
    COUNT(r.id) as total_reviews
    FROM equipment e
    LEFT JOIN ratings r ON e.id = r.equipment_id
    GROUP BY e.id
    """).fetchall()

    return jsonify([dict(r) for r in rows])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000,debug=True)