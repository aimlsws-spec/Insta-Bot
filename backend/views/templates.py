"""views/templates.py — /api/templates/* routes."""

from fastapi import APIRouter, Depends

from views.schemas import MessageTemplate
from controllers   import template as template_ctrl
from core.security import get_current_user

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.post("")
async def create(template: MessageTemplate, user_id: str = Depends(get_current_user)):
    return template_ctrl.create(
        user_id, template.name, template.content, template.type, template.quick_replies,
    )


@router.get("")
async def list_templates(user_id: str = Depends(get_current_user)):
    return template_ctrl.list_templates(user_id)
