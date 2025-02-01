# Philosophers Fridge

A thoughtful meal planning and nutrition tracking application that helps users create personalized weekly meal plans based on their preferences and nutritional goals.

## Project Overview

Philosophers Fridge helps users:
- Define their nutritional goals and dietary preferences
- Generate personalized weekly meal plans
- Track their daily food intake
- Monitor progress towards nutritional targets
- Maintain a log of meals and portions

## Features

- Personalized meal planning
- Food intake logging with portion tracking
- Calorie estimation for common foods
- User preference management
- Weekly meal plan generation
- Progress tracking
- SQLite database storage
- Web interface built with FastAPI and Jinja2

## Requirements

- Python 3.x
- FastAPI
- SQLAlchemy
- Jinja2
- Additional dependencies in requirements.txt

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file with your configuration:
   ```
   OPENAI_API_KEY=your_key_here
   ANTHROPIC_API_KEY=your_key_here
   ```

## Running the Application

Start the FastAPI server:
```bash
uvicorn main:app --reload
```

Then visit http://localhost:8000 in your web browser.

## Usage

1. Enter your name
2. Input your meal preferences and nutritional goals
3. Generate your weekly meal plan
4. Log your daily food intake
5. Track your progress

## Database Schema

- Users table: Stores user information and preferences
- Food_logs table: Stores food entries with timestamps and nutritional information

## Development

- Tests can be run using pytest
- Code formatting is handled by black
- Type checking with mypy
- Linting with flake8

## Configuration

Basic configuration options can be modified in config.py
