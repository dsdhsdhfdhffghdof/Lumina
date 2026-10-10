"""Regression coverage for synthetic-session authentication and cookie behavior."""
import os
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient


BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture
def synthetic_session(mongo):
    user_id = "TEST_auth_user"
    token = "TEST_auth_token"
    now = datetime.now(timezone.utc)
    mongo.users.delete_many({"user_id": user_id})
    mongo.user_sessions.delete_many({"session_token": token})
    mongo.users.insert_one({
        "user_id": user_id, "google_id": "google-test-id", "email": "TEST_auth@example.com",
        "name": "Auth Test", "picture": "", "first_sign_in_at": now.isoformat(),
        "last_sign_in_at": now.isoformat(), "learner_profile": {"level": "new"},
        "course_progress": {}, "mastery": {}, "chat_history": [],
    })
    mongo.user_sessions.insert_one({
        "user_id": user_id, "session_token": token,
        "expires_at": (now + timedelta(days=7)).isoformat(),
    })
    yield token
    mongo.users.delete_many({"user_id": user_id})
    mongo.user_sessions.delete_many({"session_token": token})


def test_auth_me_accepts_bearer_and_excludes_mongo_id(synthetic_session):
    response = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {synthetic_session}"}, timeout=20)
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "TEST_auth_user"
    assert data["email"] == "TEST_auth@example.com"
    assert "_id" not in data


def test_auth_me_accepts_cookie(synthetic_session):
    response = requests.get(f"{BASE_URL}/api/auth/me", cookies={"session_token": synthetic_session}, timeout=20)
    assert response.status_code == 200
    assert response.json()["user_id"] == "TEST_auth_user"


def test_expired_session_is_rejected(mongo, synthetic_session):
    mongo.user_sessions.update_one({"session_token": synthetic_session}, {"$set": {"expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}})
    response = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {synthetic_session}"}, timeout=20)
    assert response.status_code == 401


def test_logout_removes_cookie_session(mongo, synthetic_session):
    response = requests.post(f"{BASE_URL}/api/auth/logout", cookies={"session_token": synthetic_session}, timeout=20)
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert mongo.user_sessions.find_one({"session_token": synthetic_session}) is None