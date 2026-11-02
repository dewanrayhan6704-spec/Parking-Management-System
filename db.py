import os
from pymongo import MongoClient, ASCENDING

_client = None


def get_db():
    global _client
    if _client is None:
        if os.environ.get("USE_MOCK_DB") == "1":
            import mongomock
            _client = mongomock.MongoClient()
        else:
            _client = MongoClient(os.environ.get("MONGO_URI", "mongodb://localhost:27017"))
    return _client[os.environ.get("DB_NAME", "parking_db")]


def init_indexes():
    db = get_db()
    db.users.create_index([("email", ASCENDING)], unique=True)
    db.parkings.create_index([("parking_id", ASCENDING)], unique=True)
    db.parkings.create_index([("location.area", ASCENDING)])
    db.parkings.create_index([("vacant_space", ASCENDING)])
    db.occupancy_history.create_index([("parking_id", ASCENDING), ("timestamp", ASCENDING)])
    db.blacklist.create_index([("jti", ASCENDING)], unique=True)
