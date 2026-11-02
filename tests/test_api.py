import os
import sys
import pytest

os.environ["USE_MOCK_DB"] = "1"
os.environ["DB_NAME"] = "parking_test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from seed import seed, ADMIN_EMAIL, ADMIN_PASSWORD, USER_EMAIL, USER_PASSWORD


@pytest.fixture()
def client():
    app = create_app()
    seed()
    return app.test_client()


def login(client, email, password):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.get_json()['token']}"}, r.get_json()["user"]


@pytest.fixture()
def admin(client):
    return login(client, ADMIN_EMAIL, ADMIN_PASSWORD)[0]


@pytest.fixture()
def user(client):
    return login(client, USER_EMAIL, USER_PASSWORD)


NEW_LOT = {"name": "Test Lot", "location": {"address": "1 Test St", "area": "Walthamstow", "latitude": 51.58, "longitude": -0.02},
           "total_space": 50, "hourly_rate": 2}


def test_auth_flow(client):
    assert client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": "bad"}).status_code == 401
    r = client.post("/auth/register", json={"name": "A", "email": "a@b.com", "password": "password1"})
    assert r.status_code == 201
    assert client.post("/auth/register", json={"name": "A", "email": "a@b.com", "password": "password1"}).status_code == 409
    assert client.post("/auth/register", json={"name": "A", "email": "bad", "password": "x"}).status_code == 400
    headers, _ = login(client, "a@b.com", "password1")
    assert client.get("/auth/me", headers=headers).status_code == 200
    assert client.post("/auth/logout", headers=headers).status_code == 200
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_public_listing_and_filters(client):
    r = client.get("/parkings?limit=5&sort=-vacant_space")
    body = r.get_json()
    assert r.status_code == 200 and body["total"] == 12 and len(body["results"]) == 5
    assert client.get("/parkings?area=stratford").get_json()["total"] == 3
    assert client.get("/parkings?sort=bogus").status_code == 400
    assert client.get("/parkings?page=x").status_code == 400
    avail = client.get("/parkings/available").get_json()
    assert all(p["vacant_space"] > 0 for p in avail["results"])
    assert client.get("/parkings/nothex").status_code == 400
    assert client.get("/parkings/64b7f0f0f0f0f0f0f0f0f0f0").status_code == 404


def test_nearby_and_guest(client):
    r = client.get("/parkings/nearby?lat=51.583&lng=-0.02&radius_km=1")
    assert r.status_code == 200 and r.get_json()["count"] >= 1
    assert client.get("/parkings/nearby?lat=51.5").status_code == 400
    assert client.get("/guest/parkings").status_code == 200
    assert client.get("/guest/search?location=walthamstow").get_json()["total"] == 3
    assert client.get("/guest/search").status_code == 400


def test_admin_crud(client, admin, user):
    assert client.post("/parkings", json=NEW_LOT).status_code == 401
    assert client.post("/parkings", json=NEW_LOT, headers=user[0]).status_code == 403
    assert client.post("/admin/parkings", json={"name": ""}, headers=admin).status_code == 400
    r = client.post("/admin/parkings", json=NEW_LOT, headers=admin)
    assert r.status_code == 201
    pid = r.get_json()["_id"]
    assert r.get_json()["vacant_space"] == 50 and r.get_json()["status"] == "free"
    assert client.post("/parkings", json={**NEW_LOT, "parking_id": r.get_json()["parking_id"]}, headers=admin).status_code == 409
    r = client.put(f"/admin/parkings/{pid}", json={"vacant_space": 5}, headers=admin)
    assert r.status_code == 200 and r.get_json()["status"] == "limited"
    assert client.put(f"/parkings/{pid}", json={"vacant_space": 500}, headers=admin).status_code == 400
    r = client.patch(f"/admin/parkings/{pid}/occupancy", json={"vacant_space": 0}, headers=admin)
    assert r.get_json()["status"] == "full"
    assert client.get("/admin/parkings", headers=admin).status_code == 200
    assert client.get("/admin/parkings", headers=user[0]).status_code == 403
    assert client.delete(f"/admin/parkings/{pid}", headers=admin).status_code == 200
    assert client.get(f"/parkings/{pid}").status_code == 404


