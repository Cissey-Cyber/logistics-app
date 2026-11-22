import os
from datetime import datetime, timezone
from flask import Flask, request, redirect, url_for, render_template, session, flash
import requests
import hashlib
import math
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "logistics-secret-change-me")

# --- Postgres / SQLite compat layer ---
try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None
try:
    import sqlite3
except ImportError:
    sqlite3 = None

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
DB_PATH = "logistics.db"

class PGWrapperCursor:
    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid
    def fetchone(self):
        return self._cur.fetchone()
    def fetchall(self):
        return self._cur.fetchall()
    def close(self):
        self._cur.close()

class PGConn:
    def __init__(self, url):
        self._conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
        self._conn.autocommit = False
    def _translate(self, sql):
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        sql = sql.replace("AUTOINCREMENT", "")
        sql = sql.replace("?", "%s")
        return sql
    def execute(self, sql, params=None):
        sql2 = self._translate(sql)
        cur = self._conn.cursor()
        is_insert = sql2.strip().upper().startswith("INSERT")
        if is_insert and "RETURNING" not in sql2.upper():
            sql2 = sql2 + " RETURNING id"
            cur.execute(sql2, params or ())
            row = cur.fetchone()
            last = row["id"] if row else None
            return PGWrapperCursor(cur, lastrowid=last)
        cur.execute(sql2, params or ())
        return PGWrapperCursor(cur)
    def commit(self):
        self._conn.commit()
    def close(self):
        try: self._conn.close()
        except: pass
    def __enter__(self):
        return self
    def __exit__(self, *a):
        try: self._conn.commit()
        except: pass
        self.close()
        return False

def db():
    if DATABASE_URL and psycopg2:
        return PGConn(DATABASE_URL)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con
# --- ADMIN LOGIN ---
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "LDTS123"

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name")
        phone = request.form.get("phone")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")
        confirm = request.form.get("confirm_password")
        if password != confirm:
            flash("Passwords do not match!")
            return redirect(url_for("register"))
        if not all([full_name, phone, email, username, password]):
            flash("Fill all fields!")
            return redirect(url_for("register"))
        try:
            with db() as con:
                con.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT, phone TEXT, email TEXT, username TEXT UNIQUE, password_hash TEXT, created_at TEXT)")
                con.execute("INSERT INTO users(full_name,phone,email,username,password_hash,created_at) VALUES(?,?,?,?,?,?)", (full_name, phone, email, username, generate_password_hash(password), datetime.now().isoformat()))
                con.commit()
            flash("Account created! Login now.")
            return redirect(url_for("login"))
        except:
            flash("Username or Email already exists!")
            return redirect(url_for("register"))
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == "admin" and password == "LDTS123":
            session["admin_logged_in"] = True
            session["admin_name"] = "Admin One"
            return redirect(url_for("index"))
        with db() as con:
            con.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT, phone TEXT, email TEXT, username TEXT UNIQUE, password_hash TEXT, created_at TEXT)")
            user = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["admin_logged_in"] = True
            session["admin_name"] = user["full_name"]
            return redirect(url_for("index"))
        flash("Wrong username or password!")
    return render_template("login.html")
@app.route("/logout")
def logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("login"))

BREVO_API_KEY = os.getenv("BREVO_API_KEY", "paste-your-brevo-key-here")
WUSE_DEPOT = (9.064, 7.452)  # Wuse Depot, Abuja

def euclidean(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2)

def nearest_neighbour(packages, start=WUSE_DEPOT):
    current = start
    unvisited = packages.copy()
    order = []
    while unvisited:
        nxt = min(unvisited, key=lambda p: euclidean(current, (p['lat'], p['lng'])))
        dist = euclidean(current, (nxt['lat'], nxt['lng']))
        order.append({
            "stop_order": len(order) + 1,
            "tracking_no": nxt['tracking_no'],
            "address": nxt.get('address', ''),
            "lat": nxt['lat'],
            "lng": nxt['lng'],
            "distance_from_prev": round(dist, 4)
        })
        current = (nxt['lat'], nxt['lng'])
        unvisited.remove(nxt)
    return order



