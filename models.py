from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship, declarative_base
import datetime

Base = declarative_base()

class Household(Base):
    __tablename__ = 'households'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Relationships
    members = relationship('User', back_populates='household')

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    household_id = Column(Integer, ForeignKey('households.id'))
    
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

class FoodLog(Base):
    __tablename__ = 'food_logs'
    id = Column(Integer, primary_key=True)
    food_name = Column(String)
    portion_size = Column(String)
    calorie_count = Column(Float)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    user_id = Column(Integer, ForeignKey('users.id'))
    user = relationship('User', back_populates='food_logs')
