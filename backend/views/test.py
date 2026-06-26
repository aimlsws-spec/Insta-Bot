"""views/test.py — /api/test/* routes (bot simulation endpoints)."""

from fastapi import APIRouter, Depends

from views.schemas import SimulatedMessage
from controllers   import webhook as webhook_ctrl
from core.security import get_current_user

router = APIRouter(prefix="/api/test", tags=["test"])


@router.post("/message")
async def test_message(msg: SimulatedMessage, user_id: str = Depends(get_current_user)):
    return await webhook_ctrl.handle_test_message(msg.text, user_id, msg.sender_name, msg.message_type)


@router.post("/comment")
async def test_comment(msg: SimulatedMessage, user_id: str = Depends(get_current_user)):
    return await webhook_ctrl.handle_test_comment(msg.text, user_id)
