from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from models import User, UserRole
from database import SessionLocal
from authlib.integrations.starlette_client import OAuth
from starlette.config import Config
from itsdangerous import URLSafeTimedSerializer
import os
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

# OAuth setup
config = Config(environ=os.environ)
oauth = OAuth(config)

oauth.register(
    name='google',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    client_kwargs={
        'scope': 'openid email profile'
    }
)

# Secret key for session
SECRET_KEY = os.getenv('SECRET_KEY', 'default-secret-key')

# Serializer for tokens
serializer = URLSafeTimedSerializer(SECRET_KEY)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Get the current user from the session"""
    user_email = request.session.get('user_email')
    if not user_email:
        return None
    
    return db.query(User).filter(User.email == user_email).first()

def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Require a logged-in user or raise an exception"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

def require_admin(request: Request, db: Session = Depends(get_db)) -> User:
    """Require an admin user or raise an exception"""
    user = require_user(request, db)
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized. Admin role required.",
        )
    return user

def is_admin(user: User) -> bool:
    """Check if a user has admin role"""
    return user and user.role == UserRole.ADMIN

def create_or_update_user(db: Session, user_info: dict) -> User:
    """Create or update a user from Google OAuth info"""
    email = user_info.get('email')
    if not email:
        raise ValueError("Email is required")
    
    user = db.query(User).filter(User.email == email).first()
    
    if not user:
        # Create new user
        user = User(
            email=email,
            name=user_info.get('name', email.split('@')[0]),
            google_id=user_info.get('sub'),
            picture=user_info.get('picture'),
            # First user is automatically an admin
            role=UserRole.ADMIN if db.query(User).count() == 0 else UserRole.MEMBER
        )
        db.add(user)
    else:
        # Update existing user
        user.name = user_info.get('name', user.name)
        user.google_id = user_info.get('sub', user.google_id)
        user.picture = user_info.get('picture', user.picture)
    
    db.commit()
    db.refresh(user)
    return user
