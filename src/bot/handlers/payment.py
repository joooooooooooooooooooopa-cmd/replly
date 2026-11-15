"""
Telegram Stars оплата подписки.
Периоды: неделя / месяц / год.
"""

from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
from loguru import logger
from sqlalchemy import select

from config import settings
from src.db.database import get_session
from src.db.models import Business, BizStatus, Plan

router = Router(name="payment")

# Цены: plan_period → (title, description, stars, days, plan)
PRICES = {
    "start_week":  ("Старт — неделя",  "AI-бот TG, 500 сообщ/мес",         150,  7,   Plan.START),
    "start_month": ("Старт — месяц",   "AI-бот TG, 500 сообщ/мес",         500,  30,  Plan.START),
    "start_year":  ("Старт — год",      "AI-бот TG, 500 сообщ/мес (-20%)",  4800, 365, Plan.START),
    "biz_week":    ("Бизнес — неделя",  "TG+VK, безлимит, аналитика",       250,  7,   Plan.BUSINESS),
    "biz_month":   ("Бизнес — месяц",   "TG+VK, безлимит, аналитика",       850,  30,  Plan.BUSINESS),
    "biz_year":    ("Бизнес — год",      "TG+VK, безлимит (-20%)",           8200, 365, Plan.BUSINESS),
    "pro_week":    ("Про — неделя",     "Всё + Instagram, менеджер",         700,  7,   Plan.PRO),
    "pro_month":   ("Про — месяц",      "Всё + Instagram, менеджер",         2500, 30,  Plan.PRO),
    "pro_year":    ("Про — год",         "Всё + менеджер (-20%)",             24000,365, Plan.PRO),
}


def payment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="── Старт ──", callback_data="pay:noop")],
        [
            InlineKeyboardButton(text="150⭐ нед", callback_data="pay:start_week"),
            InlineKeyboardButton(text="500⭐ мес", callback_data="pay:start_month"),
            InlineKeyboardButton(text="4800⭐ год", callback_data="pay:start_year"),
        ],
        [InlineKeyboardButton(text="── Бизнес ──", callback_data="pay:noop")],
        [
            InlineKeyboardButton(text="250⭐ нед", callback_data="pay:biz_week"),
            InlineKeyboardButton(text="850⭐ мес", callback_data="pay:biz_month"),
            InlineKeyboardButton(text="8200⭐ год", callback_data="pay:biz_year"),
        ],
        [InlineKeyboardButton(text="── Про ──", callback_data="pay:noop")],
        [
            InlineKeyboardButton(text="700⭐ нед", callback_data="pay:pro_week"),
            InlineKeyboardButton(text="2500⭐ мес", callback_data="pay:pro_month"),
            InlineKeyboardButton(text="24000⭐ год", callback_data="pay:pro_year"),
        ],
    ])


@router.callback_query(F.data == "pay:noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("pay:"))
async def cb_pay(callback: CallbackQuery) -> None:
    key = callback.data.replace("pay:", "")
    if key == "noop":
        return

    cfg = PRICES.get(key)
    if not cfg:
        await callback.answer("Тариф не найден", show_alert=True)
        return

    title, desc, stars, days, plan = cfg
    prices = [LabeledPrice(label=title, amount=stars)]

    await callback.message.answer_invoice(
        title=title,
        description=f"{desc}\nПериод: {days} дней",
        payload=f"replly_{key}",
        currency="XTR",
        prices=prices,
    )
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message) -> None:
    payment = message.successful_payment
    key = payment.invoice_payload.replace("replly_", "")
    cfg = PRICES.get(key)

    if not cfg:
        await message.answer("❌ Ошибка обработки платежа.")
        return

    title, desc, stars, days, plan = cfg
    user_id = message.from_user.id
    expires = datetime.utcnow() + timedelta(days=days)

    async with get_session() as session:
        stmt = select(Business).where(Business.owner_tg_id == user_id).limit(1)
        biz = (await session.execute(stmt)).scalar_one_or_none()
        if biz:
            biz.status = BizStatus.ACTIVE
            biz.plan = plan
            biz.trial_ends_at = expires

    logger.info("Payment: user={} plan={} stars={} days={}", user_id, key, stars, days)

    from src.bot.keyboards import owner_main_kb
    bot_info = await message.bot.get_me()

    async with get_session() as session:
        stmt = select(Business).where(Business.owner_tg_id == user_id).limit(1)
        biz = (await session.execute(stmt)).scalar_one_or_none()
        biz_id = biz.id if biz else 0
        biz_name = biz.name if biz else "Ваш бизнес"

    link = f"https://t.me/{bot_info.username}?start=biz_{biz_id}"

    await message.answer(
        f"🎉 <b>Оплата прошла! {title} активирован!</b>\n\n"
        f"🏢 <b>{biz_name}</b> работает.\n"
        f"⏰ Подписка до: <b>{expires:%d.%m.%Y}</b>\n\n"
        f"🔗 <b>Ваша ссылка:</b>\n"
        f"<code>{link}</code>\n\n"
        f"Поддержка: @{settings.SUPPORT_USERNAME}",
        parse_mode="HTML",
        reply_markup=owner_main_kb(is_admin=user_id in settings.ADMIN_IDS),
    )
