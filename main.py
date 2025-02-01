from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from models import User, FoodLog
from database import SessionLocal
import config
from openai import OpenAI
import anthropic
import os
from dotenv import load_dotenv
load_dotenv()

client = OpenAI()
anthropic_client = anthropic.Client(api_key=os.getenv('ANTHROPIC_API_KEY'))

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
    prompt = f"Estimate the total calories in {portion_size} of {food_name}. Respond with only a number, no words or units."
    print(f"OpenAI Prompt: {prompt}")
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=50,
        temperature=0.0
    )
    calorie_text = response.choices[0].message.content.strip()
    print(f"OpenAI Response: {calorie_text}")
    try:
        # Remove any non-numeric characters except decimal points
        cleaned_text = ''.join(c for c in calorie_text if c.isdigit() or c == '.')
        calorie_count = float(cleaned_text)
        print(f"Parsed calories: {calorie_count}")
    except ValueError:
        print(f"Failed to parse response as number: {calorie_text}")
        calorie_count = 0.0
    return calorie_count

async def get_calories_from_anthropic(food_name, portion_size):
    prompt = f"Estimate the total calories in {portion_size} of {food_name}. Respond with only a number, no words or units."
    print(f"Anthropic Prompt: {prompt}")
    response = await anthropic_client.messages.create(
        model="claude-2",
        max_tokens=50,
        temperature=0,
        messages=[{"role": "user", "content": prompt}]
    )
    calorie_text = response.content[0].text.strip()
    print(f"Anthropic Response: {calorie_text}")
    try:
        # Remove any non-numeric characters except decimal points
        cleaned_text = ''.join(c for c in calorie_text if c.isdigit() or c == '.')
        calorie_count = float(cleaned_text)
        print(f"Parsed calories: {calorie_count}")
    except ValueError:
        print(f"Failed to parse response as number: {calorie_text}")
        calorie_count = 0.0
    return calorie_count

@app.get('/view_logs', response_class=HTMLResponse)
async def view_logs(request: Request, db: Session = Depends(get_db)):
    # Get all food logs with user information
    logs = db.query(FoodLog, User).join(User).all()
    
    # Format the data for display
    formatted_logs = []
    for log, user in logs:
        formatted_logs.append({
            'user_name': user.name,
            'food_name': log.food_name,
            'portion_size': log.portion_size,
            'calorie_count': log.calorie_count,
            'timestamp': log.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        })
    
    return templates.TemplateResponse(
        "view_logs.html", 
        {"request": request, "logs": formatted_logs}
    )
