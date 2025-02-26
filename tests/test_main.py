import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_read_form():
    response = client.get("/")
    assert response.status_code == 200
    assert "Philosophers Fridge" in response.text

@pytest.mark.asyncio
async def test_create_household():
    response = client.post(
        "/create_household",
        data={"household_name": "Test Household"}
    )
    assert response.status_code == 200
    assert "Test Household" in response.text

@pytest.mark.asyncio
async def test_add_member():
    # First create a household
    household_response = client.post(
        "/create_household",
        data={"household_name": "Test Household 2"}
    )
    assert household_response.status_code == 200
    
    # Then add a member
    response = client.post(
        "/add_member",
        data={
            "household_id": 1,
            "member_name": "Test Member"
        }
    )
    assert response.status_code == 200
    assert "Test Member" in response.text

@pytest.mark.asyncio
async def test_add_food():
    response = client.post(
        "/add_food",
        data={
            "household_id": 1,
            "user_id": 1,
            "food_name": "apple",
            "portion_size": "1 medium"
        }
    )
    assert response.status_code == 200
    assert "Entry added" in response.text