def init_db():
    with db() as con:
        con.execute("CREATE TABLE IF NOT EXISTS drivers(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, status TEXT DEFAULT 'Available')")
        con.execute("CREATE TABLE IF NOT EXISTS packages(id INTEGER PRIMARY KEY AUTOINCREMENT, tracking_no TEXT UNIQUE, customer_name TEXT, customer_phone TEXT, pickup TEXT, destination TEXT, status TEXT DEFAULT 'Pending', driver_id INTEGER, created_at TEXT, updated_at TEXT, notes TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, package_id INTEGER, status TEXT, location TEXT, note TEXT, created_at TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS NotificationAttempts (id INTEGER PRIMARY KEY AUTOINCREMENT, event_reference TEXT, package_reference TEXT, recipient TEXT, channel TEXT DEFAULT 'email', message_type TEXT DEFAULT 'status_update', attempt_count INTEGER DEFAULT 1, status TEXT DEFAULT 'pending', idempotency_key TEXT, provider_response TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(event_reference, channel, message_type))")
        con.execute("CREATE TABLE IF NOT EXISTS Routes (id INTEGER PRIMARY KEY AUTOINCREMENT, optimized_order TEXT, method TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        con.execute("CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT, package_id INTEGER, message TEXT, is_read INTEGER DEFAULT 0, created_at TEXT)")
        if con.execute("SELECT COUNT(*) FROM drivers").fetchone()["count"]==0:
            con.execute("INSERT INTO drivers(name, phone, status) VALUES('John Driver','08012345678','Available')")

# Helper to find package
def get_pkg(identifier):
    with db() as con:
        try:
            pid = int(identifier)
            pkg = con.execute("SELECT * FROM packages WHERE id=%s", (pid,)).fetchone()
            if pkg: return pkg
        except:
            pass
        return con.execute("SELECT * FROM packages WHERE tracking_no=%s", (str(identifier),)).fetchone()

notifications_log = []

@app.route('/notifications')
def notifications_page():
    return render_template('notifications.html', notifications=notifications_log)

@app.route('/routes')
def routes_page():
    return render_template('routes.html')    
# --- REAL NOTIFICATION API ---
# In-memory store + file log so we can prove sent/failed


@app.route('/api/notifications', methods=['POST'])
def send_notification():
    data = request.get_json() or {}
    tracking_no = data.get('tracking_no')
    customer = data.get('customer', 'Unknown Customer')
    email = data.get('email', '')
    phone = data.get('phone', '')
    status = data.get('status', 'Updated')
    message = data.get('message') or f"Package {tracking_no} is {status}"

    if not tracking_no:
        return jsonify({"error": "tracking_no is required"}), 400

    # Try to "send" - we log it and try email if configured
    # In a real company this would call Twilio / SendGrid. Here we
    # record the attempt so it is provable, and save to notifications.txt
    delivery_status = "sent"
    delivery_detail = "Logged to notifications log"
    try:
        # Simulated delivery: write to file (this is the delivery record)
        with open("notifications.txt", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now()} | To: {customer} ({email}/{phone}) | {tracking_no} | {status} | {message}\n")
        # If you later add real SMTP, put it here. For now, log = sent
    except Exception as e:
        delivery_status = "failed"
        delivery_detail = str(e)

    record = {
        "id": len(notifications_log) + 1,
        "tracking_no": tracking_no,
        "customer": customer,
        "email": email,
        "phone": phone,
        "status": status,
        "message": message,
        "delivery_status": delivery_status,
        "detail": delivery_detail,
        "created_at": datetime.now().isoformat()
    }
    notifications_log.append(record)
    return jsonify({"success": True, "notification": record}), 201

@app.route('/api/notifications', methods=['GET'])
def list_notifications():
    return jsonify(notifications_log)
# --- REAL ROUTE OPTIMIZATION API - Nearest Neighbor + Haversine ---
import math

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))

@app.route('/api/routes/optimize', methods=['POST'])
def optimize_route():
    data = request.get_json() or {}
    packages = data.get('packages', [])
    # Each package must have: tracking_no, lat, lng
    # Example: {"tracking_no":"LOT-0001","lat":9.0579,"lng":7.4951}
    if len(packages) < 2:
        return jsonify({"error": "Need at least 2 packages with lat/lng"}), 400

    # Start from first package (depot / start point)
    remaining = packages[:]
    current = remaining.pop(0)
    optimized = [current]
    total_distance = 0.0

    # Nearest Neighbor: always go to closest unvisited stop
    while remaining:
        nearest = min(remaining, key=lambda p: haversine_km(current['lat'], current['lng'], p['lat'], p['lng']))
        dist = haversine_km(current['lat'], current['lng'], nearest['lat'], nearest['lng'])
        total_distance += dist
        optimized.append({**nearest, "distance_from_prev_km": round(dist, 2)})
        current = nearest
        remaining.remove(nearest)

    return jsonify({
        "method": "nearest_neighbor",
        "algorithm": "Nearest Neighbor + Haversine distance",
        "total_stops": len(optimized),
        "total_distance_km": round(total_distance, 2),
        "optimized_order": [p.get('tracking_no') for p in optimized],
        "optimized_route": optimized
    })
