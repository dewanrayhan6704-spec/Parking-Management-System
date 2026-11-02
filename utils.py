import math
from datetime import datetime, timezone
from bson import ObjectId
from flask import request

STATUSES = ("free", "limited", "full")
FIELDS = ("parking_id", "name", "location", "total_space", "vacant_space", "hourly_rate", "features")


class ApiError(Exception):
    def __init__(self, message, status=400, details=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.details = details


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def oid(value):
    try:
        return ObjectId(value)
    except Exception:
        return None


def require_oid(value, label="id"):
    o = oid(value)
    if o is None:
        raise ApiError(f"Invalid {label}", 400)
    return o


def serialize(obj):
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [serialize(v) for v in obj]
    return obj


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Request body must be a JSON object", 400)
    return data


def parse_int(args, name, default, minimum=None, maximum=None):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ApiError(f"{name} must be an integer", 400)
    if minimum is not None and value < minimum:
        raise ApiError(f"{name} must be >= {minimum}", 400)
    if maximum is not None and value > maximum:
        raise ApiError(f"{name} must be <= {maximum}", 400)
    return value


def parse_float(args, name, default=None, required=False):
    raw = args.get(name)
    if raw is None or raw == "":
        if required:
            raise ApiError(f"{name} is required", 400)
        return default
    try:
        return float(raw)
    except ValueError:
        raise ApiError(f"{name} must be a number", 400)


def haversine(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def compute_status(total, vacant):
    if vacant == 0:
        return "full"
    if (total - vacant) / total * 100 >= 80:
        return "limited"
    return "free"


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_parking(data, existing=None):
    errors = []
    merged = {k: existing[k] for k in FIELDS if existing and k in existing}
    for k in FIELDS:
        if k in data and k != "location":
            merged[k] = data[k]
    if "location" in data:
        if isinstance(data["location"], dict):
            merged["location"] = {**merged.get("location", {}), **data["location"]}
        else:
            errors.append("location must be an object")
    if existing is None:
        for k in ("name", "location", "total_space"):
            if k not in merged:
                errors.append(f"{k} is required")
    if errors:
        return None, errors

    name = merged.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("name must be a non-empty string")
    else:
        merged["name"] = name.strip()

    loc = merged.get("location", {})
    for k in ("address", "area"):
        if not isinstance(loc.get(k), str) or not loc[k].strip():
            errors.append(f"location.{k} must be a non-empty string")
    if not _is_num(loc.get("latitude")) or not -90 <= loc["latitude"] <= 90:
        errors.append("location.latitude must be a number between -90 and 90")
    if not _is_num(loc.get("longitude")) or not -180 <= loc["longitude"] <= 180:
        errors.append("location.longitude must be a number between -180 and 180")

    total = merged.get("total_space")
    if not _is_int(total) or total <= 0:
        errors.append("total_space must be a positive integer")
    vacant = merged.get("vacant_space", total)
    if _is_int(total) and total > 0 and (not _is_int(vacant) or not 0 <= vacant <= total):
        errors.append("vacant_space must be an integer between 0 and total_space")
    rate = merged.setdefault("hourly_rate", 0)
    if not _is_num(rate) or rate < 0:
        errors.append("hourly_rate must be a non-negative number")
    features = merged.setdefault("features", [])
    if not isinstance(features, list) or not all(isinstance(f, str) for f in features):
        errors.append("features must be a list of strings")
    pid = merged.get("parking_id")
    if pid is not None and (not isinstance(pid, str) or not pid.strip()):
        errors.append("parking_id must be a non-empty string")
    if errors:
        return None, errors

    merged["vacant_space"] = vacant
    merged["occupancy_rate"] = round((total - vacant) / total * 100, 1)
    merged["status"] = compute_status(total, vacant)
    merged["recent_update"] = utcnow()
    return merged, []
