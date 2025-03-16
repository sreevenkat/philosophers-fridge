from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Enum
from sqlalchemy.orm import relationship, declarative_base
import datetime
import enum
import uuid

Base = declarative_base()

def generate_invite_code():
    return str(uuid.uuid4())

class UserRole(enum.Enum):
    ADMIN = "admin"
    MEMBER = "member"

class Household(Base):
    __tablename__ = 'households'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Relationships
    members = relationship('User', back_populates='household')
    invitations = relationship('HouseholdInvitation', back_populates='household')

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String, unique=True)
    google_id = Column(String, unique=True)
    picture = Column(String, nullable=True)
    role = Column(Enum(UserRole), default=UserRole.MEMBER)
    household_id = Column(Integer, ForeignKey('households.id'), nullable=True)
    
    # Nutritional preferences and goals
    daily_calorie_goal = Column(Integer, nullable=True)
    is_vegetarian = Column(Boolean, default=False)
    is_vegan = Column(Boolean, default=False)
    has_gluten_allergy = Column(Boolean, default=False)
    has_nut_allergy = Column(Boolean, default=False)
    additional_preferences = Column(String, nullable=True)

    # Relationships
    household = relationship('Household', back_populates='members')
    food_logs = relationship('FoodLog', back_populates='user')

class InvitationStatus(enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"

class HouseholdInvitation(Base):
    __tablename__ = 'household_invitations'
    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False)
    invite_code = Column(String, default=generate_invite_code, unique=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, default=lambda: datetime.datetime.utcnow() + datetime.timedelta(days=7))
    status = Column(Enum(InvitationStatus), default=InvitationStatus.PENDING)
    
    # Relationships
    household_id = Column(Integer, ForeignKey('households.id'))
    household = relationship('Household', back_populates='invitations')

class FoodLog(Base):
    __tablename__ = 'food_logs'
    id = Column(Integer, primary_key=True)
    food_name = Column(String)
    portion_size = Column(String)
    calorie_count = Column(Float)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    user_id = Column(Integer, ForeignKey('users.id'))
    user = relationship('User', back_populates='food_logs')
