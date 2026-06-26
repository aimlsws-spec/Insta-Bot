"""views/flows.py — /api/flows/* routes."""

from fastapi import APIRouter, Depends

from views.schemas import BotFlow
from controllers   import flow as flow_ctrl
from core.security import get_current_user

router = APIRouter(prefix="/api/flows", tags=["flows"])


@router.post("")
async def create(flow: BotFlow, user_id: str = Depends(get_current_user)):
    return flow_ctrl.create(
        user_id, flow.name, flow.triggers, flow.steps,
        flow.reply_type, flow.conditions, flow.enabled,
    )


@router.get("")
async def list_flows(user_id: str = Depends(get_current_user)):
    return flow_ctrl.list_flows(user_id)


@router.delete("/{flow_id}")
async def delete(flow_id: str, user_id: str = Depends(get_current_user)):
    return flow_ctrl.delete(flow_id, user_id)
