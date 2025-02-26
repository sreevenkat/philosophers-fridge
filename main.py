from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from models import User, FoodLog, Household
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
async def read_form(request: Request, db: Session = Depends(get_db)):
    # Create test household if it doesn't exist
    test_household = db.query(Household).filter(Household.name == "test").first()
    if not test_household:
        test_household = Household(name="test")
        db.add(test_household)
        db.commit()
        
        # Move existing users without household to test household
        orphan_users = db.query(User).filter(User.household_id == None).all()
        for user in orphan_users:
            user.household_id = test_household.id
        db.commit()
    
    households = db.query(Household).all()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "households": households
    })

@app.get('/manage_household', response_class=HTMLResponse)
async def manage_household(request: Request, db: Session = Depends(get_db)):
    households = db.query(Household).all()
    return templates.TemplateResponse("household_form.html", {
        "request": request,
        "households": households
    })

@app.post('/create_household', response_class=HTMLResponse)
async def create_household(
    request: Request,
    household_name: str = Form(...),
    db: Session = Depends(get_db)
):
    try:
        # Check if household already exists
        existing_household = db.query(Household).filter(Household.name == household_name).first()
        if existing_household:
            households = db.query(Household).all()
            return templates.TemplateResponse("index.html", {
                "request": request,
                "households": households,
                "message": f"Household '{household_name}' already exists!"
            })

        # Create new household
        household = Household(name=household_name)
        db.add(household)
        try:
            db.commit()
            db.refresh(household)
        except Exception as db_error:
            db.rollback()
            print(f"Database error: {str(db_error)}")
            raise HTTPException(status_code=500, detail="Database error occurred")

        # Get updated list of households
        households = db.query(Household).all()
        return templates.TemplateResponse("index.html", {
            "request": request,
            "households": households,
            "message": f"Household '{household_name}' created successfully!"
        })
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        households = db.query(Household).all()
        return templates.TemplateResponse("index.html", {
            "request": request,
            "households": households,
            "message": "An unexpected error occurred while creating the household."
        }, status_code=500)

@app.post('/add_member', response_class=HTMLResponse)
async def add_member(
    request: Request,
    household_id: int = Form(...),
    member_name: str = Form(...),
    db: Session = Depends(get_db)
):
    user = User(name=member_name, household_id=household_id)
    db.add(user)
    db.commit()
    return await manage_household(request, db)

@app.get('/get_household_members/{household_id}')
async def get_household_members(household_id: int, db: Session = Depends(get_db)):
    members = db.query(User).filter(User.household_id == household_id).all()
    return JSONResponse(content=[{"id": m.id, "name": m.name} for m in members])

@app.post('/add_food', response_class=HTMLResponse)
async def add_food(
    request: Request,
    household_id: int = Form(...),
    user_id: int = Form(...),
    food_name: str = Form(...),
    portion_size: str = Form(...),
    db: Session = Depends(get_db)
):
    # Get user
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

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
    # Get all food logs with user and household information
    logs = db.query(FoodLog, User, Household)\
        .select_from(FoodLog)\
        .join(User, FoodLog.user_id == User.id)\
        .join(Household, User.household_id == Household.id)\
        .all()
    
    # Format the data for display
    formatted_logs = []
    for log, user, household in logs:
        formatted_logs.append({
            'household_name': household.name,
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