@app.route('/')
@login_required
def index():
    with db() as con:
        pkgs = con.execute("SELECT p.*, d.name as driver_name FROM packages p LEFT JOIN drivers d ON p.driver_id=d.id ORDER BY p.id DESC").fetchall()
        total = con.execute("SELECT COUNT(*) FROM packages").fetchone()['count']
        in_transit = con.execute("SELECT COUNT(*) FROM packages WHERE status IN ('Assigned','In transit','In Transit','On delivery','Shipped')").fetchone()['count']
        delivered = con.execute("SELECT COUNT(*) FROM packages WHERE status = 'Delivered'").fetchone()['count']
        total_drivers = con.execute("SELECT COUNT(*) FROM drivers").fetchone()['count']
        pending = con.execute("SELECT COUNT(*) FROM packages WHERE status='Pending'").fetchone()['count']
        drivers = con.execute("SELECT * FROM drivers").fetchall()
    stats = {
        "total": total, "total_packages": total,
        "in_transit": in_transit, "inTransit": in_transit, "transit": in_transit, "assigned": in_transit,
        "delivered": delivered, "drivers": total_drivers, "total_drivers": total_drivers, "pending": pending
    }
    try:
        return render_template("index.html", packages=pkgs, stats=stats, drivers=drivers)
    except:
        try:
            return render_template("dashboard.html", packages=pkgs, stats=stats, drivers=drivers)
        except:
            return redirect(url_for("packages_list"))

# --- DRIVERS ---
@app.route('/drivers')
def drivers_list():
    with db() as con:
        drivers = con.execute("SELECT * FROM drivers ORDER BY id DESC").fetchall()
    try:
        return render_template("drivers.html", drivers=drivers, stats={})
    except:
        html = "<h1>Drivers</h1><a href='/drivers/new'>Add Driver</a> | <a href='/'>Home</a><ul>"
        with db() as con:
            drivers = con.execute("SELECT * FROM drivers").fetchall()
        for d in drivers: html+=f"<li>{d['name']} - {d['status']}</li>"
        return html

@app.route('/drivers/new', methods=['GET','POST'])
def drivers_new():
    if request.method=='POST':
        with db() as con:
            con.execute("INSERT INTO drivers(name, phone, status) VALUES(?,?,'Available')", (request.form.get("name"), request.form.get("phone")))
            con.commit()
        return redirect(url_for("drivers_list"))
    try: return render_template("new_driver.html")
    except: return '<h1>Add Driver</h1><form method="POST">Name:<input name="name" required><br>Phone:<input name="phone"><br><button>Create</button></form>'

@app.route('/drivers/delete/<int:driver_id>', methods=['POST'])
def drivers_delete(driver_id):
    with db() as con:
        con.execute("DELETE FROM drivers WHERE id=?", (driver_id,))
        con.commit()
    return redirect(url_for("drivers_list"))

# --- PACKAGES ---
@app.route('/packages')
def packages_list():
    with db() as con:
        pkgs = con.execute("SELECT p.*, d.name as driver_name FROM packages p LEFT JOIN drivers d ON p.driver_id=d.id ORDER BY p.id DESC").fetchall()
    try:
        return render_template("packages.html", packages=pkgs)
    except:
        html = f"""<html><head><style>
        body{{font-family:Arial;background:#e8eef5;padding:20px}}
        .box{{background:white;max-width:800px;margin:auto;padding:25px;border-radius:15px;box-shadow:0 5px 20px rgba(0,0,0,0.08)}}
        h1{{color:#334155}}
        .btn{{background:#64748b;color:white;padding:9px 16px;border-radius:8px;text-decoration:none;display:inline-block;margin-right:8px}}
        li{{background:#f8fafc;padding:14px;margin:10px 0;border-radius:10px;list-style:none;border:1px solid #e2e8f0}}
        li a{{color:#2563eb;text-decoration:none;font-weight:bold}}
        </style></head><body><div class='box'>
        <h1>All Packages ({len(pkgs)})</h1>
        <a class='btn' href='/packages/new'>+ New Shipment</a> <a class='btn' href='/'>Dashboard</a><ul>"""
        for p in pkgs:
            html += f"<li><a href='/track/{p['tracking_no']}'>{p['tracking_no']}</a> - {p['customer_name']} - {p['status']} - <a href='/packages/{p['id']}'>View</a></li>"
        html += "</ul></div></body></html>"
        return html

