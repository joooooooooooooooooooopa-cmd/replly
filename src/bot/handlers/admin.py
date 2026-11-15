"""
Админ-панель Replly для владельца платформы.
Доступ только ADMIN_IDS.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger
from sqlalchemy import func, select

from config import settings
from src.db.database import get_session
from src.db.models import (
    Business, BizStatus, Plan,
    Dialogue, DialogueStatus,
    Lead, LeadStatus,
    Message as DbMessage,
)

router = Router(name="admin")


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _is_admin(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS


# ── Главная админка ─────────────────────────────────────────────────


@router.message(F.text == "🔐 Админ панель")
@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    async with get_session() as session:
        total_biz = (await session.execute(
            select(func.count()).select_from(Business)
        )).scalar() or 0

        active_biz = (await session.execute(
            select(func.count()).select_from(Business)
            .where(Business.status == BizStatus.ACTIVE)
        )).scalar() or 0

        paused_biz = (await session.execute(
            select(func.count()).select_from(Business)
            .where(Business.status == BizStatus.PAUSED)
        )).scalar() or 0

        trial_biz = (await session.execute(
            select(func.count()).select_from(Business)
            .where(Business.status == BizStatus.TRIAL)
        )).scalar() or 0

        total_dialogues = (await session.execute(
            select(func.count()).select_from(Dialogue)
        )).scalar() or 0

        total_messages = (await session.execute(
            select(func.count()).select_from(DbMessage)
        )).scalar() or 0

        total_leads = (await session.execute(
            select(func.count()).select_from(Lead)
        )).scalar() or 0

        # Подсчёт по тарифам
        plan_rows = (await session.execute(
            select(Business.plan, func.count())
            .where(Business.status == BizStatus.ACTIVE)
            .group_by(Business.plan)
        )).all()

    plan_names = {
        Plan.FREE: "Free", Plan.START: "Старт (500⭐)",
        Plan.BUSINESS: "Бизнес (850⭐)", Plan.PRO: "Про (2500⭐)",
    }

    # Считаем доход
    stars_earned = 0
    for plan_val, cnt in plan_rows:
        price = {Plan.START: 500, Plan.BUSINESS: 850, Plan.PRO: 2500}.get(plan_val, 0)
        stars_earned += price * cnt

    plan_lines = ""
    for plan_val, cnt in plan_rows:
        plan_lines += f"  {plan_names.get(plan_val, plan_val.value)}: <b>{cnt}</b>\n"
    if not plan_lines:
        plan_lines = "  Нет оплаченных\n"

    text = (
        f"🔐 <b>ADMIN PANEL — Replly</b>\n"
        f"{'━' * 28}\n\n"
        f"🏢 <b>Бизнесы:</b>\n"
        f"  Всего: <b>{total_biz}</b>\n"
        f"  ✅ Активных: <b>{active_biz}</b>\n"
        f"  ⏸ Ожидают оплату: <b>{paused_biz}</b>\n"
        f"  🆓 Триал: <b>{trial_biz}</b>\n\n"
        f"💰 <b>Доход:</b>\n"
        f"  ⭐ Stars заработано: <b>{stars_earned}</b>\n"
        f"{plan_lines}\n"
        f"📊 <b>Активность:</b>\n"
        f"  💬 Диалогов: <b>{total_dialogues}</b>\n"
        f"  📨 Сообщений: <b>{total_messages}</b>\n"
        f"  🎯 Заявок: <b>{total_leads}</b>\n"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список бизнесов", callback_data="adm:biz_list:1")],
        [InlineKeyboardButton(text="🎯 Последние заявки", callback_data="adm:leads")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:refresh")],
    ])

    await message.answer(text, parse_mode="HTML", reply_markup=kb)


# ── Список бизнесов ─────────────────────────────────────────────────


@router.callback_query(F.data.startswith("adm:biz_list:"))
async def cb_biz_list(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        return

    page = int(callback.data.split(":")[2])
    per_page = 5

    async with get_session() as session:
        total = (await session.execute(
            select(func.count()).select_from(Business)
        )).scalar() or 0

        stmt = (
            select(Business)
            .order_by(Business.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        businesses = (await session.execute(stmt)).scalars().all()

    if not businesses:
        await callback.message.edit_text("📋 Нет бизнесов.")
        await callback.answer()
        return

    total_pages = max(1, (total + per_page - 1) // per_page)
    status_icons = {"active": "✅", "paused": "⏸", "trial": "🆓", "blocked": "🚫"}
    plan_names = {"free": "Free", "start": "Старт", "business": "Бизнес", "pro": "Про"}

    text = f"📋 <b>Бизнесы</b> — стр. {page}/{total_pages}\n\n"

    for biz in businesses:
        icon = status_icons.get(biz.status.value, "")
        plan = plan_names.get(biz.plan.value, biz.plan.value)
        text += (
            f"{icon} <b>{_esc(biz.name)}</b> (#{biz.id})\n"
            f"   👤 {biz.owner_name} | 📦 {plan}\n"
            f"   📅 {biz.created_at:%d.%m.%Y}\n\n"
        )

    buttons = []
    for biz in businesses:
        buttons.append([InlineKeyboardButton(
            text=f"📊 {biz.name}",
            callback_data=f"adm:biz_detail:{biz.id}",
        )])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm:biz_list:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="adm:noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm:biz_list:{page+1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="← Назад", callback_data="adm:refresh")])

    try:
        await callback.message.edit_text(text, parse_mode="HTML",
                                         reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except Exception:
        await callback.message.answer(text, parse_mode="HTML",
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


# ── Детали бизнеса ───────────────────────────────────────────────────


async def _show_biz_detail(message: Message, biz_id: int) -> None:
    """Показать детали бизнеса."""
    async with get_session() as session:
        biz = await session.get(Business, biz_id)
        if not biz:
            await message.answer("Не найден.")
            return

        dialogues = (await session.execute(
            select(func.count()).select_from(Dialogue).where(Dialogue.business_id == biz_id)
        )).scalar() or 0

        messages = (await session.execute(
            select(func.count()).select_from(DbMessage)
            .join(Dialogue).where(Dialogue.business_id == biz_id)
        )).scalar() or 0

        leads = (await session.execute(
            select(func.count()).select_from(Lead).where(Lead.business_id == biz_id)
        )).scalar() or 0

    status_icons = {"active": "✅", "paused": "⏸", "trial": "🆓", "blocked": "🚫"}
    plan_names = {"free": "Free", "start": "Старт", "business": "Бизнес", "pro": "Про"}

    text = (
        f"🏢 <b>{_esc(biz.name)}</b> (#{biz.id})\n"
        f"{'━' * 28}\n\n"
        f"👤 Владелец: {_esc(biz.owner_name)} (ID: {biz.owner_tg_id})\n"
        f"📦 Тариф: {plan_names.get(biz.plan.value, biz.plan.value)}\n"
        f"{status_icons.get(biz.status.value, '')} Статус: {biz.status.value}\n"
        f"📅 Создан: {biz.created_at:%d.%m.%Y %H:%M}\n\n"
        f"📂 Категория: {_esc(biz.category or '—')}\n"
        f"📱 Телефон: {_esc(biz.phone or '—')}\n"
        f"📍 Адрес: {_esc(biz.address or '—')}\n"
        f"🌐 Сайт: {_esc(biz.website or '—')}\n"
        f"🎭 Тон: {biz.tone}\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"  💬 Диалогов: {dialogues}\n"
        f"  📨 Сообщений: {messages}\n"
        f"  🎯 Заявок: {leads}\n\n"
        f"📝 База знаний: {len(biz.knowledge_base or '')} символов\n"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Активировать", callback_data=f"adm:activate:{biz_id}"),
            InlineKeyboardButton(text="⏸ Пауза", callback_data=f"adm:pause:{biz_id}"),
        ],
        [InlineKeyboardButton(text="← Назад к списку", callback_data="adm:biz_list:1")],
    ])

    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("adm:biz_detail:"))
async def cb_biz_detail(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        return
    biz_id = int(callback.data.split(":")[2])
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _show_biz_detail(callback.message, biz_id)
    await callback.answer()


# ── Активация/Пауза бизнеса ─────────────────────────────────────────


@router.callback_query(F.data.startswith("adm:activate:"))
async def cb_activate(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        return

    biz_id = int(callback.data.split(":")[2])
    async with get_session() as session:
        biz = await session.get(Business, biz_id)
        if biz:
            biz.status = BizStatus.ACTIVE
            if biz.plan == Plan.FREE:
                biz.plan = Plan.START

    await callback.answer("✅ Активирован!", show_alert=True)
    # Обновляем детали через edit
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _show_biz_detail(callback.message, biz_id)


@router.callback_query(F.data.startswith("adm:pause:"))
async def cb_pause(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        return

    biz_id = int(callback.data.split(":")[2])
    async with get_session() as session:
        biz = await session.get(Business, biz_id)
        if biz:
            biz.status = BizStatus.PAUSED

    await callback.answer("⏸ На паузе", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _show_biz_detail(callback.message, biz_id)


# ── Последние заявки ─────────────────────────────────────────────────


@router.callback_query(F.data == "adm:leads")
async def cb_leads(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        return

    async with get_session() as session:
        stmt = (
            select(Lead, Business.name)
            .join(Business, Lead.business_id == Business.id)
            .order_by(Lead.created_at.desc())
            .limit(10)
        )
        rows = (await session.execute(stmt)).all()

    if not rows:
        await callback.message.edit_text("🎯 Заявок пока нет.")
        await callback.answer()
        return

    text = "🎯 <b>Последние 10 заявок</b>\n\n"
    for lead, biz_name in rows:
        text += (
            f"• <b>{_esc(lead.client_name or 'Аноним')}</b>\n"
            f"  📱 {_esc(lead.client_phone or '—')} | 🏢 {_esc(biz_name)}\n"
            f"  📝 {_esc((lead.request or '—')[:50])}\n"
            f"  📅 {lead.created_at:%d.%m %H:%M}\n\n"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="← Назад", callback_data="adm:refresh")],
    ])

    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ── Обновить ─────────────────────────────────────────────────────────


@router.callback_query(F.data == "adm:refresh")
async def cb_refresh(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        return
    # Удаляем старое сообщение и шлём новое
    try:
        await callback.message.delete()
    except Exception:
        pass
    # Фейковый message для cmd_admin
    await cmd_admin(callback.message)
    await callback.answer()


@router.callback_query(F.data == "adm:noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()
