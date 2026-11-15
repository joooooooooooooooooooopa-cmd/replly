from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy import select

from src.db.database import get_session
from src.db.models import Business


class InjectBusinessMiddleware(BaseMiddleware):
    """Inject Business object into handler data if user is a registered owner."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user:
            async with get_session() as session:
                stmt = select(Business).where(Business.owner_tg_id == user.id).limit(1)
                result = await session.execute(stmt)
                biz = result.scalar_one_or_none()
                data["business"] = biz

        return await handler(event, data)
