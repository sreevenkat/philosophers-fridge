from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from models import User, FoodLog, Household, UserRole, HouseholdInvitation, InvitationStatus, UserHouseholdAssociation
from database import SessionLocal
import config
from openai import OpenAI
import anthropic
import os
import datetime
import secrets
from dotenv import load_dotenv
from starlette.middleware.sessions import SessionMiddleware
from auth import (
    get_current_user, require_user, require_admin, is_admin,
    hash_password, verify_password, authenticate_user, create_user,
    generate_verification_token, get_verification_link, get_password_reset_link,
    get_invitation_link, BASE_URL
)
from email_service import (
    send_verification_email, send_password_reset_email, send_household_invitation_email
)

load_dotenv()

# AI client initialization
openai_api_key = os.getenv('OPENAI_API_KEY')
client = OpenAI(api_key=openai_api_key) if openai_api_key else None

anthropic_api_key = os.getenv('ANTHROPIC_API_KEY')
anthropic_client = anthropic.Client(api_key=anthropic_api_key) if anthropic_api_key else None

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.getenv('SESSION_SECRET', os.getenv('SECRET_KEY', 'default-secret-key')))

# Redirect all HTTP requests to HTTPS in production, except for health checks
@app.middleware("http")
async def https_redirect_middleware(request: Request, call_next):
    if os.getenv('RAILWAY_ENVIRONMENT') and request.headers.get("x-forwarded-proto") == "http":
        if request.url.path != "/health":
            url = request.url.replace(scheme="https")
            return RedirectResponse(url, status_code=307)
    
    return await call_next(request)

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

@app.get('/health')
async def health_check():
    return {"status": "healthy"}

# ============================================
# Authentication Routes (Email/Password)
# ============================================

@app.get('/login', response_class=HTMLResponse)
async def login_page(request: Request, error: str = None, message: str = None):
    """Show login page."""
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error,
        "message": message
    })

@app.post('/login')
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Handle login form submission."""
    user = authenticate_user(db, email, password)
    
    if not user:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid email or password"
        })
    
    if not user.is_email_verified:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Please verify your email before logging in. Check your inbox for the verification link."
        })
    
    # Store user email in session
    request.session['user_email'] = user.email
    
    return RedirectResponse(url='/', status_code=303)

@app.get('/register', response_class=HTMLResponse)
async def register_page(request: Request, error: str = None, invite_code: str = None):
    """Show registration page."""
    return templates.TemplateResponse("register.html", {
        "request": request,
        "error": error,
        "invite_code": invite_code
    })

@app.post('/register')
async def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    invite_code: str = Form(None),
    db: Session = Depends(get_db)
):
    """Handle registration form submission."""
    # Validate password match
    if password != confirm_password:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Passwords do not match",
            "invite_code": invite_code
        })
    
    # Validate password strength
    if len(password) < 8:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Password must be at least 8 characters",
            "invite_code": invite_code
        })
    
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "An account with this email already exists",
            "invite_code": invite_code
        })
    
    # Check if this is the first user (make them admin)
    is_first_user = db.query(User).count() == 0
    
    # Create user
    user = create_user(db, email, password, name, is_first_user)
    
    # Send verification email
    verification_link = get_verification_link(user.email_verification_token)
    send_verification_email(user.email, user.name, verification_link)
    
    # If there's an invite code, store it in session for after verification
    if invite_code:
        request.session['pending_invite_code'] = invite_code
    
    return templates.TemplateResponse("login.html", {
        "request": request,
        "message": "Registration successful! Please check your email to verify your account."
    })

@app.get('/verify-email/{token}')
async def verify_email(request: Request, token: str, db: Session = Depends(get_db)):
    """Verify user's email address."""
    user = db.query(User).filter(User.email_verification_token == token).first()
    
    if not user:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid verification link"
        })
    
    if user.email_verification_expires < datetime.datetime.utcnow():
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Verification link has expired. Please register again."
        })
    
    # Mark email as verified
    user.is_email_verified = True
    user.email_verification_token = None
    user.email_verification_expires = None
    db.commit()
    
    # Auto-login the user
    request.session['user_email'] = user.email
    
    # Check for pending invite
    invite_code = request.session.pop('pending_invite_code', None)
    if invite_code:
        return RedirectResponse(url=f'/accept-invite/{invite_code}', status_code=303)
    
    return RedirectResponse(url='/?message=Email verified successfully!', status_code=303)

