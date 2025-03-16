from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from models import User, FoodLog, Household, UserRole, HouseholdInvitation, InvitationStatus
from database import SessionLocal
import config
from openai import OpenAI
import anthropic
import os
import datetime
from dotenv import load_dotenv
from starlette.middleware.sessions import SessionMiddleware
from auth import oauth, get_current_user, require_user, require_admin, is_admin, create_or_update_user

load_dotenv()

client = OpenAI()
anthropic_client = anthropic.Client(api_key=os.getenv('ANTHROPIC_API_KEY'))

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.getenv('SECRET_KEY', 'default-secret-key'))

templates = Jinja2Templates(directory="templates")
templates.env.globals["is_admin"] = is_admin

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Authentication routes
@app.get('/login')
async def login(request: Request):
    redirect_uri = request.url_for('auth')
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get('/auth')
async def auth(request: Request, db: Session = Depends(get_db)):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get('userinfo')
    
    if not user_info:
        return RedirectResponse(url='/login')
    
    # Create or update user in database
    user = create_or_update_user(db, user_info)
    
    # Store user email in session
    request.session['user_email'] = user.email
    
    return RedirectResponse(url='/')

@app.get('/logout')
async def logout(request: Request):
    request.session.pop('user_email', None)
    return RedirectResponse(url='/')

@app.get('/', response_class=HTMLResponse)
async def read_form(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    
    if not user:
        return templates.TemplateResponse("login.html", {
            "request": request,
        })
    
    # Get households (admins see all, members see only their own)
    if is_admin(user):
        households = db.query(Household).all()
    else:
        if user.household_id:
            households = [user.household]
        else:
            households = []
    
    # Get pending invitations for this user
    pending_invitations = []
    if user.email:
        pending_invitations = db.query(HouseholdInvitation).join(Household).filter(
            HouseholdInvitation.email == user.email,
            HouseholdInvitation.status == InvitationStatus.PENDING
        ).all()
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user,
        "households": households,
        "pending_invitations": pending_invitations
    })