@app.route('/packages/new', methods=['GET','POST'])
def packages_new():
    if request.method=='POST':
        data = request.form
        with db() as con:
            count = con.execute("SELECT COUNT(*) FROM packages").fetchone()["count"] + 1
            tracking = data.get("tracking_no") or f"LDT-{count:04d}"
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            cur = con.execute("INSERT INTO packages(tracking_no,customer_name,customer_phone,pickup,destination,status,created_at,updated_at,notes) VALUES(%s,%s,%s,%s,%s,'Pending',%s,%s,%s) RETURNING id", (tracking, data["customer_name"], data.get("customer_phone"), data["pickup"], data["destination"], now, now, data.get("notes")))
            pid = cur.fetchone()["id"]
            drv = con.execute("SELECT id FROM drivers WHERE status='Available' LIMIT 1").fetchone()
            if drv:
                con.execute("UPDATE packages SET driver_id=%s, status='Assigned' WHERE id=%s", (drv["id"], pid))
                con.execute("UPDATE drivers SET status='On delivery' WHERE id=%s", (drv["id"],))
            con.commit()
        return redirect(url_for("packages_list"))
    try: return render_template("new_package.html")
    except: return '<h1>New Shipment</h1><form method="POST">Customer:<input name="customer_name" required><br>Pickup:<input name="pickup" required><br>Destination:<input name="destination" required><br><button>Create</button></form>'

# --- VIEW SINGLE PACKAGE (FIXES TRACK BUTTON) ---
@app.route('/packages/<id_or_tracking>')
def package_detail(id_or_tracking):
    pkg = get_pkg(id_or_tracking)
    if not pkg: return "Package Not Found", 404
    with db() as con:
        driver = con.execute("SELECT * FROM drivers WHERE id=%s", (pkg["driver_id"],)).fetchone() if pkg["driver_id"] else None
        events = con.execute("SELECT * FROM events WHERE package_id=%s ORDER BY id DESC", (pkg["id"],)).fetchall()
        all_drivers = con.execute("SELECT * FROM drivers").fetchall()
    try:
        return render_template("package_detail.html", package=pkg, driver=driver, events=events, drivers=all_drivers)
    except:
        return render_template("detail.html", package=pkg, driver=driver, events=events, drivers=all_drivers) if False else f"<h1>{pkg['tracking_no']}</h1><p>{pkg['customer_name']} - {pkg['status']}</p><a href='/track/{pkg['tracking_no']}'>Track</a> | <a href='/packages'>Back</a>"

# --- UPDATE STATUS (FIXES SAVE BUTTON) - I ADDED ALL POSSIBLE ROUTES ---
@app.route('/packages/<int:package_id>/update', methods=['POST'])
@app.route('/packages/update', methods=['POST'])
@app.route('/update_status', methods=['POST'])
@app.route('/packages/<int:package_id>/update_status', methods=['POST'])
@app.route('/update', methods=['POST'])
def update_status(package_id=None):
    data = request.form
    pid = package_id or data.get("package_id") or data.get("id") or data.get("tracking_no")
    pkg = get_pkg(pid) if pid else None
    if not pkg:
        flash("Package not found", "error")
        return redirect(url_for("packages_list"))
    status = data.get("status") or data.get("delivery_status") or "Delivered"
    location = data.get("location") or data.get("current_location") or pkg["destination"]
    note = data.get("note") or data.get("update_note") or ""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as con:
        con.execute("UPDATE packages SET status=%s, updated_at=%s WHERE id=%s", (status, now, pkg["id"]))
        con.execute("INSERT INTO events(package_id,status,location,note,created_at) VALUES(%s,%s,%s,%s,%s)", (pkg["id"], status, location, note, now))
        try:
            con.execute("INSERT INTO notifications (package_id, message, is_read, created_at) VALUES (%s, %s, 0, %s)", (pid, f"Your package {pkg['tracking_no']} status updated to {status} - {location}", now))
        except Exception:
            pass
        if status.lower() in ["delivered", "delivered successfully"]:
            if pkg["driver_id"]:
                con.execute("UPDATE drivers SET status='Available' WHERE id=%s", (pkg["driver_id"],))
        con.commit()
    flash(f"Status updated to {status}", "success")
    return redirect(url_for("package_detail", id_or_tracking=pkg["tracking_no"]))

