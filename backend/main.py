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
from routers.speech import router as speech_router
from routers.webrtc import router as webrtc_router
from routers.sessions import router as sessions_router
from multimedia.webrtc_receiver import webrtc_receiver
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

# Close active peer connections during a graceful application shutdown.
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await webrtc_receiver.close_all()


# Create the main FastAPI application.
app = FastAPI(
    lifespan=lifespan,
    title="EyeSight API",
    description="Backend API for the EyeSight visual assistant.",
    version="1.0.0"
)

# Allow the local React/Vite frontend to communicate with FastAPI.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register the authentication, question, and speech endpoints.
app.include_router(auth_router)
app.include_router(questions_router)
app.include_router(speech_router)
app.include_router(webrtc_router)
app.include_router(sessions_router)


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
