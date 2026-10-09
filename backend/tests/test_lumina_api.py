"""Regression coverage for Lumina dashboard, source, tutor, quiz, and evaluation APIs."""
import os
from io import BytesIO

import pytest
import requests


BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")


@pytest.fixture(scope="module")
def client():
    with requests.Session() as session:
        yield session


def test_dashboard_shape(client):
    response = client.get(f"{BASE_URL}/api/dashboard", timeout=20)
    assert response.status_code == 200
    data = response.json()
    assert len(data["topics"]) >= 4
    assert len(data["sources"]) >= 3
    assert data["confidence"] == 72


def test_sources_list(client):
    response = client.get(f"{BASE_URL}/api/sources", timeout=20)
    assert response.status_code == 200
    assert all(source["status"] == "Ready" for source in response.json())


def test_upload_rejects_unsupported_file(client):
    response = client.post(
        f"{BASE_URL}/api/sources/upload",
        files={"file": ("notes.txt", BytesIO(b"not a course source"), "text/plain")},
        timeout=20,
    )
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


def test_quiz_shape_and_submit_feedback(client):
    quiz_response = client.get(f"{BASE_URL}/api/quiz", timeout=20)
    assert quiz_response.status_code == 200
    quiz = quiz_response.json()
    assert quiz["question"]["type"] == "MCQ"
    answer = "To store energy as a proton difference"
    submit_response = client.post(
        f"{BASE_URL}/api/quiz/submit",
        json={"question_id": quiz["question"]["id"], "answer": answer},
        timeout=20,
    )
    assert submit_response.status_code == 200
    result = submit_response.json()
    assert result["correct"] is True
    assert result["citation"]["location"] == "Slide 12"
    assert result["topic"]["mastery"] > 48


def test_quiz_wrong_answer_feedback(client):
    response = client.post(
        f"{BASE_URL}/api/quiz/submit",
        json={"question_id": "q3", "answer": "To split glucose"},
        timeout=20,
    )
    assert response.status_code == 200
    result = response.json()
    assert result["correct"] is False
    assert "proton difference" in result["feedback"]


def test_evaluation_shape(client):
    response = client.get(f"{BASE_URL}/api/evaluation", timeout=20)
    assert response.status_code == 200
    data = response.json()
    assert 0 <= data["faithfulness"] <= 100
    assert len(data["profiles"]) == 3


def test_study_plan_shape(client):
    response = client.get(f"{BASE_URL}/api/study-plan", timeout=20)
    assert response.status_code == 200
    assert response.json()[0]["topic"] == "Electron transport chain"
