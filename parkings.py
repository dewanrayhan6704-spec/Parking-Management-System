import re
from bson import ObjectId
from flask import Blueprint, request, jsonify, g
from db import get_db
from auth import login_required, admin_required
from utils import (ApiError, STATUSES, serialize, json_body, require_oid, parse_int, parse_float,
                   haversine, validate_parking, utcnow)

parkings_bp = Blueprint("parkings", __name__)
SORTABLE = {"name", "vacant_space", "occupancy_rate", "hourly_rate", "recent_update", "rating_avg"}


def rx(text, exact=False):
    pattern = f"^{re.escape(text)}$" if exact else re.escape(text)
    return {"$regex": pattern, "$options": "i"}


def build_filter(args, available_only=False):
    q = {}
    if available_only:
        q["vacant_space"] = {"$gt": 0}
    if args.get("status"):
        if args["status"] not in STATUSES:
            raise ApiError(f"status must be one of {', '.join(STATUSES)}", 400)
        q["status"] = args["status"]
    if args.get("area"):
        q["location.area"] = rx(args["area"], exact=True)
    if args.get("min_vacant"):
        q.setdefault("vacant_space", {})["$gte"] = parse_int(args, "min_vacant", 0, 0)
    if args.get("max_rate"):
        q["hourly_rate"] = {"$lte": parse_float(args, "max_rate")}
    if args.get("feature"):
        q["features"] = rx(args["feature"], exact=True)
    if args.get("q"):
        term = rx(args["q"])
        q["$or"] = [{"name": term}, {"location.address": term}, {"location.area": term}]
    return q


def paged_list(args, available_only=False, default_sort="name", projection=None):
    page = parse_int(args, "page", 1, 1)
    limit = parse_int(args, "limit", 10, 1, 100)
    sort = args.get("sort", default_sort)
    direction = -1 if sort.startswith("-") else 1
    field = sort.lstrip("-")
    if field not in SORTABLE:
        raise ApiError(f"sort must be one of {', '.join(sorted(SORTABLE))}", 400)
    query = build_filter(args, available_only)
    proj = projection if projection is not None else {"reviews": 0}
    col = get_db().parkings
    total = col.count_documents(query)
    cursor = col.find(query, proj).sort([(field, direction), ("_id", 1)]).skip((page - 1) * limit).limit(limit)
    return {
        "page": page,
        "limit": limit,
        "total": total,
        "pages": (total + limit - 1) // limit,
        "results": [serialize(d) for d in cursor],
    }


def get_parking_or_404(pid):
    doc = get_db().parkings.find_one({"_id": require_oid(pid, "parking id")})
    if not doc:
        raise ApiError("Parking not found", 404)
    return doc


def log_history(p):
    get_db().occupancy_history.insert_one({
        "parking_id": p["_id"],
        "timestamp": utcnow(),
        "vacant_space": p["vacant_space"],
        "occupancy_rate": p["occupancy_rate"],
    })


def create_parking():
    data = json_body()
    clean, errors = validate_parking(data)
    if errors:
        raise ApiError("Validation failed", 400, errors)
    col = get_db().parkings
    if not clean.get("parking_id"):
        n = col.count_documents({}) + 1
        while col.find_one({"parking_id": f"P{n:03d}"}):
            n += 1
        clean["parking_id"] = f"P{n:03d}"
    elif col.find_one({"parking_id": clean["parking_id"]}):
        raise ApiError("parking_id already exists", 409)
    clean.update({"reviews": [], "review_count": 0, "rating_avg": None, "created_at": utcnow()})
    clean["_id"] = col.insert_one(clean).inserted_id
    log_history(clean)
    resp = jsonify(serialize(clean))
    resp.status_code = 201
    resp.headers["Location"] = f"/parkings/{clean['_id']}"
    return resp


def update_parking(pid):
    existing = get_parking_or_404(pid)
    data = json_body()
    clean, errors = validate_parking(data, existing)
    if errors:
        raise ApiError("Validation failed", 400, errors)
    col = get_db().parkings
    if clean.get("parking_id") != existing.get("parking_id") and col.find_one({"parking_id": clean["parking_id"]}):
        raise ApiError("parking_id already exists", 409)
    col.update_one({"_id": existing["_id"]}, {"$set": clean})
    updated = col.find_one({"_id": existing["_id"]})
    if updated["vacant_space"] != existing["vacant_space"] or updated["total_space"] != existing["total_space"]:
        log_history(updated)
    return jsonify(serialize(updated)), 200


def update_occupancy(pid):
    existing = get_parking_or_404(pid)
    data = json_body()
    if "vacant_space" not in data:
        raise ApiError("vacant_space is required", 400)
    return update_parking_with({"vacant_space": data["vacant_space"]}, existing)


def update_parking_with(data, existing):
    clean, errors = validate_parking(data, existing)
    if errors:
        raise ApiError("Validation failed", 400, errors)
    col = get_db().parkings
    col.update_one({"_id": existing["_id"]}, {"$set": clean})
    updated = col.find_one({"_id": existing["_id"]})
    log_history(updated)
    return jsonify(serialize(updated)), 200


