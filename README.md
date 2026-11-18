# Logistics and Delivery Tracking System

A small runnable Flask + SQLite web application demonstrating package tracking, driver management, delivery-status updates, in-app customer notifications, a route-optimization API, and REST endpoints. Designed as a student project prototype.

## Requirements
- Python 3.10+
- pip

## Run locally
1. Extract the ZIP archive.
2. Open a terminal in the extracted `logistics_delivery_tracking_system` folder.
3. Create and activate a virtual environment (recommended):
   - Windows: `python -m venv .venv` then `.venv\\Scripts\\activate`
   - macOS/Linux: `python3 -m venv .venv` then `source .venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Start the server: `python app.py`
6. Visit `http://127.0.0.1:5000`.

The database is created automatically on first run and contains sample drivers and shipments. Sample tracking numbers: `LDT-1001`, `LDT-1002`, `LDT-1003`.

## Main features
- Dashboard with shipment counts and package list.
- Register a package and generate a tracking number.
- Public tracking page with status/event history.
- Add drivers and assign drivers to packages.
- Update delivery status and location; each update records an in-app notification.
- JSON API for packages, drivers, tracking, notifications and health checks.
- Route-ordering endpoint using a nearest-neighbour heuristic and Haversine distance.

## API quick reference
All endpoints run at `http://127.0.0.1:5000`.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/packages` | List packages |
| POST | `/api/packages` | Create package (JSON) |
| GET | `/api/track/LDT-1001` | Package tracking and event history |
| GET | `/api/drivers` | List drivers |
| POST | `/api/drivers` | Create driver (JSON) |
| GET | `/api/notifications` | Latest in-app notification records |
| POST | `/api/packages/<id>/update` | Update package status (JSON) |
| POST | `/api/packages/<id>/assign` | Assign driver (JSON) |
| POST | `/routes/optimize` | Order delivery stops |

### Create a package
```bash
curl -X POST http://127.0.0.1:5000/api/packages \
  -H "Content-Type: application/json" \
  -d '{"customer_name":"Test Customer","customer_phone":"08000000000","pickup":"Kano","destination":"Abuja"}'
```

### Update status
```bash
curl -X POST http://127.0.0.1:5000/api/packages/1/update \
  -H "Content-Type: application/json" \
  -d '{"status":"In Transit","location":"Kano depot","note":"Departed sorting centre"}'
```

### Optimize stop order
```bash
curl -X POST http://127.0.0.1:5000/routes/optimize \
  -H "Content-Type: application/json" \
  -d '{"start":{"lat":12.00,"lon":8.52},"stops":[{"name":"Stop A","lat":12.01,"lon":8.53},{"name":"Stop B","lat":12.04,"lon":8.50}]}'
```
The route endpoint uses straight-line geographic distance and a greedy nearest-neighbour heuristic. It is a demonstration, not a production road-routing engine.

## Architecture
- **Presentation layer:** responsive HTML/CSS dashboard and tracking portal.
- **Application/API layer:** Flask routes, validation, assignment, status workflows and route ordering.
- **Data layer:** SQLite tables for drivers, packages, tracking events and notifications.
- **Distributed systems concept:** web/API service separated conceptually from persistent data; API endpoints allow future mobile clients and third-party integrations.
- **Mobile integration:** responsive web pages and JSON endpoints suitable for a future Android/iOS app.
- **Notifications:** currently stored in the database and displayed via an API; SMS, WhatsApp, email or push delivery requires a provider and credentials.

## Important prototype limitations
- Demo app only: no authentication, authorization, rate limiting, or production deployment hardening.
- Notifications are recorded in-app; no real SMS/email/WhatsApp is sent.
- Route optimization does not use live traffic, road networks, vehicle capacity, or delivery time windows.
- For production, use HTTPS, environment-managed secrets, role-based access, PostgreSQL, database migrations, background jobs/queue, audit logging, backups and automated tests.
