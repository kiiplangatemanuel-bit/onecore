from fastapi.testclient import TestClient
from app.main import app

def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

def test_public_footer_and_home():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Powered by OneCore Technologies Ltd" in response.text
