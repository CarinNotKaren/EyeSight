import jwt
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import update
from typing import cast
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import hashlib
from datetime import datetime, timezone, timedelta
from sqlalchemy.engine import CursorResult
from database.models.refresh_token import RefreshToken
from database.dependencies import get_db
from database.models.user import User
from schemas.auth import (
    SignUpRequest,
    LoginRequest,
    RefreshTokenRequest,
    LogoutRequest
)
from security.password import hash_password, verify_password
from security.jwt import (
    create_access_token,
    create_refresh_token,
    verify_access_token,
    REFRESH_TOKEN_EXPIRE_DAYS,
    SECRET_KEY,
    ALGORITHM
)
router = APIRouter(prefix="/auth", tags=["Authentication"])

bearer_scheme = HTTPBearer()
@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(data: SignUpRequest, db: Session = Depends(get_db)):

    # Check whether the email is already registered
    existing_user = db.query(User).filter(
        User.email == str(data.email).lower()
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=409,
            detail="Email is already registered"
        )

    # Create a new user with a hashed password
    new_user = User(
        display_name=data.display_name.strip(),
        email=str(data.email).lower(),
        password_hash=hash_password(data.password)
    )

    db.add(new_user)

    try:
        db.commit()
        db.refresh(new_user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Email is already registered"
        )

    return {
        "message": "Account created successfully",
        "user_id": new_user.user_id,
        "display_name": new_user.display_name,
        "email": new_user.email
    }


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):

    # Find the user using their email
    user = db.query(User).filter(
        User.email == str(data.email).lower()
    ).first()

    # Check if the user exists and password is correct
    if not user or not verify_password(
        data.password, str(user.password_hash)
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    
   
   
    user_id = cast(int, user.user_id)

    # Create both tokens
    access_token = create_access_token(user_id)
    refresh_token = create_refresh_token(user_id)

    # Read the unique identifier from the refresh token
    

    payload = jwt.decode(
        refresh_token,
        SECRET_KEY,
        algorithms=[ALGORITHM]
    )

    token_jti = payload["jti"]

    # Hash the identifier before storing it
    token_hash = hashlib.sha256(
        token_jti.encode("utf-8")
    ).hexdigest()

    # Save the refresh token record in MySQL
    now = datetime.now(timezone.utc)

    new_refresh_token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=(
            now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        ).replace(tzinfo=None)
    )

    db.add(new_refresh_token)
    db.commit()


    return {
        "message": "Login successful",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user_id": user.user_id,
        "display_name": user.display_name,
        "email": user.email
    }

@router.get("/me")
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
):
    user_id = verify_access_token(credentials.credentials)

    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )

    user = db.query(User).filter(User.user_id == user_id).first()

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="User not found or no longer active"
        )

    return {
        "user_id": user.user_id,
        "display_name": user.display_name,
        "email": user.email,
        "preferred_language": user.preferred_language
    }


@router.post("/refresh")
def refresh_tokens(
    data: RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    # 1. Decode and validate the refresh token
    try:
        payload = jwt.decode(
            data.refresh_token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp", "iat", "jti"]}
        )

        if payload.get("type") != "refresh":
            raise ValueError("Wrong token type")

        user_id = payload.get("sub")
        token_jti = payload.get("jti")

        if (
            not isinstance(user_id, str)
            or not user_id.isdigit()
            or not isinstance(token_jti, str)
            or not token_jti
        ):
            raise ValueError("Invalid token data")

    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired refresh token"
        )

    # 2. Find the hashed identifier in MySQL
    
    # Check that the user still exists
    user = db.query(User).filter(
        User.user_id == int(user_id)
    ).first()

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="User account no longer exists"
        )

    token_hash = hashlib.sha256(
        token_jti.encode("utf-8")
    ).hexdigest()

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 3. Revoke the old token only if it is still active
    result = cast(CursorResult, db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == int(user_id),
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now
        )
        .values(revoked_at=now)
    ))

    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=401,
            detail="Refresh token is revoked or expired"
        )

    # 4. Create replacement tokens
    new_access_token = create_access_token(int(user_id))
    new_refresh_token = create_refresh_token(int(user_id))

    new_payload = jwt.decode(
        new_refresh_token,
        SECRET_KEY,
        algorithms=[ALGORITHM]
    )

    new_token_hash = hashlib.sha256(
        new_payload["jti"].encode("utf-8")
    ).hexdigest()

    new_expires_at = datetime.fromtimestamp(
        new_payload["exp"],
        tz=timezone.utc
    ).replace(tzinfo=None)

    db.add(
        RefreshToken(
            user_id=int(user_id),
            token_hash=new_token_hash,
            expires_at=new_expires_at
        )
    )

    # 5. Save both changes together
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=401,
            detail="Unable to refresh token"
        )

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }


@router.post("/logout")
def logout(
    data: LogoutRequest,
    db: Session = Depends(get_db)
):
    # 1. Validate the refresh token
    try:
        payload = jwt.decode(
            data.refresh_token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp", "iat", "jti"]}
        )

        if payload.get("type") != "refresh":
            raise ValueError("Wrong token type")

        user_id = payload.get("sub")
        token_jti = payload.get("jti")

        if (
            not isinstance(user_id, str)
            or not user_id.isdigit()
            or not isinstance(token_jti, str)
            or not token_jti
        ):
            raise ValueError("Invalid token data")

    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired refresh token"
        )

    # 2. Hash the token identifier
    token_hash = hashlib.sha256(
        token_jti.encode("utf-8")
    ).hexdigest()

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 3. Revoke the refresh token in MySQL
    result = cast(CursorResult, db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == int(user_id),
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None)
        )
        .values(revoked_at=now)
    ))

    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=401,
            detail="Refresh token already revoked or not found"
        )

    db.commit()

    return {
        "message": "Logout successful"
    }
