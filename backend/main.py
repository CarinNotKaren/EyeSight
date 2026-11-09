# Load environment variables before importing modules that use the database
# configuration or other backend settings.
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# FastAPI and database imports.
from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from database.connection import engine
from database.dependencies import get_db

# Import application routers after loading the environment.
from routers.auth import router as auth_router
from routers.questions import router as questions_router


# Create the main FastAPI application.
app = FastAPI(
    title="EyeSight API",
    description="Backend API for the EyeSight visual assistant.",
    version="1.0.0"
)

# Register the authentication and question endpoints.
app.include_router(auth_router)
app.include_router(questions_router)


@app.get("/")
def home():
    return {
        "message": "Welcome to EyeSight API",
        "status": "running"
    }


@app.get("/health/database")
def check_database():
    try:
        # Check whether the database engine can establish a connection.
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "connected",
            "database": "vision_assistant"
        }

    except SQLAlchemyError:
        return {
            "status": "error",
            "message": "Database connection failed"
        }


@app.get("/health/database-session")
def check_database_session(db: Session = Depends(get_db)):
    try:
        # Check whether a dependency-provided database session can execute SQL.
        db.execute(text("SELECT 1"))

        return {
            "status": "connected",
            "message": "Database session working correctly"
        }

    except SQLAlchemyError:
        return {
            "status": "error",
            "message": "Database query failed"
        }