@app.get('/manage_household', response_class=HTMLResponse)
async def manage_household(
    request: Request, 
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    households = db.query(Household).all()
    users_without_household = db.query(User).filter(User.household_id == None).all()
    
    return templates.TemplateResponse("household_form.html", {
        "request": request,
        "user": admin,
        "households": households,
        "available_users": users_without_household
    })

@app.post('/create_household', response_class=HTMLResponse)
async def create_household(
    request: Request,
    household_name: str = Form(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    try:
        # Check if household already exists
        existing_household = db.query(Household).filter(Household.name == household_name).first()
        if existing_household:
            households = db.query(Household).all()
            return templates.TemplateResponse("index.html", {
                "request": request,
                "user": admin,
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
            "user": admin,
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
            "user": admin,
            "households": households,
            "message": "An unexpected error occurred while creating the household."
        }, status_code=500)

@app.post('/add_member', response_class=HTMLResponse)
async def add_member(
    request: Request,
    household_id: int = Form(...),
    user_id: int = Form(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    # Get the user to add
    user_to_add = db.query(User).filter(User.id == user_id).first()
    if not user_to_add:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update user's household
    user_to_add.household_id = household_id
    db.commit()
    
    return await manage_household(request, db)

@app.post('/add_self_to_household', response_class=HTMLResponse)
async def add_self_to_household(
    request: Request,
    household_id: int = Form(...),
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    try:
        user_id = current_user.id  # Store the user ID for later retrieval
        
        # Check if user is already in a household
        if current_user.household_id:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user": current_user,
                "error_message": "You are already in a household. You must leave your current household before joining a new one."
            })
        
        # Check if household exists
        household = db.query(Household).filter(Household.id == household_id).first()
        if not household:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user": current_user,
                "error_message": "The selected household does not exist."
            })
        print("household", household.__dict__)
        # Update user's household
        current_user.household_id = household_id
        db.commit()
        
        # Get the updated user from the database
        updated_user = db.query(User).filter(User.id == user_id).first()
        print("updated_user", user_id, updated_user.__dict__)
        # Get updated list of households for the redirect
        if is_admin(updated_user):
            households = db.query(Household).all()
        else:
            households = [updated_user.household]
        
        # Get pending invitations for this user
        pending_invitations = []
        if updated_user.email:
            pending_invitations = db.query(HouseholdInvitation).join(Household).filter(
                HouseholdInvitation.email == updated_user.email,
                HouseholdInvitation.status == InvitationStatus.PENDING
            ).all()
        
        return templates.TemplateResponse("index.html", {
            "request": request,
            "user": updated_user,
            "households": households,
            "pending_invitations": pending_invitations,
            "message": f"You have successfully joined the household: {household.name}"
        })
    except Exception as e:
        db.rollback()  # Roll back the transaction in case of error
        return templates.TemplateResponse("error.html", {
            "request": request,
            "user": current_user,
            "error_message": f"An error occurred: {str(e)}"
        })

@app.post('/invite_member', response_class=HTMLResponse)
async def invite_member(
    request: Request,
    household_id: int = Form(...),
    email: str = Form(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    # Check if household exists
    household = db.query(Household).filter(Household.id == household_id).first()
    if not household:
        raise HTTPException(status_code=404, detail="Household not found")
    
    # Prevent self-invitation
    if admin.email.lower() == email.lower():
        return templates.TemplateResponse("household_form.html", {
            "request": request,
            "user": admin,
            "households": db.query(Household).all(),
            "available_users": db.query(User).filter(User.household_id == None).all(),
            "error_message": "You cannot invite yourself. Use 'Join Household' from the home page instead."
        })
    
    # Check if user with this email already exists
    existing_user = db.query(User).filter(User.email == email).first()
    
    # Check if there's already a pending invitation for this email and household
    existing_invitation = db.query(HouseholdInvitation).filter(
        HouseholdInvitation.email == email,
        HouseholdInvitation.household_id == household_id,
        HouseholdInvitation.status == InvitationStatus.PENDING
    ).first()
    
    if existing_invitation:
        # Return the existing invitation
        invite_url = f"{request.base_url}join_household?code={existing_invitation.invite_code}"
        
        # Get all pending invitations for this household
        pending_invitations = db.query(HouseholdInvitation).filter(
            HouseholdInvitation.household_id == household_id,
            HouseholdInvitation.status == InvitationStatus.PENDING
        ).all()
        
        return templates.TemplateResponse("household_form.html", {
            "request": request,
            "user": admin,
            "households": db.query(Household).all(),
            "available_users": db.query(User).filter(User.household_id == None).all(),
            "invite_url": invite_url,
            "message": f"Invitation for {email} already exists",
            "pending_invitations": pending_invitations
        })
    
    if existing_user:
        if existing_user.household_id:
            return templates.TemplateResponse("household_form.html", {
                "request": request,
                "user": admin,
                "households": db.query(Household).all(),
                "available_users": db.query(User).filter(User.household_id == None).all(),
                "error_message": f"User with email {email} is already in a household"
            })
        else:
            # Create invitation for existing user
            invitation = HouseholdInvitation(
                email=email,
                household_id=household_id
            )
            db.add(invitation)
            db.commit()
            db.refresh(invitation)
            
            invite_url = f"{request.base_url}join_household?code={invitation.invite_code}"
            
            # Get all pending invitations for this household
            pending_invitations = db.query(HouseholdInvitation).filter(
                HouseholdInvitation.household_id == household_id,
                HouseholdInvitation.status == InvitationStatus.PENDING
            ).all()
            
            return templates.TemplateResponse("household_form.html", {
                "request": request,
                "user": admin,
                "households": db.query(Household).all(),
                "available_users": db.query(User).filter(User.household_id == None).all(),
                "invite_url": invite_url,
                "message": f"Invitation sent to {email}",
                "pending_invitations": pending_invitations
            })
    else:
        # Create invitation for new user
        invitation = HouseholdInvitation(
            email=email,
            household_id=household_id
        )
        db.add(invitation)
        db.commit()
        db.refresh(invitation)
        
        invite_url = f"{request.base_url}join_household?code={invitation.invite_code}"
        
        # Get all pending invitations for this household
        pending_invitations = db.query(HouseholdInvitation).filter(
            HouseholdInvitation.household_id == household_id,
            HouseholdInvitation.status == InvitationStatus.PENDING
        ).all()
        
        return templates.TemplateResponse("household_form.html", {
            "request": request,
            "user": admin,
            "households": db.query(Household).all(),
            "available_users": db.query(User).filter(User.household_id == None).all(),
            "invite_url": invite_url,
            "message": f"Invitation sent to {email}",
            "pending_invitations": pending_invitations
        })

@app.get('/join_household', response_class=HTMLResponse)
async def join_household(
    request: Request,
    code: str = Query(...),
    db: Session = Depends(get_db)
):
    # Get current user
    user = get_current_user(request, db)
    
    # If not logged in, redirect to login with return URL
    if not user:
        request.session['return_url'] = str(request.url)
        return RedirectResponse(url='/login')
    
    # Find invitation
    invitation = db.query(HouseholdInvitation).filter(
        HouseholdInvitation.invite_code == code,
        HouseholdInvitation.status == InvitationStatus.PENDING
    ).first()
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invalid or expired invitation")
    
    # Check if invitation has expired
    if invitation.expires_at and invitation.expires_at < datetime.datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invitation has expired")
    
    # Check if invitation email matches user email
    if invitation.email.lower() != user.email.lower():
        return templates.TemplateResponse("error.html", {
            "request": request,
            "user": user,
            "error_message": "This invitation was sent to a different email address"
        })
    
    # Add user to household
    user.household_id = invitation.household_id
    
    # Mark invitation as accepted
    invitation.status = InvitationStatus.ACCEPTED
    
    db.commit()
    
    return RedirectResponse(url='/', status_code=303)

@app.post('/accept_invitation', response_class=HTMLResponse)
async def accept_invitation(
    request: Request,
    invitation_id: int = Form(...),
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    try:
        # Find invitation
        invitation = db.query(HouseholdInvitation).filter(
            HouseholdInvitation.id == invitation_id,
            HouseholdInvitation.status == InvitationStatus.PENDING
        ).first()
        
        if not invitation:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user": current_user,
                "error_message": "Invitation not found or already processed."
            })
        
        # Check if invitation email matches user email
        if invitation.email.lower() != current_user.email.lower():
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user": current_user,
                "error_message": "This invitation was not sent to you."
            })
        
        # Check if user is already in a household
        if current_user.household_id:
            # Mark invitation as rejected since user is already in a household
            invitation.status = InvitationStatus.REJECTED
            db.commit()
            
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user": current_user,
                "error_message": "You are already in a household. You must leave your current household before joining a new one."
            })
        
        # Check if household exists
        household = db.query(Household).filter(Household.id == invitation.household_id).first()
        if not household:
            invitation.status = InvitationStatus.REJECTED
            db.commit()
            
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user": current_user,
                "error_message": "The household no longer exists."
            })
        
        # Add user to household
        current_user.household_id = invitation.household_id
        
        # Mark invitation as accepted
        invitation.status = InvitationStatus.ACCEPTED
        
        db.commit()
        
        return RedirectResponse(url='/', status_code=303)
    except Exception as e:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "user": current_user,
            "error_message": f"An error occurred: {str(e)}"
        })

