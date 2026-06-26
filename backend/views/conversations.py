"""views/conversations.py — /api/conversations/* routes."""

from fastapi import APIRouter, Depends

from controllers   import conversation as conv_ctrl
from core.security import get_current_user

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(user_id: str = Depends(get_current_user)):
    return conv_ctrl.list_conversations(user_id)
