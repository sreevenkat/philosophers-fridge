from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Enum, Table
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
    members = relationship('User', secondary='user_household_association', back_populates='households')
    invitations = relationship('HouseholdInvitation', back_populates='household')

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String, unique=True)
    google_id = Column(String, unique=True)
    picture = Column(String, nullable=True)
    role = Column(Enum(UserRole), default=UserRole.MEMBER)
    
    # Nutritional preferences and goals
    daily_calorie_goal = Column(Integer, nullable=True)
    is_vegetarian = Column(Boolean, default=False)
    is_vegan = Column(Boolean, default=False)
    has_gluten_allergy = Column(Boolean, default=False)
    has_nut_allergy = Column(Boolean, default=False)
    additional_preferences = Column(String, nullable=True)

    # Relationships
    household_associations = relationship('UserHouseholdAssociation', back_populates='user', overlaps="members")
    households = relationship('Household', secondary='user_household_association', back_populates='members', overlaps="household_associations")
    food_logs = relationship('FoodLog', back_populates='user')
    
    def get_primary_household(self):
        """Get the user's primary household if set"""
        for assoc in self.household_associations:
            if assoc.is_primary:
                return assoc.household
        # If no primary is set but user has households, return the first one
        return self.households[0] if self.households else None

class UserHouseholdAssociation(Base):
    __tablename__ = 'user_household_association'
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True)
    household_id = Column(Integer, ForeignKey('households.id'), primary_key=True)
    is_primary = Column(Boolean, default=False)
    joined_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    user = relationship('User', back_populates='household_associations', overlaps="households,members")
    household = relationship('Household', overlaps="households,members")

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
    
    # Nutritional information (in grams) - None indicates no data available
    protein = Column(Float, nullable=True, default=None)
    carbohydrates = Column(Float, nullable=True, default=None)
    fiber = Column(Float, nullable=True, default=None)
    fat = Column(Float, nullable=True, default=None)
    sugar = Column(Float, nullable=True, default=None)
    
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    user_id = Column(Integer, ForeignKey('users.id'))
    user = relationship('User', back_populates='food_logs')
    
    # Add household_id to track which household this food log belongs to
    household_id = Column(Integer, ForeignKey('households.id'))
    household = relationship('Household')

