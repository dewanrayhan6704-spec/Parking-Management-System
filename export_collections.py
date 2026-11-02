import os
import json
from bson import json_util
from db import get_db

OUT = "db_export"


def export():
    os.makedirs(OUT, exist_ok=True)
    db = get_db()
    for name in ("parkings", "users", "occupancy_history"):
        docs = list(db[name].find())
        with open(os.path.join(OUT, f"{name}.json"), "w") as f:
            json.dump(json.loads(json_util.dumps(docs)), f, indent=2)
        print(f"Exported {len(docs)} documents -> {OUT}/{name}.json")


if __name__ == "__main__":
    export()
