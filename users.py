import re
from flask import Blueprint, request, jsonify, g
from db import get_db
from auth import login_required
from utils import ApiError, serialize, json_body, require_oid, parse_int, parse_float, haversine
from parkings import rx, paged_list

users_bp = Blueprint("users", __name__)
COORD_RE = re.compile(r"^\s*(-?\d+(\.\d+)?)\s*,\s*(-?\d+(\.\d+)?)\s*$")


@users_bp.get("/guest/parkings")
def guest_parkings():
    proj = {"name": 1, "location": 1, "vacant_space": 1, "status": 1, "hourly_rate": 1, "parking_id": 1}
    return jsonify(paged_list(request.args, projection=proj)), 200


@users_bp.get("/guest/search")
def guest_search():
    term = (request.args.get("location") or "").strip()
    if not term:
        raise ApiError("location query parameter is required", 400)
    args = {k: v for k, v in request.args.items() if k not in ("location", "q", "area")}
    args["q"] = term
    return jsonify(paged_list(args, available_only=request.args.get("available_only", "").lower() == "true")), 200


@users_bp.post("/user/save_location")
@login_required
def save_location():
    location = json_body().get("location")
    if not isinstance(location, str) or not location.strip():
        raise ApiError("location must be a non-empty string", 400)
    location = location.strip()
    match = get_db().parkings.find_one({"location.area": rx(location, exact=True)}, {"location.area": 1})
    if not match:
        raise ApiError("No parking lots found in that location", 404)
    canonical = match["location"]["area"]
    if canonical in g.user.get("saved_locations", []):
        raise ApiError("Location already saved", 409)
    get_db().users.update_one({"_id": g.user["_id"]}, {"$addToSet": {"saved_locations": canonical}})
    return jsonify({"message": "Location saved", "location": canonical}), 201


@users_bp.get("/user/saved_locations")
@login_required
def saved_locations():
    return jsonify({"saved_locations": g.user.get("saved_locations", [])}), 200


@users_bp.delete("/user/save_location/<location>")
@login_required
def remove_location(location):
    res = get_db().users.update_one(
        {"_id": g.user["_id"]}, {"$pull": {"saved_locations": {"$regex": f"^{re.escape(location)}$", "$options": "i"}}}
    )
    if res.modified_count == 0:
        raise ApiError("Saved location not found", 404)
    return jsonify({"message": "Location removed"}), 200


@users_bp.get("/user/alerts/<uid>")
@login_required
def alerts(uid):
    target = require_oid(uid, "user id")
    if target != g.user["_id"] and g.user["role"] != "admin":
        raise ApiError("You can only view your own alerts", 403)
    user = g.user if target == g.user["_id"] else get_db().users.find_one({"_id": target})
    if not user:
        raise ApiError("User not found", 404)
    threshold = parse_int(request.args, "threshold", 10, 0)
    result = []
    for loc in user.get("saved_locations", []):
        for p in get_db().parkings.find({"location.area": rx(loc, exact=True)}, {"reviews": 0}).sort("vacant_space", -1):
            if p["vacant_space"] == 0:
                level, msg = "full", f"{p['name']} is full"
            elif p["vacant_space"] <= threshold:
                level, msg = "low", f"{p['name']} has only {p['vacant_space']} spaces left"
            else:
                level, msg = "available", f"{p['name']} has {p['vacant_space']} spaces available"
            result.append({"location": loc, "parking_id": p["parking_id"], "parking_name": p["name"],
                           "vacant_space": p["vacant_space"], "level": level, "message": msg})
    order = {"low": 0, "full": 1, "available": 2}
    result.sort(key=lambda a: order[a["level"]])
    return jsonify({"user_id": str(user["_id"]), "threshold": threshold, "count": len(result), "alerts": result}), 200


def resolve_destination(text):
    col = get_db().parkings
    m = COORD_RE.match(text)
    if m:
        lat, lng = float(m.group(1)), float(m.group(3))
        if not -90 <= lat <= 90 or not -180 <= lng <= 180:
            raise ApiError("Destination coordinates out of range", 400)
        return lat, lng, text
    from utils import oid
    o = oid(text)
    doc = col.find_one({"$or": [{"_id": o}, {"parking_id": text}]} if o else {"parking_id": text})
    if doc:
        return doc["location"]["latitude"], doc["location"]["longitude"], doc["name"]
    docs = list(col.find({"$or": [{"location.area": rx(text)}, {"name": rx(text)}, {"location.address": rx(text)}]}))
    if not docs:
        raise ApiError("Destination not found", 404)
    lat = sum(d["location"]["latitude"] for d in docs) / len(docs)
    lng = sum(d["location"]["longitude"] for d in docs) / len(docs)
    return lat, lng, text


@users_bp.get("/user/navigation")
@login_required
def navigation():
    dest = (request.args.get("destination") or "").strip()
    if not dest:
        raise ApiError("destination query parameter is required", 400)
    dlat, dlng, label = resolve_destination(dest)
    olat = parse_float(request.args, "origin_lat")
    olng = parse_float(request.args, "origin_lng")
    if (olat is None) != (olng is None):
        raise ApiError("origin_lat and origin_lng must be provided together", 400)
    options = []
    for p in get_db().parkings.find({"vacant_space": {"$gt": 0}}, {"reviews": 0}):
        d = haversine(dlat, dlng, p["location"]["latitude"], p["location"]["longitude"])
        options.append((d, p))
    options.sort(key=lambda x: x[0])
    suggestions = []
    for d, p in options[:3]:
        lat, lng = p["location"]["latitude"], p["location"]["longitude"]
        url = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}"
        item = {"parking_id": p["parking_id"], "name": p["name"], "address": p["location"]["address"],
                "vacant_space": p["vacant_space"], "distance_to_destination_km": round(d, 3)}
        if olat is not None:
            url += f"&origin={olat},{olng}"
            dist = haversine(olat, olng, lat, lng)
            item["distance_from_origin_km"] = round(dist, 3)
            item["estimated_drive_minutes"] = max(1, round(dist / 30 * 60))
        item["directions_url"] = url
        suggestions.append(item)
    return jsonify({"destination": label, "destination_coordinates": {"lat": dlat, "lng": dlng}, "suggested_parkings": suggestions}), 200
