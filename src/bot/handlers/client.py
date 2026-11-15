"""
Хендлеры для клиентов бизнеса.
Клиент переходит по ссылке t.me/bot?start=biz_123 → общается с AI.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from loguru import logger
from sqlalchemy import select

from src.ai.responder import generate_response
from src.db.database import get_session
from src.db.models import (
    Business,
    BizStatus,
    Dialogue,
    DialogueStatus,
    Lead,
    Message as DbMessage,
)

router = Router(name="client")


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Deep link entry: /start biz_123 ─────────────────────────────────────


@router.message(CommandStart(deep_link=True))
async def cmd_start_client(message: Message) -> None:
    """Клиент перешёл по ссылке бизнеса."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return

    payload = args[1].strip()
    if not payload.startswith("biz_"):
        return

    try:
        biz_id = int(payload.removeprefix("biz_"))
    except ValueError:
        return

    async with get_session() as session:
        biz = await session.get(Business, biz_id)

    if not biz or biz.status == BizStatus.BLOCKED:
        await message.answer("К сожалению, этот бизнес сейчас недоступен.")
        return

    if biz.status == BizStatus.PAUSED:
        await message.answer(
            "⏸ Этот бизнес ещё не активирован.\n"
            "Если вы владелец — оплатите подписку в боте."
        )
        return

    # Создаём или находим диалог
    dialogue = await _get_or_create_dialogue(biz.id, message.from_user.id, message.from_user.full_name)

    # Отправляем приветствие
    greeting = biz.greeting or f"Здравствуйте! Это {biz.name}. Чем могу помочь?"
    await message.answer(greeting)

    # Сохраняем приветствие в историю
    async with get_session() as session:
        session.add(DbMessage(
            dialogue_id=dialogue.id,
            role="assistant",
            content=greeting,
        ))

    logger.info("[Client] New dialogue: biz={} client={}", biz.name, message.from_user.id)


# ── Handle client messages ───────────────────────────────────────────────


@router.message()
async def handle_client_message(message: Message, business: Business | None) -> None:
    """Обработка сообщений от клиентов."""
    if not message.text:
        return

    user_id = message.from_user.id

    # Ищем активный диалог этого клиента (приоритет над владельцем)
    async with get_session() as session:
        stmt = (
            select(Dialogue)
            .where(
                Dialogue.client_tg_id == user_id,
                Dialogue.status == DialogueStatus.ACTIVE,
            )
            .order_by(Dialogue.updated_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        dialogue = result.scalar_one_or_none()

    if not dialogue:
        # Нет активного диалога
        if business:
            # Это владелец — owner router обработает (не отвечаем тут)
            return
        await message.answer(
            "👋 Привет! Я — <b>Replly</b>, AI-ассистент для бизнеса.\n\n"
            "Если вы владелец бизнеса — нажмите /start чтобы создать своего бота.\n"
            "Если вы клиент — перейдите по ссылке от компании.",
            parse_mode="HTML",
        )
        return

    # Загружаем бизнес
    async with get_session() as session:
        biz = await session.get(Business, dialogue.business_id)

    if not biz or biz.status == BizStatus.BLOCKED:
        await message.answer("К сожалению, этот сервис сейчас недоступен.")
        return

    # Сохраняем сообщение клиента
    async with get_session() as session:
        session.add(DbMessage(
            dialogue_id=dialogue.id,
            role="client",
            content=message.text,
        ))

    # Загружаем историю
    async with get_session() as session:
        stmt = (
            select(DbMessage)
            .where(DbMessage.dialogue_id == dialogue.id)
            .order_by(DbMessage.created_at)
        )
        result = await session.execute(stmt)
        db_messages = result.scalars().all()

    history = [{"role": m.role, "content": m.content} for m in db_messages]

    # Генерируем ответ AI
    try:
        ai_result = await generate_response(biz, history, message.text)
    except Exception as exc:
        logger.error("[Client] AI error for biz {}: {}", biz.id, exc)
        ai_result = {"type": "text", "text": "Секунду, уточню информацию и напишу вам."}

    reply_text = ai_result.get("text", "Секунду, уточню информацию.")
    if not reply_text.strip():
        reply_text = "Секунду, уточню информацию и напишу вам."

    logger.info("[Client] AI reply for biz={}: type={} text={}...", biz.id, ai_result["type"], reply_text[:60])
    await message.answer(reply_text)

    # Сохраняем ответ AI
    async with get_session() as session:
        session.add(DbMessage(
            dialogue_id=dialogue.id,
            role="assistant",
            content=reply_text,
        ))

    # Обработка специальных действий
    if ai_result["type"] == "lead":
        await _create_lead(
            biz_id=biz.id,
            client_tg_id=user_id,
            client_name=ai_result.get("name") or message.from_user.full_name,
            phone=ai_result.get("phone"),
            request=ai_result.get("request"),
        )
        # Уведомляем владельца
        await _notify_owner(
            message.bot,
            biz.owner_tg_id,
            f"🎯 <b>Новая заявка!</b>\n\n"
            f"👤 {_esc(ai_result.get('name', 'Аноним'))}\n"
            f"📱 {_esc(ai_result.get('phone', '—'))}\n"
            f"📝 {_esc(ai_result.get('request', '—'))}",
        )

    elif ai_result["type"] == "handoff":
        async with get_session() as session:
            d = await session.get(Dialogue, dialogue.id)
            if d:
                d.status = DialogueStatus.HANDED_OFF

        await _notify_owner(
            message.bot,
            biz.owner_tg_id,
            f"🟡 <b>Клиент ждёт ответа менеджера</b>\n\n"
            f"👤 {_esc(message.from_user.full_name or 'Аноним')}\n"
            f"💬 «{_esc(message.text[:200])}»\n"
            f"❓ {_esc(ai_result.get('reason', ''))}",
        )

    logger.debug("[Client] biz={} msg={}", biz.id, message.text[:50])


# ── Helpers ──────────────────────────────────────────────────────────────


async def _get_or_create_dialogue(biz_id: int, client_tg_id: int, client_name: str | None) -> Dialogue:
    async with get_session() as session:
        stmt = (
            select(Dialogue)
            .where(
                Dialogue.business_id == biz_id,
                Dialogue.client_tg_id == client_tg_id,
                Dialogue.status == DialogueStatus.ACTIVE,
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        dialogue = result.scalar_one_or_none()

        if dialogue:
            return dialogue

        dialogue = Dialogue(
            business_id=biz_id,
            client_tg_id=client_tg_id,
            client_name=client_name,
            status=DialogueStatus.ACTIVE,
        )
        session.add(dialogue)
        await session.flush()
        return dialogue


async def _create_lead(
    biz_id: int,
    client_tg_id: int,
    client_name: str | None,
    phone: str | None,
    request: str | None,
) -> None:
    async with get_session() as session:
        session.add(Lead(
            business_id=biz_id,
            client_tg_id=client_tg_id,
            client_name=client_name,
            client_phone=phone,
            request=request,
        ))
    logger.info("[Lead] New lead for biz {}: {} {}", biz_id, client_name, phone)


async def _notify_owner(bot, owner_tg_id: int, text: str) -> None:
    try:
        await bot.send_message(owner_tg_id, text, parse_mode="HTML")
    except Exception as exc:
        logger.error("[Notify] Failed to notify owner {}: {}", owner_tg_id, exc)
