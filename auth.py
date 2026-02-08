"""Authentication module with email/password support."""

from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from models import User, UserRole
from database import SessionLocal
from passlib.context import CryptContext
from itsdangerous import URLSafeTimedSerializer
import os
import secrets
import datetime
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Secret key for tokens
SECRET_KEY = os.getenv('SESSION_SECRET', os.getenv('SECRET_KEY', 'default-secret-key'))

# Serializer for tokens
serializer = URLSafeTimedSerializer(SECRET_KEY)

# Base URL for email links
BASE_URL = os.getenv('BASE_URL', 'http://localhost:8000')


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def generate_verification_token() -> str:
    """Generate a secure random token for email verification."""
    return secrets.token_urlsafe(32)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Get the current user from the session."""
    user_email = request.session.get('user_email')
    if not user_email:
        return None
    
    return db.query(User).filter(User.email == user_email).first()


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Require a logged-in user or raise an exception."""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    return user


def require_verified_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Require a logged-in AND email-verified user."""
    user = require_user(request, db)
    if not user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please check your email for verification link."
        )
    return user


def require_admin(request: Request, db: Session = Depends(get_db)) -> User:
    """Require an admin user or raise an exception."""
    user = require_user(request, db)
    if not is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return user


def is_admin(user: User) -> bool:
    """Check if user is an admin."""
    return user.role == UserRole.ADMIN


def create_user(
    db: Session,
    email: str,
    password: str,
    name: str,
    is_first_user: bool = False
) -> User:
    """Create a new user with hashed password and verification token."""
    verification_token = generate_verification_token()
    
    user = User(
        name=name,
        email=email,
        password_hash=hash_password(password),
        is_email_verified=False,
        email_verification_token=verification_token,
        email_verification_expires=datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        role=UserRole.ADMIN if is_first_user else UserRole.MEMBER
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return user


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """Authenticate a user by email and password."""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return None
    if not user.password_hash:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_verification_link(token: str) -> str:
    """Generate the full verification URL."""
    return f"{BASE_URL}/verify-email/{token}"


def get_password_reset_link(token: str) -> str:
    """Generate the full password reset URL."""
    return f"{BASE_URL}/reset-password/{token}"


def get_invitation_link(invite_code: str) -> str:
    """Generate the full invitation URL."""
    return f"{BASE_URL}/accept-invite/{invite_code}"
