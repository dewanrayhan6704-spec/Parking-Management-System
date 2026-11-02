from flask import Blueprint, request, jsonify, g
from db import get_db
from auth import admin_required
from utils import ApiError, serialize, json_body, require_oid
import parkings as pk

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.get("/parkings")
@admin_required
def admin_list():
    return jsonify(pk.paged_list(request.args, projection={})), 200


@admin_bp.post("/parkings")
@admin_required
def admin_create():
    return pk.create_parking()


@admin_bp.put("/parkings/<pid>")
@admin_required
def admin_update(pid):
    return pk.update_parking(pid)


@admin_bp.patch("/parkings/<pid>/occupancy")
@admin_required
def admin_occupancy(pid):
    return pk.update_occupancy(pid)


@admin_bp.delete("/parkings/<pid>")
@admin_required
def admin_delete(pid):
    return pk.delete_parking(pid)


@admin_bp.get("/users")
@admin_required
def list_users():
    users = get_db().users.find({}, {"password_hash": 0}).sort("created_at", 1)
    return jsonify([serialize(u) for u in users]), 200


@admin_bp.put("/users/<uid>/role")
@admin_required
def set_role(uid):
    role = json_body().get("role")
    if role not in ("user", "admin"):
        raise ApiError("role must be 'user' or 'admin'", 400)
    oid_ = require_oid(uid, "user id")
    if oid_ == g.user["_id"]:
        raise ApiError("You cannot change your own role", 400)
    res = get_db().users.update_one({"_id": oid_}, {"$set": {"role": role}})
    if res.matched_count == 0:
        raise ApiError("User not found", 404)
    return jsonify({"message": f"Role updated to {role}"}), 200


@admin_bp.delete("/users/<uid>")
@admin_required
def delete_user(uid):
    oid_ = require_oid(uid, "user id")
    if oid_ == g.user["_id"]:
        raise ApiError("You cannot delete your own account", 400)
    res = get_db().users.delete_one({"_id": oid_})
    if res.deleted_count == 0:
        raise ApiError("User not found", 404)
    return jsonify({"message": "User deleted"}), 200
