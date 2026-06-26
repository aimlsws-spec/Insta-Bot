"""views/broadcasts.py — /api/broadcasts/* routes."""

from fastapi import APIRouter, Depends

from views.schemas import BroadcastMessage
from controllers   import broadcast as broadcast_ctrl
from core.security import get_current_user

router = APIRouter(prefix="/api/broadcasts", tags=["broadcasts"])


@router.post("")
async def create(broadcast: BroadcastMessage, user_id: str = Depends(get_current_user)):
    return broadcast_ctrl.create(
        user_id, broadcast.name, broadcast.content, broadcast.target_tags, broadcast.schedule_time,
    )


@router.get("")
async def list_broadcasts(user_id: str = Depends(get_current_user)):
    return broadcast_ctrl.list_broadcasts(user_id)


@router.delete("/{broadcast_id}")
async def delete(broadcast_id: str, user_id: str = Depends(get_current_user)):
    return broadcast_ctrl.delete(broadcast_id, user_id)
