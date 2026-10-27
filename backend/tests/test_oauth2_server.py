import pytest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.database import get_db
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.database import Base
from backend.app.models import User
from backend.app.routers.oauth2_server import get_password_hash

SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

@pytest.fixture(scope="module")
def test_user():
    db = TestingSessionLocal()
    user = User(
        email="testuser@example.com",
        name="Test User",
        password_hash=get_password_hash("testpassword"),
        role="user",
        status="ACTIVE",
        points=0,
        unlocked_achievement_ids=[],
        tasks_created=0,
        tasks_completed=0,
        clarity_scores=[],
        claimed_reward_ids=[],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    yield user
    db.delete(user)
    db.commit()
    db.close()

def test_login_success(test_user):
    response = client.post(
        "/oauth2/token",
        data={"username": "testuser@example.com", "password": "testpassword"},
    )
    assert response.status_code == 200
    json_response = response.json()
    assert "access_token" in json_response
    assert json_response["token_type"] == "bearer"

def test_login_wrong_password(test_user):
    response = client.post(
        "/oauth2/token",
        data={"username": "testuser@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password"

def test_login_nonexistent_user():
    response = client.post(
        "/oauth2/token",
        data={"username": "nonexistent@example.com", "password": "testpassword"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password"
