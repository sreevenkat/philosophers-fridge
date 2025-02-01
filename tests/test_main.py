import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_read_form():
    response = client.get("/")
    assert response.status_code == 200
    assert "Philosophers Fridge" in response.text

@pytest.mark.asyncio
async def test_add_food():
    response = client.post(
        "/add_food",
        data={
            "user_name": "test_user",
            "food_name": "apple",
            "portion_size": "1 medium"
        }
    )
    assert response.status_code == 200
    assert "Entry added for test_user" in response.text