@app.post('/reject_invitation', response_class=HTMLResponse)
async def reject_invitation(
    request: Request,
    invitation_id: int = Form(...),
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    # Find invitation
    invitation = db.query(HouseholdInvitation).filter(
        HouseholdInvitation.id == invitation_id,
        HouseholdInvitation.status == InvitationStatus.PENDING
    ).first()
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    # Check if invitation email matches user email
    if invitation.email.lower() != current_user.email.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invitation was not sent to you"
        )
    
    # Mark invitation as rejected
    invitation.status = InvitationStatus.REJECTED
    
    db.commit()
    
    return RedirectResponse(url='/', status_code=303)

@app.post('/leave_household', response_class=HTMLResponse)
async def leave_household(
    request: Request,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    # Check if user is in a household
    if not current_user.household_id:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "user": current_user,
            "error_message": "You are not currently in a household."
        })
    
    # Check if user is the only admin in the household
    if is_admin(current_user):
        admin_count = db.query(User).filter(
            User.household_id == current_user.household_id,
            User.role == UserRole.ADMIN
        ).count()
        
        if admin_count == 1:
            # Count other members
            member_count = db.query(User).filter(
                User.household_id == current_user.household_id,
                User.id != current_user.id
            ).count()
            
            if member_count > 0:
                return templates.TemplateResponse("error.html", {
                    "request": request,
                    "user": current_user,
                    "error_message": "You cannot leave the household as you are the only admin. Please promote another member to admin first."
                })
    
    # Remove user from household
    current_user.household_id = None
    db.commit()
    
    return RedirectResponse(url='/', status_code=303)

@app.get('/get_household_members/{household_id}')
async def get_household_members(
    household_id: int, 
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    # Check if user is admin or belongs to the requested household
    if not is_admin(current_user) and current_user.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this household's members"
        )
    
    members = db.query(User).filter(User.household_id == household_id).all()
    return JSONResponse(content=[{"id": m.id, "name": m.name, "email": m.email} for m in members])

@app.post('/add_food', response_class=HTMLResponse)
async def add_food(
    request: Request,
    household_id: int = Form(...),
    user_id: int = Form(...),
    food_name: str = Form(...),
    portion_size: str = Form(...),
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    # Get user
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if current user is admin or the user themselves
    if not is_admin(current_user):
        # Non-admin users can only add food for themselves
        if current_user.id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to add food for other users"
            )
    else:
        # Admin users can only add food for users in their household
        if user.household_id != current_user.household_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to add food for users outside your household"
            )

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
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "user": current_user,
        "message": message
    })

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
        model="claude-3-haiku-20240307",
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
async def view_logs(
    request: Request, 
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    # For admins, get all logs; for regular users, get only their household's logs
    if is_admin(current_user):
        logs = db.query(FoodLog, User, Household)\
            .select_from(FoodLog)\
            .join(User, FoodLog.user_id == User.id)\
            .join(Household, User.household_id == Household.id)\
            .all()
    else:
        logs = db.query(FoodLog, User, Household)\
            .select_from(FoodLog)\
            .join(User, FoodLog.user_id == User.id)\
            .join(Household, User.household_id == Household.id)\
            .filter(User.household_id == current_user.household_id)\
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
        {"request": request, "user": current_user, "logs": formatted_logs}
    )
@app.get('/manage_users', response_class=HTMLResponse)
async def manage_users(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    users = db.query(User).all()
    return templates.TemplateResponse(
        "manage_users.html",
        {"request": request, "user": admin, "users": users}
    )

@app.post('/update_user_role', response_class=HTMLResponse)
async def update_user_role(
    request: Request,
    user_id: int = Form(...),
    role: str = Form(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    # Don't allow changing own role
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own role"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update role
    try:
        user.role = UserRole(role)
        db.commit()
        message = f"Updated {user.name}'s role to {role}"
    except ValueError:
        message = f"Invalid role: {role}"
    
    return await manage_users(request, admin, db)
