import os
from flask import Flask, jsonify
from flask_cors import CORS
from db import init_indexes
from utils import ApiError
from auth import auth_bp
from parkings import parkings_bp
from admin import admin_bp
from users import users_bp
from analytics import analytics_bp


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "parking-api-dev-secret-key-change-me-0123456789")
    app.json.sort_keys = False
    CORS(app)
    init_indexes()
    for bp in (auth_bp, parkings_bp, admin_bp, users_bp, analytics_bp):
        app.register_blueprint(bp)

    @app.get("/")
    def index():
        return jsonify({"service": "Parking Availability API", "version": "1.0", "docs": "See README.md and postman/"}), 200

    @app.errorhandler(ApiError)
    def api_error(e):
        body = {"error": e.message}
        if e.details:
            body["details"] = e.details
        return jsonify(body), e.status

    @app.errorhandler(404)
    def not_found(_):
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(405)
    def not_allowed(_):
        return jsonify({"error": "Method not allowed"}), 405

    @app.errorhandler(500)
    def server_error(_):
        return jsonify({"error": "Internal server error"}), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
