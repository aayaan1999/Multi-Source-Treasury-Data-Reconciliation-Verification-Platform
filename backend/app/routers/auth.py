from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..db import query_one
from ..security import DUMMY_HASH, create_token, current_user, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: LoginRequest):
    user = query_one(
        """SELECT u.user_id, u.name, u.email, u.password_hash, r.name AS role
           FROM users u JOIN roles r ON r.role_id = u.role_id
           WHERE lower(u.email) = lower(%s)""",
        (body.email,),
    )
    # Always run one hash check, so an unknown email and a wrong password take the same time.
    stored = (user or {}).get("password_hash") or DUMMY_HASH
    password_ok = verify_password(body.password, stored)
    if user is None or not user["password_hash"] or not password_ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return {
        "access_token": create_token(user),
        "token_type": "bearer",
        "user": {"user_id": user["user_id"], "name": user["name"], "email": user["email"], "role": user["role"]},
    }


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return user
