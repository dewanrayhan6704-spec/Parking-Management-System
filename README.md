# Parking Availability API (COM661 Assignment 1)

Flask + MongoDB REST API for smart-city parking availability.

## Run in VS Code

1. Install Python 3.10+ and MongoDB Community Server (running on `localhost:27017`).
2. Open this folder in VS Code, then in the terminal:

```
python -m venv venv
venv\Scripts\activate          (Windows)   |   source venv/bin/activate   (Mac/Linux)
pip install -r requirements.txt
python seed.py
python app.py
```

API runs at `http://127.0.0.1:5000`.

Optional environment variables: `MONGO_URI` (default `mongodb://localhost:27017`), `DB_NAME` (default `parking_db`), `SECRET_KEY`.

## Login accounts

| Role  | Email             | Password    |
|-------|-------------------|-------------|
| Admin | admin@parking.com | Admin@12345 |
| User  | user@parking.com  | User@12345  |

Guests need no login. Use `Authorization: Bearer <token>` from `POST /auth/login`.

## Postman

Import `postman/Parking_API.postman_collection.json`, run `python seed.py` (resets the data), then run the collection with the Collection Runner (59 requests with tests, run in order). Use the Postman "Publish/View documentation" feature for the documentation printout.

## Automated tests (no MongoDB needed)

```
pip install -r requirements-dev.txt
python -m pytest -v
```

## Submission exports

`db_export/` holds JSON for each collection. To regenerate with mongoexport:

```
mongoexport --db parking_db --collection parkings --jsonArray --out parkings.json
mongoexport --db parking_db --collection users --jsonArray --out users.json
mongoexport --db parking_db --collection occupancy_history --jsonArray --out occupancy_history.json
```

## Collections

- `parkings` – lots with embedded `location`, `features`, and nested `reviews`
- `occupancy_history` – hourly occupancy readings (analytics)
- `users` – accounts (hashed passwords, role, saved_locations)
- `blacklist` – revoked JWTs (logout)

## Endpoints

| Method | Path | Access | Purpose |
|---|---|---|---|
| POST | /auth/register | Public | Register user |
| POST | /auth/login | Public | Login, returns JWT |
| POST | /auth/logout | User | Revoke token |
| GET | /auth/me | User | Current profile |
| GET | /parkings | Public | List (page, limit, sort, area, status, min_vacant, max_rate, feature, q) |
| GET | /parkings/available | Public | Lots with vacant spaces |
| GET | /parkings/nearby?lat&lng&radius_km | Public | Nearby lots by distance |
| GET | /parkings/analytics | User | Occupancy overview by area/status |
| GET | /parkings/{id} | Public | One lot |
| POST | /parkings | Admin | Create |
| PUT | /parkings/{id} | Admin | Update |
| DELETE | /parkings/{id} | Admin | Delete (and history) |
| GET | /parkings/{id}/history?hours | Public | Occupancy readings |
| GET/POST | /parkings/{id}/reviews | Public / User | List / add review |
| PUT/DELETE | /parkings/{id}/reviews/{rid} | Owner/Admin | Edit / delete review |
| GET | /admin/parkings | Admin | All lots (full docs) |
| POST | /admin/parkings | Admin | Create |
| PUT | /admin/parkings/{id} | Admin | Update |
| PATCH | /admin/parkings/{id}/occupancy | Admin | Update live vacancy |
| DELETE | /admin/parkings/{id} | Admin | Delete |
| GET | /admin/users | Admin | List users |
| PUT | /admin/users/{id}/role | Admin | Change role |
| DELETE | /admin/users/{id} | Admin | Delete user |
| GET | /admin/analytics/peak-hours | Admin | Average occupancy by hour |
| GET | /admin/analytics/trend?days | Admin | Daily occupancy trend |
| GET | /guest/parkings | Public | Guest view |
| GET | /guest/search?location= | Public | Search by location |
| POST | /user/save_location | User | Save favourite location |
| GET | /user/saved_locations | User | List saved locations |
| DELETE | /user/save_location/{location} | User | Remove saved location |
| GET | /user/alerts/{user_id}?threshold | User | Availability alerts |
| GET | /user/navigation?destination= | User | Nearest available lots + directions link |

Status codes used: 200, 201, 400, 401, 403, 404, 405, 409, 500.