def test_reviews(client, admin, user):
    pid = client.get("/parkings").get_json()["results"][0]["_id"]
    headers = user[0]
    assert client.post(f"/parkings/{pid}/reviews", json={"rating": 5, "comment": "Great"}).status_code == 401
    assert client.post(f"/parkings/{pid}/reviews", json={"rating": 9, "comment": "x"}, headers=headers).status_code == 400
    r = client.post(f"/parkings/{pid}/reviews", json={"rating": 4, "comment": "Good"}, headers=headers)
    assert r.status_code == 201
    rid = r.get_json()["_id"]
    r = client.put(f"/parkings/{pid}/reviews/{rid}", json={"rating": 2}, headers=headers)
    assert r.status_code == 200 and r.get_json()["rating"] == 2
    assert client.get(f"/parkings/{pid}/reviews").get_json()["rating_avg"] == 2
    other = client.post("/auth/register", json={"name": "B", "email": "b@b.com", "password": "password1"})
    other_headers, _ = login(client, "b@b.com", "password1")
    assert client.delete(f"/parkings/{pid}/reviews/{rid}", headers=other_headers).status_code == 403
    assert client.delete(f"/parkings/{pid}/reviews/{rid}", headers=headers).status_code == 200
    assert client.get(f"/parkings/{pid}/reviews").get_json()["count"] == 0


def test_user_features(client, user):
    headers, profile = user
    assert client.post("/user/save_location", json={"location": "Nowhere"}, headers=headers).status_code == 404
    assert client.post("/user/save_location", json={"location": "leyton"}, headers=headers).status_code == 201
    assert client.post("/user/save_location", json={"location": "Leyton"}, headers=headers).status_code == 409
    assert "Leyton" in client.get("/user/saved_locations", headers=headers).get_json()["saved_locations"]
    r = client.get(f"/user/alerts/{profile['_id']}", headers=headers)
    assert r.status_code == 200 and r.get_json()["count"] > 0
    assert client.get("/user/alerts/64b7f0f0f0f0f0f0f0f0f0f0", headers=headers).status_code == 403
    r = client.get("/user/navigation?destination=Stratford&origin_lat=51.58&origin_lng=-0.02", headers=headers)
    assert r.status_code == 200 and "directions_url" in r.get_json()["suggested_parkings"][0]
    assert client.get("/user/navigation", headers=headers).status_code == 400
    assert client.get("/user/navigation?destination=Atlantis", headers=headers).status_code == 404
    assert client.delete("/user/save_location/Leyton", headers=headers).status_code == 200


def test_analytics(client, admin, user):
    assert client.get("/parkings/analytics").status_code == 401
    r = client.get("/parkings/analytics", headers=user[0]).get_json()
    assert r["total_lots"] == 12 and len(r["by_area"]) == 6
    pid = client.get("/parkings").get_json()["results"][0]["_id"]
    assert len(client.get(f"/parkings/{pid}/history?hours=48").get_json()["readings"]) > 10
    r = client.get("/admin/analytics/peak-hours", headers=admin).get_json()
    assert len(r["hours"]) == 24 and r["peak_hour"] is not None
    assert client.get("/admin/analytics/peak-hours", headers=user[0]).status_code == 403
    assert len(client.get("/admin/analytics/trend?days=3", headers=admin).get_json()["trend"]) >= 3


def test_admin_user_management(client, admin):
    users = client.get("/admin/users", headers=admin).get_json()
    assert len(users) == 2 and "password_hash" not in users[0]
    target = next(u for u in users if u["role"] == "user")["_id"]
    assert client.put(f"/admin/users/{target}/role", json={"role": "boss"}, headers=admin).status_code == 400
    assert client.put(f"/admin/users/{target}/role", json={"role": "admin"}, headers=admin).status_code == 200
    assert client.delete(f"/admin/users/{target}", headers=admin).status_code == 200
    assert client.delete(f"/admin/users/{target}", headers=admin).status_code == 404
