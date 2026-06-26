"""
views/schemas.py
Pydantic request / response schemas used by all routers.
Identical to the inline class definitions that were in main.py.
"""

from pydantic import BaseModel, EmailStr
from typing import List, Optional, Dict, Any


class UserRegister(BaseModel):
    email: EmailStr
    password: str
    name: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class InstagramAccountConnect(BaseModel):
    access_token: str
    instagram_id: str
    username: str


class BotFlow(BaseModel):
    name: str
    triggers: List[str]
    steps: List[Dict[str, Any]]
    enabled: bool = True
    reply_type: Optional[str] = "dm"
    conditions: Optional[List[Dict[str, Any]]] = []


class MessageTemplate(BaseModel):
    name: str
    content: str
    type: str = "text"
    quick_replies: Optional[List[Dict[str, str]]] = []


class BroadcastMessage(BaseModel):
    name: str
    content: str
    target_tags: Optional[List[str]] = []
    schedule_time: Optional[str] = None


class UserTag(BaseModel):
    name: str
    description: Optional[str] = ""


class SimulatedMessage(BaseModel):
    text: str
    sender_name: Optional[str] = "Test User"
    message_type: str = "dm"
