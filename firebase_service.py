import base64
import hashlib
import json
import os
from pathlib import Path
from threading import Lock

import firebase_admin
from firebase_admin import credentials, firestore

PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "fdm-database")
USERS_COLLECTION = os.environ.get("FIRESTORE_USERS_COLLECTION", "users")
_firebase_lock = Lock()


def load_environment():
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not os.getenv(key):
            os.environ[key] = value


def initialize_firebase():
    load_environment()
    global PROJECT_ID, USERS_COLLECTION
    PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", PROJECT_ID)
    USERS_COLLECTION = os.environ.get("FIRESTORE_USERS_COLLECTION", USERS_COLLECTION)

    try:
        return firebase_admin.get_app()
    except ValueError:
        pass

    with _firebase_lock:
        try:
            return firebase_admin.get_app()
        except ValueError:
            service_account = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
            if service_account:
                if service_account.startswith("{"):
                    credential = credentials.Certificate(json.loads(service_account))
                else:
                    credential = credentials.Certificate(service_account)
                return firebase_admin.initialize_app(
                    credential, options={"projectId": PROJECT_ID}
                )
            return firebase_admin.initialize_app(options={"projectId": PROJECT_ID})


def get_users_collection():
    initialize_firebase()
    return firestore.client().collection(USERS_COLLECTION)


def auth_email(username):
    load_environment()
    project_id = os.environ.get("FIREBASE_PROJECT_ID", PROJECT_ID)
    digest = base64.urlsafe_b64encode(
        hashlib.sha256(username.encode("utf-8")).digest()
    ).decode("ascii").rstrip("=")
    return f"u{digest}@{project_id}.firebaseapp.com"