def delete_parking(pid):
    existing = get_parking_or_404(pid)
    db = get_db()
    db.parkings.delete_one({"_id": existing["_id"]})
    removed = db.occupancy_history.delete_many({"parking_id": existing["_id"]}).deleted_count
    return jsonify({"message": "Parking deleted", "history_records_removed": removed}), 200


@parkings_bp.get("/parkings")
def list_parkings():
    return jsonify(paged_list(request.args)), 200


@parkings_bp.get("/parkings/available")
def list_available():
    return jsonify(paged_list(request.args, available_only=True, default_sort="-vacant_space")), 200


@parkings_bp.get("/parkings/nearby")
def nearby():
    lat = parse_float(request.args, "lat", required=True)
    lng = parse_float(request.args, "lng", required=True)
    radius = parse_float(request.args, "radius_km", 2.0)
    if not -90 <= lat <= 90 or not -180 <= lng <= 180 or radius <= 0:
        raise ApiError("Invalid coordinates or radius", 400)
    query = {"vacant_space": {"$gt": 0}} if request.args.get("available_only", "true").lower() != "false" else {}
    results = []
    for p in get_db().parkings.find(query, {"reviews": 0}):
        d = haversine(lat, lng, p["location"]["latitude"], p["location"]["longitude"])
        if d <= radius:
            item = serialize(p)
            item["distance_km"] = round(d, 3)
            results.append(item)
    results.sort(key=lambda x: x["distance_km"])
    return jsonify({"origin": {"lat": lat, "lng": lng}, "radius_km": radius, "count": len(results), "results": results}), 200


@parkings_bp.get("/parkings/<pid>")
def get_parking(pid):
    return jsonify(serialize(get_parking_or_404(pid))), 200


@parkings_bp.post("/parkings")
@admin_required
def post_parking():
    return create_parking()


@parkings_bp.put("/parkings/<pid>")
@admin_required
def put_parking(pid):
    return update_parking(pid)


@parkings_bp.delete("/parkings/<pid>")
@admin_required
def del_parking(pid):
    return delete_parking(pid)


def recompute_rating(parking_oid):
    col = get_db().parkings
    doc = col.find_one({"_id": parking_oid})
    reviews = doc.get("reviews", [])
    avg = round(sum(r["rating"] for r in reviews) / len(reviews), 2) if reviews else None
    col.update_one({"_id": parking_oid}, {"$set": {"review_count": len(reviews), "rating_avg": avg}})


def validate_review(data, partial=False):
    errors = []
    clean = {}
    if "rating" in data or not partial:
        r = data.get("rating")
        if isinstance(r, bool) or not isinstance(r, int) or not 1 <= r <= 5:
            errors.append("rating must be an integer between 1 and 5")
        else:
            clean["rating"] = r
    if "comment" in data or not partial:
        c = data.get("comment")
        if not isinstance(c, str) or not c.strip() or len(c) > 500:
            errors.append("comment must be a non-empty string of at most 500 characters")
        else:
            clean["comment"] = c.strip()
    if errors:
        raise ApiError("Validation failed", 400, errors)
    return clean


@parkings_bp.get("/parkings/<pid>/reviews")
def list_reviews(pid):
    p = get_parking_or_404(pid)
    return jsonify({"rating_avg": p.get("rating_avg"), "count": p.get("review_count", 0), "reviews": serialize(p.get("reviews", []))}), 200


@parkings_bp.post("/parkings/<pid>/reviews")
@login_required
def add_review(pid):
    p = get_parking_or_404(pid)
    clean = validate_review(json_body())
    review = {"_id": ObjectId(), "user_id": g.user["_id"], "user_name": g.user["name"], **clean, "created_at": utcnow()}
    get_db().parkings.update_one({"_id": p["_id"]}, {"$push": {"reviews": review}})
    recompute_rating(p["_id"])
    return jsonify(serialize(review)), 201


def get_review_or_404(pid, rid):
    p = get_parking_or_404(pid)
    rid_o = require_oid(rid, "review id")
    review = next((r for r in p.get("reviews", []) if r["_id"] == rid_o), None)
    if not review:
        raise ApiError("Review not found", 404)
    if review["user_id"] != g.user["_id"] and g.user["role"] != "admin":
        raise ApiError("You can only modify your own reviews", 403)
    return p, review


@parkings_bp.put("/parkings/<pid>/reviews/<rid>")
@login_required
def edit_review(pid, rid):
    p, review = get_review_or_404(pid, rid)
    clean = validate_review(json_body(), partial=True)
    if not clean:
        raise ApiError("Nothing to update", 400)
    sets = {f"reviews.$.{k}": v for k, v in clean.items()}
    sets["reviews.$.edited_at"] = utcnow()
    get_db().parkings.update_one({"_id": p["_id"], "reviews._id": review["_id"]}, {"$set": sets})
    recompute_rating(p["_id"])
    updated = next(r for r in get_db().parkings.find_one({"_id": p["_id"]})["reviews"] if r["_id"] == review["_id"])
    return jsonify(serialize(updated)), 200


@parkings_bp.delete("/parkings/<pid>/reviews/<rid>")
@login_required
def remove_review(pid, rid):
    p, review = get_review_or_404(pid, rid)
    get_db().parkings.update_one({"_id": p["_id"]}, {"$pull": {"reviews": {"_id": review["_id"]}}})
    recompute_rating(p["_id"])
    return jsonify({"message": "Review deleted"}), 200
