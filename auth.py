import re
import uuid
import functools
from datetime import timedelta
import jwt
from bson import ObjectId
from flask import Blueprint, request, jsonify, g, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db
from utils import ApiError, json_body, serialize, utcnow

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def make_token(user):
    payload = {
        "sub": str(user["_id"]),
        "role": user["role"],
        "jti": uuid.uuid4().hex,
        "exp": utcnow() + timedelta(hours=2),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def authenticate():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise ApiError("Authentication token is missing", 401)
    try:
        payload = jwt.decode(header[7:], current_app.config["SECRET_KEY"], algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise ApiError("Token has expired", 401)
    except jwt.InvalidTokenError:
        raise ApiError("Invalid token", 401)
    db = get_db()
    if db.blacklist.find_one({"jti": payload["jti"]}):
        raise ApiError("Token has been revoked", 401)
    user = db.users.find_one({"_id": ObjectId(payload["sub"])})
    if not user:
        raise ApiError("User no longer exists", 401)
    g.user = user
    g.jti = payload["jti"]
    g.exp = payload["exp"]


def login_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        authenticate()
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        authenticate()
        if g.user["role"] != "admin":
            raise ApiError("Administrator access required", 403)
        return fn(*args, **kwargs)
    return wrapper


def public_user(user):
    return serialize({k: user[k] for k in ("_id", "name", "email", "role", "saved_locations", "created_at") if k in user})


@auth_bp.post("/register")
def register():
    data = json_body()
    name = data.get("name")
    email = data.get("email")
    password = data.get("password")
    errors = []
    if not isinstance(name, str) or not name.strip():
        errors.append("name is required")
    if not isinstance(email, str) or not EMAIL_RE.match(email):
        errors.append("a valid email is required")
    if not isinstance(password, str) or len(password) < 8:
        errors.append("password must be at least 8 characters")
    if errors:
        raise ApiError("Validation failed", 400, errors)
    email = email.strip().lower()
    db = get_db()
    if db.users.find_one({"email": email}):
        raise ApiError("Email is already registered", 409)
    user = {
        "name": name.strip(),
        "email": email,
        "password_hash": generate_password_hash(password),
        "role": "user",
        "saved_locations": [],
        "created_at": utcnow(),
    }
    user["_id"] = db.users.insert_one(user).inserted_id
    return jsonify({"message": "Registration successful", "user": public_user(user)}), 201


@auth_bp.post("/login")
def login():
    data = json_body()
    email = str(data.get("email", "")).strip().lower()
    password = data.get("password")
    user = get_db().users.find_one({"email": email})
    if not user or not isinstance(password, str) or not check_password_hash(user["password_hash"], password):
        raise ApiError("Invalid email or password", 401)
    return jsonify({"token": make_token(user), "token_type": "Bearer", "expires_in": 7200, "user": public_user(user)}), 200


@auth_bp.post("/logout")
@login_required
def logout():
    get_db().blacklist.insert_one({"jti": g.jti, "exp": g.exp})
    return jsonify({"message": "Logged out"}), 200


@auth_bp.get("/me")
@login_required
def me():
    return jsonify(public_user(g.user)), 200
