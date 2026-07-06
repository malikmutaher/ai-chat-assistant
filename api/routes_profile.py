"""POST /api/profile — saves name, gender, and optional phone for a session."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import get_db
from database.crud import get_or_create_user
from database.models import Gender
from api.schemas import ProfileRequest, ProfileResponse

router = APIRouter()


@router.post("/api/profile", response_model=ProfileResponse)
def save_profile(request: ProfileRequest, db: Session = Depends(get_db)):
    try:
        gender = Gender(request.gender)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"gender must be one of: {[g.value for g in Gender]}",
        )

    user = get_or_create_user(
        db,
        session_id=request.session_id,
        name=request.name,
        gender=gender,
        phone=request.phone,
    )

    return ProfileResponse(user_id=user.id, message=f"Welcome, {user.name}!")
