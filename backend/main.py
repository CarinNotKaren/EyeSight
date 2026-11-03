from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from database.connection import engine
from database.dependencies import get_db

app = FastAPI(
    title="EyeSight API",
    description="Backend API for the EyeSight visual assistant.",
    version="1.0.0"
)


@app.get("/")
def home():
    return {
        "message": "Welcome to EyeSight API",
        "status": "running"
    }


@app.get("/health/database")
def check_database():
    try:
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