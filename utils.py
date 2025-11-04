"""
Utility functions for the Philosophers Fridge application.
"""
import datetime
from typing import Dict, List, Any

def format_timestamp(timestamp: datetime.datetime) -> str:
    """Format a datetime object into a readable string."""
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")

def calculate_daily_calories(logs: List[Dict[str, Any]], user_id: int) -> float:
    """
    Calculate the total calories consumed by a user in the current day.
    
    Args:
        logs: List of food log entries
        user_id: ID of the user
        
    Returns:
        Total calories consumed today
    """
    today = datetime.datetime.now().date()
    total_calories = 0.0
    
    for log in logs:
        if (log['user_id'] == user_id and 
            log['timestamp'].date() == today):
            total_calories += log['calorie_count']
            
    return total_calories

def get_calorie_goal_progress(current_calories: float, goal_calories: float) -> float:
    """
    Calculate the percentage of calorie goal reached.
    
    Args:
        current_calories: Current calories consumed
        goal_calories: Daily calorie goal
        
    Returns:
        Percentage of goal reached (0-100)
    """
    if goal_calories <= 0:
        return 0
    
    progress = (current_calories / goal_calories) * 100
    return min(progress, 100)  # Cap at 100%
