import math
import random
from datetime import timedelta
from werkzeug.security import generate_password_hash
from db import get_db, init_indexes
from utils import utcnow, compute_status

ADMIN_EMAIL = "adminrd@parking.com"
ADMIN_PASSWORD = "Adminrd@12345"
USER_EMAIL = "user@parking.com"
USER_PASSWORD = "User@12345"

LOTS = [
    ("Walthamstow Central Car Park", "Hoe Street, London E17 4SD", "Walthamstow", 51.5831, -0.0200, 220, 2.5, ["EV charging", "CCTV"], "commuter"),
    ("Blackhorse Road Station Parking", "Forest Road, London E17 6HE", "Walthamstow", 51.5871, -0.0412, 120, 2.0, ["CCTV"], "commuter"),
    ("Walthamstow Market Car Park", "Orford Road, London E17 9NL", "Walthamstow", 51.5836, -0.0235, 90, 1.8, ["Disabled bays"], "shopping"),
    ("Westfield Stratford Car Park", "Montfichet Road, London E20 1EJ", "Stratford", 51.5435, -0.0089, 600, 3.5, ["EV charging", "CCTV", "Covered"], "shopping"),
    ("Stratford International Parking", "Celebration Avenue, London E20 1DB", "Stratford", 51.5446, -0.0092, 300, 3.0, ["EV charging", "Covered"], "commuter"),
    ("Olympic Park South Car Park", "Carpenters Road, London E20 2ST", "Stratford", 51.5390, -0.0132, 250, 2.8, ["Disabled bays"], "leisure"),
    ("Leyton Midland Road Car Park", "Midland Road, London E10 5RL", "Leyton", 51.5698, -0.0133, 110, 1.6, ["CCTV"], "commuter"),
    ("Leyton Orient Stadium Parking", "Brisbane Road, London E10 5NF", "Leyton", 51.5600, -0.0125, 160, 2.2, ["Disabled bays"], "leisure"),
    ("Hackney Central Car Park", "Amhurst Road, London E8 1LL", "Hackney", 51.5470, -0.0560, 140, 3.2, ["CCTV", "Covered"], "commuter"),
    ("Broadway Market Parking", "Broadway Market, London E8 4PH", "Hackney", 51.5365, -0.0610, 70, 3.4, ["Disabled bays"], "shopping"),
    ("Canary Wharf Jubilee Car Park", "Jubilee Place, London E14 5NY", "Canary Wharf", 51.5054, -0.0235, 450, 4.5, ["EV charging", "CCTV", "Covered"], "commuter"),
    ("Shoreditch High Street Parking", "Bethnal Green Road, London E1 6GY", "Shoreditch", 51.5240, -0.0750, 130, 4.0, ["CCTV", "Covered"], "leisure"),
]


def occupancy_at(kind, hour, weekday, rng, bias):
    def peak(h, c, w):
        return math.exp(-((h - c) / w) ** 2)
    if kind == "commuter":
        base = 25 + 60 * peak(hour, 8.5, 2.2) + 25 * peak(hour, 17.5, 2.5)
        if weekday >= 5:
            base *= 0.55
    elif kind == "shopping":
        base = 15 + 70 * peak(hour, 13.5, 3.5)
        if weekday >= 5:
            base += 15
    else:
        base = 15 + 45 * peak(hour, 15, 4) + 35 * peak(hour, 20, 2.5)
        if weekday >= 5:
            base += 15
    return max(3.0, min(100.0, base + bias + rng.uniform(-6, 6)))


def seed():
    db = get_db()
    for name in ("users", "parkings", "occupancy_history", "blacklist"):
        db[name].drop()
    init_indexes()
    now = utcnow().replace(minute=0, second=0, microsecond=0)
    db.users.insert_many([
        {"name": "System Administrator", "email": ADMIN_EMAIL, "password_hash": generate_password_hash(ADMIN_PASSWORD),
         "role": "admin", "saved_locations": [], "created_at": now},
        {"name": "Demo Driver", "email": USER_EMAIL, "password_hash": generate_password_hash(USER_PASSWORD),
         "role": "user", "saved_locations": ["Walthamstow", "Stratford"], "created_at": now},
    ])
    rng = random.Random(661)
    history = []
    for i, (name, addr, area, lat, lng, total, rate, features, kind) in enumerate(LOTS, start=1):
        bias = rng.uniform(-8, 8)
        readings = []
        for h in range(7 * 24, -1, -1):
            ts = now - timedelta(hours=h)
            occ = occupancy_at(kind, ts.hour, ts.weekday(), rng, bias)
            vacant = total - round(total * occ / 100)
            readings.append((ts, vacant))
        vacant = readings[-1][1]
        if i == 6:
            vacant = 0
        occupancy = round((total - vacant) / total * 100, 1)
        doc = {
            "parking_id": f"P{i:03d}", "name": name,
            "location": {"address": addr, "area": area, "latitude": lat, "longitude": lng},
            "total_space": total, "vacant_space": vacant, "occupancy_rate": occupancy,
            "status": compute_status(total, vacant), "recent_update": now, "hourly_rate": rate,
            "features": features, "reviews": [], "review_count": 0, "rating_avg": None, "created_at": now,
        }
        pid = db.parkings.insert_one(doc).inserted_id
        for ts, v in readings[:-1] + [(readings[-1][0], vacant)]:
            history.append({"parking_id": pid, "timestamp": ts, "vacant_space": v,
                            "occupancy_rate": round((total - v) / total * 100, 1)})
    db.occupancy_history.insert_many(history)
    print(f"Seeded {len(LOTS)} parkings, 2 users, {len(history)} history readings")
    print(f"Admin login: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    print(f"User login:  {USER_EMAIL} / {USER_PASSWORD}")


if __name__ == "__main__":
    seed()