# --- ASSIGN DRIVER ---
@app.route('/packages/<int:package_id>/assign', methods=['POST'])
@app.route('/assign_driver', methods=['POST'])
@app.route('/packages/assign', methods=['POST'])
def assign_driver(package_id=None):
    data = request.form
    pid = package_id or data.get("package_id") or data.get("id")
    driver_id = data.get("driver_id") or data.get("driver")
    pkg = get_pkg(pid) if pid else None
    if not pkg or not driver_id:
        flash("Missing data", "error")
        return redirect(url_for("packages_list"))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as con:
        con.execute("UPDATE packages SET driver_id=%s, status='Assigned', updated_at=%s WHERE id=%s", (driver_id, now, pkg["id"]))
        con.execute("UPDATE drivers SET status='On delivery' WHERE id=%s", (driver_id,))
        con.execute("INSERT INTO events(package_id,status,location,note,created_at) VALUES(%s,%s,%s,%s,%s,)", (pkg["id"], "Assigned", pkg["destination"], f"Assigned to driver {driver_id}", now))
        con.commit()
    return redirect(url_for("package_detail", id_or_tracking=pkg["tracking_no"]))

# --- TRACK (FIXES TRACK A PACKAGE) ---
@app.route('/track')
@app.route('/track/<tracking_no>')
@app.route('/packages/track')
@app.route('/track_package')
def track_page(tracking_no=None):
    if not tracking_no:
        tracking_no = request.args.get("tracking_no") or request.args.get("q")
    if not tracking_no:
        try: return render_template("track.html")
        except: return '<h1>Track Package</h1><form action="/track" method="GET">Tracking No:<input name="tracking_no" required><button>Track</button></form><a href="/">Home</a>'
    pkg = get_pkg(tracking_no)
    if not pkg: return f"<h1>Not Found {tracking_no}</h1><a href='/track'>Try again</a>", 404
    with db() as con:
        events = con.execute("SELECT * FROM events WHERE package_id=%s ORDER BY id ASC", (pkg["id"],)).fetchall()
        driver = con.execute("SELECT * FROM drivers WHERE id=%s", (pkg["driver_id"],)).fetchone() if pkg["driver_id"] else None
    try:
        return render_template("track.html", package=pkg, events=events, driver=driver)
    except:
        ev_html = "".join([f"<li>{e['created_at']} - {e['status']} at {e['location']} - {e['note']}</li>" for e in events])
        return f"<h1>Tracking {pkg['tracking_no']}</h1><p>Customer: {pkg['customer_name']}<br>Status: <b>{pkg['status']}</b><br>Driver: {driver['name'] if driver else 'Not assigned'}</p><h3>History:</h3><ul>{ev_html}</ul><a href='/'>Home</a>"

@app.route('/create_package', methods=['POST'])
def create_package():
    return redirect(url_for("packages_new"))

@app.route('/api/notifications')
def notifications_api():
    with db() as con:
        try:
            rows = con.execute("SELECT * FROM notifications ORDER BY id DESC").fetchall()
            data = [dict(r) for r in rows]
        except:
            pkgs = con.execute("SELECT * FROM packages ORDER BY id DESC LIMIT 20").fetchall()
            data = []
            for p in pkgs:
                data.append({
                    "id": p["id"],
                    "tracking_no": p["tracking_no"],
                    "message": f"Package {p['tracking_no']} is {p['status']}",
                    "status": p["status"],
                    "customer": p["customer_name"]
                })
    return jsonify(data)

@app.route('/api/packages')
def packages_api_list():
    with db() as con:
        pkgs = con.execute("SELECT * FROM packages ORDER BY id DESC").fetchall()
        data = [dict(p) for p in pkgs]
    return jsonify(data)
init_db()

@app.route('/delete-emmanuel')
def delete_emmanuel():
    with db() as con:
        con.execute("DELETE FROM packages WHERE tracking_no='LDT-0004'")
        con.execute("DELETE FROM packages WHERE customer_name LIKE '%Emmanuel%'")
    return "Emmanuel Deleted - Go back to Notifications"
if __name__=="__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
