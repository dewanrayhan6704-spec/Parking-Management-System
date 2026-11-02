from datetime import timedelta
from flask import Blueprint, request, jsonify
from db import get_db
from auth import login_required, admin_required
from utils import serialize, require_oid, parse_int, utcnow
from parkings import get_parking_or_404

analytics_bp = Blueprint("analytics", __name__)


def pct(total, vacant):
    return round((total - vacant) / total * 100, 1) if total else 0.0


@analytics_bp.get("/parkings/analytics")
@login_required
def overview():
    db = get_db()
    totals = next(db.parkings.aggregate([
        {"$group": {"_id": None, "lots": {"$sum": 1}, "total": {"$sum": "$total_space"}, "vacant": {"$sum": "$vacant_space"}}}
    ]), {"lots": 0, "total": 0, "vacant": 0})
    by_area = [
        {"area": r["_id"], "lots": r["lots"], "total_space": r["total"], "vacant_space": r["vacant"],
         "occupancy_rate": pct(r["total"], r["vacant"])}
        for r in db.parkings.aggregate([
            {"$group": {"_id": "$location.area", "lots": {"$sum": 1}, "total": {"$sum": "$total_space"}, "vacant": {"$sum": "$vacant_space"}}},
            {"$sort": {"_id": 1}},
        ])
    ]
    by_area.sort(key=lambda a: -a["occupancy_rate"])
    status_counts = {r["_id"]: r["count"] for r in db.parkings.aggregate([{"$group": {"_id": "$status", "count": {"$sum": 1}}}])}
    brief = {"name": 1, "parking_id": 1, "occupancy_rate": 1, "vacant_space": 1, "location.area": 1}
    busiest = [serialize(p) for p in db.parkings.find({}, brief).sort("occupancy_rate", -1).limit(3)]
    emptiest = [serialize(p) for p in db.parkings.find({}, brief).sort("occupancy_rate", 1).limit(3)]
    return jsonify({
        "total_lots": totals["lots"],
        "total_spaces": totals["total"],
        "vacant_spaces": totals["vacant"],
        "occupied_spaces": totals["total"] - totals["vacant"],
        "overall_occupancy_rate": pct(totals["total"], totals["vacant"]),
        "status_counts": status_counts,
        "by_area": by_area,
        "busiest_lots": busiest,
        "emptiest_lots": emptiest,
    }), 200


@analytics_bp.get("/parkings/<pid>/history")
def history(pid):
    p = get_parking_or_404(pid)
    hours = parse_int(request.args, "hours", 24, 1, 720)
    since = utcnow() - timedelta(hours=hours)
    rows = get_db().occupancy_history.find(
        {"parking_id": p["_id"], "timestamp": {"$gte": since}}, {"parking_id": 0}
    ).sort("timestamp", 1).limit(1000)
    return jsonify({"parking_id": p["parking_id"], "hours": hours, "readings": [serialize(r) for r in rows]}), 200


@analytics_bp.get("/admin/analytics/peak-hours")
@admin_required
def peak_hours():
    pipeline = []
    if request.args.get("parking_id"):
        pipeline.append({"$match": {"parking_id": require_oid(request.args["parking_id"], "parking id")}})
    pipeline += [
        {"$group": {"_id": {"$hour": "$timestamp"}, "avg": {"$avg": "$occupancy_rate"}, "samples": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    hours = [{"hour": r["_id"], "avg_occupancy_rate": round(r["avg"], 1), "samples": r["samples"]} for r in get_db().occupancy_history.aggregate(pipeline)]
    if not hours:
        return jsonify({"hours": [], "peak_hour": None, "quietest_hour": None, "peak_periods": []}), 200
    peak = max(hours, key=lambda h: h["avg_occupancy_rate"])
    quiet = min(hours, key=lambda h: h["avg_occupancy_rate"])
    threshold = parse_int(request.args, "threshold", 80, 1, 100)
    return jsonify({
        "hours": hours,
        "peak_hour": peak,
        "quietest_hour": quiet,
        "peak_periods": [h["hour"] for h in hours if h["avg_occupancy_rate"] >= threshold],
    }), 200


@analytics_bp.get("/admin/analytics/trend")
@admin_required
def trend():
    days = parse_int(request.args, "days", 7, 1, 90)
    match = {"timestamp": {"$gte": utcnow() - timedelta(days=days)}}
    if request.args.get("parking_id"):
        match["parking_id"] = require_oid(request.args["parking_id"], "parking id")
    rows = get_db().occupancy_history.aggregate([
        {"$match": match},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
                    "avg": {"$avg": "$occupancy_rate"}, "max": {"$max": "$occupancy_rate"}, "min": {"$min": "$occupancy_rate"}}},
        {"$sort": {"_id": 1}},
    ])
    return jsonify({"days": days, "trend": [
        {"date": r["_id"], "avg_occupancy_rate": round(r["avg"], 1), "max": r["max"], "min": r["min"]} for r in rows
    ]}), 200
