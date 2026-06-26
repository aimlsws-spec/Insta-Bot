"""views/auth.py — /api/auth/* routes."""

from fastapi import APIRouter, Depends

from views.schemas import UserRegister, UserLogin
from controllers  import auth as auth_ctrl
from core.security import get_current_user, get_current_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
async def register(user_data: UserRegister):
    return auth_ctrl.register(user_data.email, user_data.password, user_data.name)


@router.post("/login")
async def login(login_data: UserLogin):
    return auth_ctrl.login(login_data.email, login_data.password)


@router.get("/me")
async def me(user_id: str = Depends(get_current_user)):
    return auth_ctrl.get_me(user_id)


@router.post("/logout")
async def logout(token: str = Depends(get_current_token)):
    return auth_ctrl.logout(token)
