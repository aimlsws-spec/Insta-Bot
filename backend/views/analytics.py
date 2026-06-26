"""views/analytics.py — /api/analytics/* routes."""

from fastapi import APIRouter, Depends

from controllers   import analytics as analytics_ctrl
from core.security import get_current_user

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("")
async def get_analytics(user_id: str = Depends(get_current_user)):
    return analytics_ctrl.get_analytics(user_id)