@app.get('/forgot-password', response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    """Show forgot password page."""
    return templates.TemplateResponse("forgot_password.html", {"request": request})

@app.post('/forgot-password')
async def forgot_password(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db)
):
    """Handle forgot password form submission."""
    user = db.query(User).filter(User.email == email).first()
    
    # Always show success message (don't reveal if email exists)
    if user:
        # Generate reset token
        token = secrets.token_urlsafe(32)
        user.password_reset_token = token
        user.password_reset_expires = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        db.commit()
        
        # Send reset email
        reset_link = get_password_reset_link(token)
        send_password_reset_email(user.email, user.name, reset_link)
    
    return templates.TemplateResponse("forgot_password.html", {
        "request": request,
        "message": "If an account with that email exists, we've sent a password reset link."
    })

@app.get('/reset-password/{token}', response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str, db: Session = Depends(get_db)):
    """Show reset password page."""
    user = db.query(User).filter(User.password_reset_token == token).first()
    
    if not user or user.password_reset_expires < datetime.datetime.utcnow():
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid or expired reset link"
        })
    
    return templates.TemplateResponse("reset_password.html", {
        "request": request,
        "token": token
    })

@app.post('/reset-password/{token}')
async def reset_password(
    request: Request,
    token: str,
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Handle password reset form submission."""
    user = db.query(User).filter(User.password_reset_token == token).first()
    
    if not user or user.password_reset_expires < datetime.datetime.utcnow():
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid or expired reset link"
        })
    
    if password != confirm_password:
        return templates.TemplateResponse("reset_password.html", {
            "request": request,
            "token": token,
            "error": "Passwords do not match"
        })
    
    if len(password) < 8:
        return templates.TemplateResponse("reset_password.html", {
            "request": request,
            "token": token,
            "error": "Password must be at least 8 characters"
        })
    
    # Update password
    user.password_hash = hash_password(password)
    user.password_reset_token = None
    user.password_reset_expires = None
    db.commit()
    
    return templates.TemplateResponse("login.html", {
        "request": request,
        "message": "Password reset successful! You can now log in with your new password."
    })

@app.get('/logout')
async def logout(request: Request):
    """Log out the current user."""
    request.session.pop('user_email', None)
    return RedirectResponse(url='/login')

@app.get('/accept-invite/{invite_code}')
async def accept_invite(
    request: Request,
    invite_code: str,
    db: Session = Depends(get_db)
):
    """Handle invitation link clicks. Redirects to register or processes acceptance."""
    # Find the invitation
    invitation = db.query(HouseholdInvitation).filter(
        HouseholdInvitation.invite_code == invite_code,
        HouseholdInvitation.status == InvitationStatus.PENDING
    ).first()
    
    if not invitation:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid or expired invitation link"
        })
    
    # Check if invitation has expired
    if invitation.expires_at and invitation.expires_at < datetime.datetime.utcnow():
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "This invitation has expired"
        })
    
    # Check if user is logged in
    user = get_current_user(request, db)
    
    if user:
        # User is logged in - check if their email matches
        if user.email.lower() == invitation.email.lower():
            # Accept the invitation
            assoc = UserHouseholdAssociation(
                user_id=user.id,
                household_id=invitation.household_id,
                is_primary=len(user.households) == 0
            )
            db.add(assoc)
            invitation.status = InvitationStatus.ACCEPTED
            db.commit()
            
            return RedirectResponse(url='/?message=You have joined the household!', status_code=303)
        else:
            return templates.TemplateResponse("login.html", {
                "request": request,
                "error": f"This invitation was sent to {invitation.email}. Please logout and login with that email."
            })
    
    # Check if user with this email already exists
    existing_user = db.query(User).filter(User.email == invitation.email).first()
    
    if existing_user:
        # Redirect to login
        request.session['pending_invite_code'] = invite_code
        return RedirectResponse(url='/login?message=Please login to accept the invitation', status_code=303)
    else:
        # Redirect to registration with invite code
        return RedirectResponse(url=f'/register?invite_code={invite_code}', status_code=303)

@app.get('/', response_class=HTMLResponse)
async def read_form(
    request: Request, 
    db: Session = Depends(get_db),
    start_date: str = Query(None),
    end_date: str = Query(None)
):
    user = get_current_user(request, db)
    
    if not user:
        return templates.TemplateResponse("login.html", {
            "request": request,
        })
    
    # Get households (admins see all, members see only their own)
    if is_admin(user):
        households = db.query(Household).all()
    else:
        households = user.households
    
    # Get pending invitations for this user
    pending_invitations = []
    if user.email:
        pending_invitations = db.query(HouseholdInvitation).join(Household).filter(
            HouseholdInvitation.email == user.email,
            HouseholdInvitation.status == InvitationStatus.PENDING
        ).all()
    
    # Get the user's primary household
    primary_household = user.get_primary_household()
    
    # Set up date range (default to last 7 days)
    today = datetime.datetime.now().date()
    if end_date:
        try:
            end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            end_dt = today
    else:
        end_dt = today
    
    if start_date:
        try:
            start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        except ValueError:
            start_dt = today - datetime.timedelta(days=6)
    else:
        start_dt = today - datetime.timedelta(days=6)
    
    # Convert to datetime for comparison (start of start_date to end of end_date)
    start_datetime = datetime.datetime.combine(start_dt, datetime.time.min)
    end_datetime = datetime.datetime.combine(end_dt, datetime.time.max)
    
    # Calculate nutrition stats for the date range
    total_calories = 0
    total_protein = 0
    total_carbs = 0
    total_fiber = 0
    total_fat = 0
    total_sugar = 0
    nutrition_per_person = []
    
    if user.households:
        household_ids = [h.id for h in user.households]
        
        # Get total nutrition
        from sqlalchemy import func
        totals = db.query(
            func.sum(FoodLog.calorie_count).label('calories'),
            func.sum(FoodLog.protein).label('protein'),
            func.sum(FoodLog.carbohydrates).label('carbs'),
            func.sum(FoodLog.fiber).label('fiber'),
            func.sum(FoodLog.fat).label('fat'),
            func.sum(FoodLog.sugar).label('sugar')
        )\
            .filter(FoodLog.household_id.in_(household_ids))\
            .filter(FoodLog.timestamp >= start_datetime)\
            .filter(FoodLog.timestamp <= end_datetime)\
            .first()
        
        if totals:
            total_calories = totals.calories or 0
            total_protein = totals.protein or 0
            total_carbs = totals.carbs or 0
            total_fiber = totals.fiber or 0
            total_fat = totals.fat or 0
            total_sugar = totals.sugar or 0
        
        # Get nutrition per person
        per_person = db.query(
            User.id,
            User.name,
            func.sum(FoodLog.calorie_count).label('total_calories'),
            func.sum(FoodLog.protein).label('total_protein'),
            func.sum(FoodLog.carbohydrates).label('total_carbs'),
            func.sum(FoodLog.fiber).label('total_fiber'),
            func.sum(FoodLog.fat).label('total_fat'),
            func.sum(FoodLog.sugar).label('total_sugar'),
            func.count(FoodLog.id).label('log_count')
        )\
            .select_from(FoodLog)\
            .join(User, FoodLog.user_id == User.id)\
            .filter(FoodLog.household_id.in_(household_ids))\
            .filter(FoodLog.timestamp >= start_datetime)\
            .filter(FoodLog.timestamp <= end_datetime)\
            .group_by(User.id, User.name)\
            .order_by(func.sum(FoodLog.calorie_count).desc())\
            .all()
        
        for person in per_person:
            nutrition_per_person.append({
                'user_id': person.id,
                'user_name': person.name,
                'total_calories': round(person.total_calories or 0, 0),
                'total_protein': round(person.total_protein or 0, 1),
                'total_carbs': round(person.total_carbs or 0, 1),
                'total_fiber': round(person.total_fiber or 0, 1),
                'total_fat': round(person.total_fat or 0, 1),
                'total_sugar': round(person.total_sugar or 0, 1),
                'log_count': person.log_count
            })
    
    # Get recent food logs (top 5) for user's households
    recent_logs = []
    if user.households:
        household_ids = [h.id for h in user.households]
        logs = db.query(FoodLog, User, Household)\
            .select_from(FoodLog)\
            .join(User, FoodLog.user_id == User.id)\
            .join(Household, FoodLog.household_id == Household.id)\
            .filter(FoodLog.household_id.in_(household_ids))\
            .order_by(FoodLog.timestamp.desc())\
            .limit(5)\
            .all()
        
        for log, log_user, household in logs:
            recent_logs.append({
                'id': log.id,
                'household_name': household.name,
                'user_name': log_user.name,
                'food_name': log.food_name,
                'portion_size': log.portion_size,
                'calorie_count': log.calorie_count,
                'protein': log.protein,
                'carbohydrates': log.carbohydrates,
                'fiber': log.fiber,
                'fat': log.fat,
                'sugar': log.sugar,
                'timestamp': log.timestamp.strftime("%b %d, %Y %I:%M %p")
            })
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user,
        "households": households,
        "pending_invitations": pending_invitations,
        "primary_household": primary_household,
        "recent_logs": recent_logs,
        "total_calories": round(total_calories, 0),
        "total_protein": round(total_protein, 1),
        "total_carbs": round(total_carbs, 1),
        "total_fiber": round(total_fiber, 1),
        "total_fat": round(total_fat, 1),
        "total_sugar": round(total_sugar, 1),
        "nutrition_per_person": nutrition_per_person,
        "start_date": start_dt.strftime("%Y-%m-%d"),
        "end_date": end_dt.strftime("%Y-%m-%d")
    })

@app.get('/manage_household', response_class=HTMLResponse)
async def manage_household(
    request: Request, 
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    # Only show households the admin is a member of
    households = admin.households
    # Get users who are not in any household
    users_with_households = db.query(User.id).join(UserHouseholdAssociation).distinct()
    users_without_household = db.query(User).filter(~User.id.in_(users_with_households)).all()
    
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
            # Get pending invitations for admin
            pending_invitations = []
            if admin.email:
                pending_invitations = db.query(HouseholdInvitation).join(Household).filter(
                    HouseholdInvitation.email == admin.email,
                    HouseholdInvitation.status == InvitationStatus.PENDING
                ).all()
            return templates.TemplateResponse("index.html", {
                "request": request,
                "user": admin,
                "households": households,
                "pending_invitations": pending_invitations,
                "primary_household": admin.get_primary_household(),
                "message": f"Household '{household_name}' already exists!"
            })

        # Create new household
        household = Household(name=household_name)
        db.add(household)
        
        # Store admin ID before commit (to avoid session detachment issues)
        admin_id = admin.id
        
        try:
            db.commit()
            db.refresh(household)
            
            # Re-query the admin user to check their current households
            admin = db.query(User).filter(User.id == admin_id).first()
            
            # Add the creator as a member of the new household
            is_first_household = len(admin.households) == 0
            association = UserHouseholdAssociation(
                user_id=admin.id,
                household_id=household.id,
                is_primary=is_first_household  # Set as primary if it's their first household
            )
            db.add(association)
            db.commit()
            db.refresh(admin)  # Refresh admin to get updated households list
            
        except Exception as db_error:
            db.rollback()
            print(f"Database error: {str(db_error)}")
            raise HTTPException(status_code=500, detail="Database error occurred")

        # Get updated list of households
        households = db.query(Household).all()
        # Get pending invitations for admin
        pending_invitations = []
        if admin.email:
            pending_invitations = db.query(HouseholdInvitation).join(Household).filter(
                HouseholdInvitation.email == admin.email,
                HouseholdInvitation.status == InvitationStatus.PENDING
            ).all()
        return templates.TemplateResponse("index.html", {
            "request": request,
            "user": admin,
            "households": households,
            "pending_invitations": pending_invitations,
            "primary_household": admin.get_primary_household(),
            "message": f"Household '{household_name}' created successfully!"
        })
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        households = db.query(Household).all()
        # Get pending invitations for admin
        pending_invitations = []
        if admin.email:
            pending_invitations = db.query(HouseholdInvitation).join(Household).filter(
                HouseholdInvitation.email == admin.email,
                HouseholdInvitation.status == InvitationStatus.PENDING
            ).all()
        return templates.TemplateResponse("index.html", {
            "request": request,
            "user": admin,
            "households": households,
            "pending_invitations": pending_invitations,
            "primary_household": admin.get_primary_household(),
            "message": "An unexpected error occurred while creating the household."
        }, status_code=500)

@app.post('/delete_household', response_class=HTMLResponse)
async def delete_household(
    request: Request,
    household_id: int = Form(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    # Check if household exists
    household = db.query(Household).filter(Household.id == household_id).first()
    if not household:
        raise HTTPException(status_code=404, detail="Household not found")
    
    # Check if admin is a member of this household
    if household not in admin.households:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete households you are a member of"
        )
    
    household_name = household.name
    
    try:
        # Delete all food logs associated with this household
        db.query(FoodLog).filter(FoodLog.household_id == household_id).delete()
        
        # Delete all invitations associated with this household
        db.query(HouseholdInvitation).filter(HouseholdInvitation.household_id == household_id).delete()
        
        # Delete all user-household associations
        db.query(UserHouseholdAssociation).filter(UserHouseholdAssociation.household_id == household_id).delete()
        
        # Delete the household
        db.delete(household)
        db.commit()
        
        # Refresh admin to update their households list
        db.refresh(admin)
        
    except Exception as e:
        db.rollback()
        print(f"Error deleting household: {str(e)}")
        raise HTTPException(status_code=500, detail="Error deleting household")
    
    return RedirectResponse(url='/manage_household', status_code=303)

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
    
    # Check if user is already in this household
    if household_id in [h.id for h in user_to_add.households]:
        raise HTTPException(status_code=400, detail="User is already in this household")
    
    # Add user to household
    association = UserHouseholdAssociation(
        user_id=user_to_add.id,
        household_id=household_id,
        is_primary=len(user_to_add.households) == 0  # Set as primary if it's the first household
    )
    db.add(association)
    db.commit()
    
    return RedirectResponse(url='/manage_household', status_code=303)

@app.post('/add_self_to_household', response_class=HTMLResponse)
async def add_self_to_household(
    request: Request,
    household_id: int = Form(...),
    set_as_primary: bool = Form(False, alias="set_as_primary"),
    auth_user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    try:
        user_id = auth_user.id  # Store the user ID for later retrieval
        current_user = db.query(User).get(user_id)  
        
        # Check if household exists
        household = db.query(Household).filter(Household.id == household_id).first()
        if not household:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user": current_user,
                "error_message": "The selected household does not exist."
            })
        
        # Check if user is already in this household
        if household in current_user.households:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user": current_user,
                "error_message": "You are already a member of this household."
            })
        
        # Add user to the household
        association = UserHouseholdAssociation(
            user_id=current_user.id,
            household_id=household_id,
            is_primary=set_as_primary or len(current_user.households) == 0  # Set as primary if requested or if it's the first household
        )
        
        # If this is set as primary, unset any existing primary
        if set_as_primary:
            existing_primary = db.query(UserHouseholdAssociation).filter(
                UserHouseholdAssociation.user_id == current_user.id,
                UserHouseholdAssociation.is_primary == True
            ).first()
            
            if existing_primary:
                existing_primary.is_primary = False
        
        db.add(association)
        db.commit()
        db.refresh(current_user)  # Refresh the current_user object with updated data
        
        # Get pending invitations for this user
        pending_invitations = []
        if current_user.email:
            pending_invitations = db.query(HouseholdInvitation).join(Household).filter(
                HouseholdInvitation.email == current_user.email,
                HouseholdInvitation.status == InvitationStatus.PENDING
            ).all()
        
        # Get all households for display
        if is_admin(current_user):
            all_households = db.query(Household).all()
        else:
            all_households = current_user.households
            
        return templates.TemplateResponse("index.html", {
            "request": request,
            "user": current_user,
            "households": all_households,
            "pending_invitations": pending_invitations,
            "primary_household": current_user.get_primary_household(),
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
        # Get users who are not in any household
        users_with_households = db.query(User.id).join(UserHouseholdAssociation).distinct()
        return templates.TemplateResponse("household_form.html", {
            "request": request,
            "user": admin,
            "households": db.query(Household).all(),
            "available_users": db.query(User).filter(~User.id.in_(users_with_households)).all(),
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
        
        # Get users who are not in any household
        users_with_households = db.query(User.id).join(UserHouseholdAssociation).distinct()
        return templates.TemplateResponse("household_form.html", {
            "request": request,
            "user": admin,
            "households": db.query(Household).all(),
            "available_users": db.query(User).filter(~User.id.in_(users_with_households)).all(),
            "invite_url": invite_url,
            "message": f"Invitation for {email} already exists",
            "pending_invitations": pending_invitations
        })
    
    if existing_user:
        if existing_user.households:
            return templates.TemplateResponse("household_form.html", {
                "request": request,
                "user": admin,
                "households": db.query(Household).all(),
                "available_users": db.query(User).filter(~User.id.in_(
                    db.query(User.id).join(UserHouseholdAssociation).distinct()
                )).all(),
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
            
            invite_url = f"{BASE_URL}/join_household?code={invitation.invite_code}"
            
            # Send invitation email
            send_household_invitation_email(
                to_email=email,
                inviter_name=admin.name,
                household_name=household.name,
                invitation_link=invite_url
            )
            
            # Get all pending invitations for this household
            pending_invitations = db.query(HouseholdInvitation).filter(
                HouseholdInvitation.household_id == household_id,
                HouseholdInvitation.status == InvitationStatus.PENDING
            ).all()
            
            return templates.TemplateResponse("household_form.html", {
                "request": request,
                "user": admin,
                "households": db.query(Household).all(),
                "available_users": db.query(User).filter(~User.id.in_(
                    db.query(User.id).join(UserHouseholdAssociation).distinct()
                )).all(),
                "invite_url": invite_url,
                "message": f"Invitation email sent to {email}",
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
        
        # Use accept-invite route which will prompt registration
        invite_url = f"{BASE_URL}/accept-invite/{invitation.invite_code}"
        
        # Send invitation email
        send_household_invitation_email(
            to_email=email,
            inviter_name=admin.name,
            household_name=household.name,
            invitation_link=invite_url
        )
        
        # Get all pending invitations for this household
        pending_invitations = db.query(HouseholdInvitation).filter(
            HouseholdInvitation.household_id == household_id,
            HouseholdInvitation.status == InvitationStatus.PENDING
        ).all()
        
        # Get users who are not in any household
        users_with_households = db.query(User.id).join(UserHouseholdAssociation).distinct()
        return templates.TemplateResponse("household_form.html", {
            "request": request,
            "user": admin,
            "households": db.query(Household).all(),
            "available_users": db.query(User).filter(~User.id.in_(users_with_households)).all(),
            "invite_url": invite_url,
            "message": f"Invitation email sent to {email}",
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
    
    # Check if user is already in this household
    if invitation.household in user.households:
        # Mark invitation as accepted
        invitation.status = InvitationStatus.ACCEPTED
        db.commit()
        return RedirectResponse(url='/', status_code=303)
    
    # Add user to household
    is_first_household = len(user.households) == 0
    association = UserHouseholdAssociation(
        user_id=user.id,
        household_id=invitation.household_id,
        is_primary=is_first_household  # Set as primary if it's the first household
    )
    db.add(association)
    
    # Mark invitation as accepted
    invitation.status = InvitationStatus.ACCEPTED
    
    db.commit()
    
    return RedirectResponse(url='/', status_code=303)

@app.post('/set_primary_household', response_class=HTMLResponse)
async def set_primary_household(
    request: Request,
    household_id: int = Form(...),
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    # Check if user is in the specified household
    household = db.query(Household).filter(Household.id == household_id).first()
    if not household or household not in current_user.households:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "user": current_user,
            "error_message": "You are not a member of this household."
        })
    
    # Update the associations
    # First, unset any existing primary
    db.query(UserHouseholdAssociation).filter(
        UserHouseholdAssociation.user_id == current_user.id,
        UserHouseholdAssociation.is_primary == True
    ).update({"is_primary": False})
    
    # Then set the new primary
    db.query(UserHouseholdAssociation).filter(
        UserHouseholdAssociation.user_id == current_user.id,
        UserHouseholdAssociation.household_id == household_id
    ).update({"is_primary": True})
    
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
        
        # Check if user is already in this household
        if household in current_user.households:
            invitation.status = InvitationStatus.ACCEPTED
            db.commit()
            
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user": current_user,
                "error_message": "You are already a member of this household."
            })
        
        # Add user to household
        is_first_household = len(current_user.households) == 0
        association = UserHouseholdAssociation(
            user_id=current_user.id,
            household_id=invitation.household_id,
            is_primary=is_first_household  # Set as primary if it's the first household
        )
        db.add(association)
        
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
    household_id: int = Form(...),
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    # Check if user is in the specified household
    household = db.query(Household).filter(Household.id == household_id).first()
    if not household or household not in current_user.households:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "user": current_user,
            "error_message": "You are not a member of this household."
        })
    
    # Check if user is the only admin in the household
    if is_admin(current_user):
        # Count admins in this household
        admin_count = 0
        for member in household.members:
            if is_admin(member) and member.id != current_user.id:
                admin_count += 1
        
        if admin_count == 0 and len(household.members) > 1:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user": current_user,
                "error_message": "You cannot leave the household as you are the only admin. Please promote another member to admin first."
            })
    
    # Remove the association
    association = db.query(UserHouseholdAssociation).filter(
        UserHouseholdAssociation.user_id == current_user.id,
        UserHouseholdAssociation.household_id == household_id
    ).first()
    
    if association:
        was_primary = association.is_primary
        db.delete(association)
        
        # If this was the primary household and user has other households, set a new primary
        if was_primary:
            other_association = db.query(UserHouseholdAssociation).filter(
                UserHouseholdAssociation.user_id == current_user.id
            ).first()
            
            if other_association:
                other_association.is_primary = True
        
        db.commit()
    
    return RedirectResponse(url='/', status_code=303)

@app.get('/get_household_members/{household_id}')
async def get_household_members(
    household_id: int, 
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    # Check if user is admin or belongs to the requested household
    user_household_ids = [h.id for h in current_user.households]
    if not is_admin(current_user) and household_id not in user_household_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this household's members"
        )
    
    # Get members of the household through the association table
    household = db.query(Household).filter(Household.id == household_id).first()
    if not household:
        raise HTTPException(status_code=404, detail="Household not found")
    
    members = household.members
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
        # Admin users can only add food for users in their households
        current_user_household_ids = [h.id for h in current_user.households]
        user_household_ids = [h.id for h in user.households]
        
        # Check if there's any overlap in households
        if not any(hid in current_user_household_ids for hid in user_household_ids):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to add food for users outside your households"
            )

    # Get nutritional information from preferred AI
    nutrition = await get_nutrition_info(food_name, portion_size)

    # Add food log entry with full nutritional info
    food_log = FoodLog(
        user_id=user.id,
        household_id=household_id,
        food_name=food_name,
        portion_size=portion_size,
        calorie_count=nutrition['calories'],
        protein=nutrition['protein'],
        carbohydrates=nutrition['carbohydrates'],
        fiber=nutrition['fiber'],
        fat=nutrition['fat'],
        sugar=nutrition['sugar']
    )
    db.add(food_log)
    db.commit()
    db.refresh(food_log)

    message = f"Entry added for {user.name}. Calories: {nutrition['calories']:.0f} | Protein: {nutrition['protein']:.1f}g | Carbs: {nutrition['carbohydrates']:.1f}g | Fat: {nutrition['fat']:.1f}g"
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "user": current_user,
        "message": message,
        "primary_household": current_user.get_primary_household(),
        "households": current_user.households if not is_admin(current_user) else db.query(Household).all()
    })

async def get_nutrition_info(food_name, portion_size):
    """Get complete nutritional information from AI"""
    if config.PREFERRED_AI == 'openai':
        return await get_nutrition_from_openai(food_name, portion_size)
    elif config.PREFERRED_AI == 'anthropic':
        return await get_nutrition_from_anthropic(food_name, portion_size)
    else:
        return {'calories': 0, 'protein': 0, 'carbohydrates': 0, 'fiber': 0, 'fat': 0, 'sugar': 0}

async def get_nutrition_from_openai(food_name, portion_size):
    import json
    if not client:
        print("OpenAI client not initialized (missing API key)")
        return {'calories': 0, 'protein': 0, 'carbohydrates': 0, 'fiber': 0, 'fat': 0, 'sugar': 0}
        
    prompt = f"""Estimate the nutritional information for {portion_size} of {food_name}.
Respond with ONLY a JSON object in this exact format, no other text:
{{"calories": <number>, "protein": <grams>, "carbohydrates": <grams>, "fiber": <grams>, "fat": <grams>, "sugar": <grams>}}"""
    
    print(f"OpenAI Nutrition Prompt: {prompt}")
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=100,
        temperature=0.0
    )
    response_text = response.choices[0].message.content.strip()
    print(f"OpenAI Response: {response_text}")
    
    try:
        nutrition = json.loads(response_text)
        return {
            'calories': float(nutrition.get('calories', 0)),
            'protein': float(nutrition.get('protein', 0)),
            'carbohydrates': float(nutrition.get('carbohydrates', 0)),
            'fiber': float(nutrition.get('fiber', 0)),
            'fat': float(nutrition.get('fat', 0)),
            'sugar': float(nutrition.get('sugar', 0))
        }
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Failed to parse nutrition response: {e}")
        return {'calories': 0, 'protein': 0, 'carbohydrates': 0, 'fiber': 0, 'fat': 0, 'sugar': 0}

async def get_nutrition_from_anthropic(food_name, portion_size):
    import json
    if not anthropic_client:
        print("Anthropic client not initialized (missing API key)")
        return {'calories': 0, 'protein': 0, 'carbohydrates': 0, 'fiber': 0, 'fat': 0, 'sugar': 0}
        
    prompt = f"""Estimate the nutritional information for {portion_size} of {food_name}.
Respond with ONLY a JSON object in this exact format, no other text:
{{"calories": <number>, "protein": <grams>, "carbohydrates": <grams>, "fiber": <grams>, "fat": <grams>, "sugar": <grams>}}"""
    
    print(f"Anthropic Nutrition Prompt: {prompt}")
    response = anthropic_client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=100,
        temperature=0,
        messages=[{"role": "user", "content": prompt}]
    )
    response_text = response.content[0].text.strip()
    print(f"Anthropic Response: {response_text}")
    
    try:
        nutrition = json.loads(response_text)
        return {
            'calories': float(nutrition.get('calories', 0)),
            'protein': float(nutrition.get('protein', 0)),
            'carbohydrates': float(nutrition.get('carbohydrates', 0)),
            'fiber': float(nutrition.get('fiber', 0)),
            'fat': float(nutrition.get('fat', 0)),
            'sugar': float(nutrition.get('sugar', 0))
        }
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Failed to parse nutrition response: {e}")
        return {'calories': 0, 'protein': 0, 'carbohydrates': 0, 'fiber': 0, 'fat': 0, 'sugar': 0}

# Keep legacy function for backward compatibility
async def get_calorie_count(food_name, portion_size):
    nutrition = await get_nutrition_info(food_name, portion_size)
    return nutrition['calories']


@app.get('/view_logs', response_class=HTMLResponse)
async def view_logs(
    request: Request, 
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    # For admins, get all logs; for regular users, get only logs from their households
    if is_admin(current_user):
        logs = db.query(FoodLog, User, Household)\
            .select_from(FoodLog)\
            .join(User, FoodLog.user_id == User.id)\
            .join(Household, FoodLog.household_id == Household.id)\
            .all()
    else:
        # Get IDs of all households the user belongs to
        household_ids = [h.id for h in current_user.households]
        
        logs = db.query(FoodLog, User, Household)\
            .select_from(FoodLog)\
            .join(User, FoodLog.user_id == User.id)\
            .join(Household, FoodLog.household_id == Household.id)\
            .filter(FoodLog.household_id.in_(household_ids))\
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
            'protein': log.protein,
            'carbohydrates': log.carbohydrates,
            'fiber': log.fiber,
            'fat': log.fat,
            'sugar': log.sugar,
            'timestamp': log.timestamp.strftime("%b %d, %Y %I:%M %p")
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
