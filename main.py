from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from models import User, FoodLog
from database import SessionLocal
import config
import openai
import anthropic
import os
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv('OPENAI_API_KEY')
anthropic_api_key = os.getenv('ANTHROPIC_API_KEY')

app = FastAPI()
templates = Jinja2Templates(directory="templates")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get('/', response_class=HTMLResponse)
async def read_form(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post('/add_food', response_class=HTMLResponse)
async def add_food(
    request: Request,
    user_name: str = Form(...),
    food_name: str = Form(...),
    portion_size: str = Form(...),
    db: Session = Depends(get_db)
):
    # Check if user exists; if not, create them
    user = db.query(User).filter(User.name == user_name).first()
    if not user:
        user = User(name=user_name)
        db.add(user)
        db.commit()
        db.refresh(user)

    # Get calorie count from preferred AI
    calorie_count = await get_calorie_count(food_name, portion_size)

    # Add food log entry
    food_log = FoodLog(
        user_id=user.id,
        food_name=food_name,
        portion_size=portion_size,
        calorie_count=calorie_count
    )
    db.add(food_log)
    db.commit()
    db.refresh(food_log)

    message = f"Entry added for {user.name}. Estimated calories: {calorie_count}"
    return templates.TemplateResponse("index.html", {"request": request, "message": message})

async def get_calorie_count(food_name, portion_size):
    if config.PREFERRED_AI == 'openai':
        return await get_calories_from_openai(food_name, portion_size)
    elif config.PREFERRED_AI == 'anthropic':
        return await get_calories_from_anthropic(food_name, portion_size)
    else:
        return 0.0  # Default value or handle error

async def get_calories_from_openai(food_name, portion_size):
    prompt = f"Estimate the total calories in {portion_size} of {food_name}. Provide only the numerical value."
    response = openai.Completion.create(
        engine='text-davinci-003',
        prompt=prompt,
        max_tokens=5,
        temperature=0.0,
    )
    calorie_text = response.choices[0].text.strip()
    try:
        calorie_count = float(calorie_text)
    except ValueError:
        calorie_count = 0.0
    return calorie_count

async def get_calories_from_anthropic(food_name, portion_size):
    client = anthropic.Client(api_key=anthropic_api_key)
    prompt = f"Estimate the total calories in {portion_size} of {food_name}. Provide only the numerical value."
    response = await client.completion(
        prompt=anthropic.HUMAN_PROMPT + prompt + anthropic.AI_PROMPT,
        stop_sequences=[anthropic.HUMAN_PROMPT],
        max_tokens_to_sample=5,
        temperature=0.0,
    )
    calorie_text = response['completion'].strip()
    try:
        calorie_count = float(calorie_text)
    except ValueError:
        calorie_count = 0.0
    return calorie_count
