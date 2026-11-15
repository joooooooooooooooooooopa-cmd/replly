"""
Хендлеры для владельцев бизнеса.
Регистрация → настройка → управление.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy import func, select

from config import settings
from src.bot.keyboards import owner_main_kb, setup_category_kb, setup_tone_kb
from src.db.database import get_session
from src.db.models import (
    Business,
    BizStatus,
    Dialogue,
    DialogueStatus,
    Lead,
    LeadStatus,
    Message as DbMessage,
)

router = Router(name="owner")


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── FSM ──────────────────────────────────────────────────────────────────


class SetupFSM(StatesGroup):
    name = State()
    category = State()
    website = State()
    description = State()
    phone = State()
    address = State()
    hours = State()
    knowledge = State()
    tone = State()


class EditKBFSM(StatesGroup):
    waiting_text = State()


# ── /start — landing + registration ─────────────────────────────────────


@router.message(CommandStart(deep_link=False))
async def cmd_start_owner(message: Message, state: FSMContext, business: Business | None) -> None:
    """Владелец бизнеса нажал /start (без deep link)."""
    if business:
        status_icons = {"active": "🟢", "paused": "🔴", "trial": "🟡", "blocked": "⛔"}
        plan_names = {"free": "Бесплатный", "start": "Старт", "business": "Бизнес", "pro": "Про"}
        icon = status_icons.get(business.status.value, "")

        expires_text = ""
        if business.trial_ends_at:
            days_left = (business.trial_ends_at - datetime.utcnow()).days
            if days_left > 0:
                expires_text = f"⏰ Подписка до: {business.trial_ends_at:%d.%m.%Y} ({days_left} дн.)\n"
            else:
                expires_text = "⚠️ Подписка истекла — продлите в 💳\n"

        await message.answer(
            f"{'━' * 28}\n"
            f"  🏢 <b>{_esc(business.name)}</b>\n"
            f"{'━' * 28}\n\n"
            f"{icon} Статус: <b>{business.status.value}</b>\n"
            f"📦 Тариф: <b>{plan_names.get(business.plan.value, '—')}</b>\n"
            f"{expires_text}\n"
            f"<b>Меню:</b>\n"
            f"📊 Статистика — диалоги, заявки\n"
            f"💬 Диалоги — последние разговоры\n"
            f"📝 База знаний — обновить прайс\n"
            f"🔗 Моя ссылка — для клиентов\n"
            f"💳 Подписка — тарифы и оплата\n"
            f"⏸ Остановить — поставить на паузу\n\n"
            f"💬 Поддержка: @{settings.SUPPORT_USERNAME}",
            parse_mode="HTML",
            reply_markup=owner_main_kb(is_admin=message.from_user.id in settings.ADMIN_IDS),
        )
        return

    await message.answer(
        f"{'━' * 28}\n"
        f"  <b>Replly</b> — AI-сотрудник\n"
        f"  для вашего бизнеса\n"
        f"{'━' * 28}\n\n"
        f"Что умеет бот:\n\n"
        f"⚡ Отвечает клиентам за <b>5 секунд</b>\n"
        f"🧠 Знает ваши цены, услуги, адрес\n"
        f"🎯 Собирает заявки (имя + телефон)\n"
        f"🔔 Уведомляет вас о новых клиентах\n"
        f"📊 Показывает статистику\n\n"
        f"Настройка займёт <b>5 минут</b>.\n"
        f"Первые <b>24 часа бесплатно</b>.\n\n"
        f"Начнём? Как называется ваш бизнес?",
        parse_mode="HTML",
    )
    await state.set_state(SetupFSM.name)


# ── Setup flow ───────────────────────────────────────────────────────────


@router.message(SetupFSM.name)
async def fsm_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if len(name) < 2 or len(name) > 200:
        await message.answer("Название должно быть от 2 до 200 символов. Попробуйте ещё:")
        return

    await state.update_data(name=name)
    await message.answer(
        f"👍 <b>{_esc(name)}</b> — отличное название!\n\n"
        "Выберите категорию бизнеса:",
        parse_mode="HTML",
        reply_markup=setup_category_kb(),
    )
    await state.set_state(SetupFSM.category)


@router.callback_query(SetupFSM.category, F.data.startswith("cat:"))
async def fsm_category(callback: CallbackQuery, state: FSMContext) -> None:
    cat_map = {
        "beauty": "Салон красоты",
        "clinic": "Клиника/Стоматология",
        "auto": "Автосервис",
        "food": "Доставка еды",
        "fitness": "Фитнес",
        "repair": "Ремонт/Сервис",
        "shop": "Магазин",
        "education": "Образование",
        "realty": "Недвижимость",
        "other": "Другое",
    }
    cat_key = callback.data.split(":")[1]
    category = cat_map.get(cat_key, "Другое")
    await state.update_data(category=category)

    await callback.message.edit_text(
        f"✅ Категория: <b>{category}</b>\n\n"
        "🌐 У вас есть сайт? Отправьте ссылку — бот сам прочитает информацию.\n"
        "Например: mycompany.ru\n\n"
        "/skip — пропустить",
        parse_mode="HTML",
    )
    await state.set_state(SetupFSM.website)
    await callback.answer()


@router.message(SetupFSM.website)
async def fsm_website(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    website = None
    auto_kb = None

    if text != "/skip" and text:
        website = text if text.startswith("http") else f"https://{text}"
        await state.update_data(website=website)

        # Пробуем спарсить сайт
        await message.answer("⏳ Читаю информацию с сайта...")
        try:
            import aiohttp, re
            headers = {"User-Agent": "Mozilla/5.0"}
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession() as session:
                async with session.get(website, headers=headers, timeout=timeout, ssl=False, allow_redirects=True) as resp:
                    if resp.status == 200:
                        html = await resp.text(errors="replace")
                        # Убираем теги
                        clean = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
                        clean = re.sub(r"<style[^>]*>.*?</style>", "", clean, flags=re.DOTALL)
                        clean = re.sub(r"<[^>]+>", " ", clean)
                        clean = re.sub(r"\s+", " ", clean).strip()[:3000]
                        if len(clean) > 100:
                            auto_kb = clean
                            await message.answer(
                                f"✅ Прочитал сайт! Нашёл {len(clean)} символов информации.\n"
                                "Бот будет использовать это как базу знаний.\n\n"
                                "Хотите дополнить? Отправьте текст.\n"
                                "Или /skip — оставить как есть.",
                            )
                            await state.update_data(auto_knowledge=auto_kb)
        except Exception as exc:
            logger.debug("Auto-scrape failed for {}: {}", website, exc)

    if not auto_kb:
        await state.update_data(website=website)

    await message.answer(
        "Теперь кратко опишите чем занимается ваш бизнес.\n"
        "Например: «Барбершоп в центре Москвы, мужские стрижки и бороды»\n\n"
        "/skip — пропустить",
    )
    await state.set_state(SetupFSM.description)


@router.message(SetupFSM.description)
async def fsm_description(message: Message, state: FSMContext) -> None:
    desc = None if message.text.strip() == "/skip" else message.text.strip()
    await state.update_data(description=desc)
    await message.answer(
        "📱 Телефон для клиентов?\n"
        "Например: +7 999 123-45-67\n\n"
        "/skip — пропустить",
    )
    await state.set_state(SetupFSM.phone)


@router.message(SetupFSM.phone)
async def fsm_phone(message: Message, state: FSMContext) -> None:
    phone = None if message.text.strip() == "/skip" else message.text.strip()
    await state.update_data(phone=phone)
    await message.answer(
        "📍 Адрес?\n"
        "Например: Москва, ул. Тверская 10\n\n"
        "/skip — пропустить",
    )
    await state.set_state(SetupFSM.address)


@router.message(SetupFSM.address)
async def fsm_address(message: Message, state: FSMContext) -> None:
    address = None if message.text.strip() == "/skip" else message.text.strip()
    await state.update_data(address=address)
    await message.answer(
        "🕐 Режим работы?\n"
        "Например: Пн-Пт 10:00-20:00, Сб 10:00-18:00\n\n"
        "/skip — пропустить",
    )
    await state.set_state(SetupFSM.hours)


@router.message(SetupFSM.hours)
async def fsm_hours(message: Message, state: FSMContext) -> None:
    hours = None if message.text.strip() == "/skip" else message.text.strip()
    await state.update_data(hours=hours)
    await message.answer(
        "📋 <b>База знаний</b> — самое важное!\n\n"
        "Отправьте одним сообщением всё что бот должен знать:\n"
        "• Список услуг и цены\n"
        "• Часто задаваемые вопросы\n"
        "• Акции и спецпредложения\n"
        "• Любая важная информация\n\n"
        "💡 Можно скопировать с сайта или прайс-листа.\n"
        f"Максимум {settings.MAX_KNOWLEDGE_BASE_SIZE} символов.",
        parse_mode="HTML",
    )
    await state.set_state(SetupFSM.knowledge)


@router.message(SetupFSM.knowledge)
async def fsm_knowledge(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    auto_kb = data.get("auto_knowledge", "")

    if message.text.strip() == "/skip" and auto_kb:
        # Используем авто-парсинг с сайта
        await state.update_data(knowledge=auto_kb)
    elif message.text.strip() == "/skip":
        await state.update_data(knowledge=None)
    else:
        kb_text = message.text.strip()
        if len(kb_text) > settings.MAX_KNOWLEDGE_BASE_SIZE:
            await message.answer(
                f"⚠️ Слишком длинный текст ({len(kb_text)} симв.).\n"
                f"Максимум: {settings.MAX_KNOWLEDGE_BASE_SIZE}. Сократите и отправьте ещё раз."
            )
            return
        # Комбинируем с авто-парсингом
        combined = f"{auto_kb}\n\n{kb_text}" if auto_kb else kb_text
        await state.update_data(knowledge=combined[:settings.MAX_KNOWLEDGE_BASE_SIZE])
    await message.answer(
        "🎭 Последний шаг — тон общения бота:\n",
        reply_markup=setup_tone_kb(),
    )
    await state.set_state(SetupFSM.tone)


@router.callback_query(SetupFSM.tone, F.data.startswith("tone:"))
async def fsm_tone(callback: CallbackQuery, state: FSMContext) -> None:
    tone = callback.data.split(":")[1]
    data = await state.get_data()
    await state.clear()

    # Создаём бизнес
    user = callback.from_user
    trial_end = datetime.utcnow() + timedelta(days=settings.FREE_TRIAL_DAYS)

    async with get_session() as session:
        biz = Business(
            owner_tg_id=user.id,
            owner_name=user.full_name or "",
            name=data["name"],
            category=data.get("category"),
            description=data.get("description"),
            phone=data.get("phone"),
            address=data.get("address"),
            working_hours=data.get("hours"),
            website=data.get("website"),
            knowledge_base=data.get("knowledge"),
            tone=tone,
            greeting=f"Здравствуйте! Это {data['name']}. Чем могу помочь?",
            status=BizStatus.PAUSED,  # paused until payment
        )
        session.add(biz)
        await session.flush()
        biz_id = biz.id

    bot_info = await callback.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=biz_{biz_id}"

    await callback.message.edit_text(
        f"🎉 <b>Ваш AI-ассистент настроен!</b>\n\n"
        f"🏢 <b>{_esc(data['name'])}</b>\n\n"
        f"Для активации выберите тариф и оплатите подписку.\n"
        f"После оплаты бот начнёт отвечать клиентам мгновенно.\n\n"
        f"🔗 Ваша ссылка (заработает после оплаты):\n"
        f"<code>{link}</code>\n\n"
        f"💡 Посмотрите демо: <a href='{settings.SITE_URL}'>{settings.SITE_URL}</a>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    # Предлагаем оплату
    from src.bot.keyboards import payment_kb
    await callback.message.answer(
        "💳 <b>Выберите тариф:</b>\n\n"
        f"⭐ <b>Старт</b> — {settings.STARS_PRICE_START} Stars/мес\n"
        f"   Telegram бот, AI 24/7, заявки, 500 сообщ.\n\n"
        f"⭐ <b>Бизнес</b> — {settings.STARS_PRICE_BUSINESS} Stars/мес\n"
        f"   TG + VK, безлимит, аналитика, приоритет\n\n"
        f"⭐ <b>Про</b> — {settings.STARS_PRICE_PRO} Stars/мес\n"
        f"   Всё + Instagram, менеджер, кастомизация\n",
        parse_mode="HTML",
        reply_markup=payment_kb(),
    )

    await callback.message.answer(
        "Меню управления 👇",
        reply_markup=owner_main_kb(is_admin=message.from_user.id in settings.ADMIN_IDS),
    )
    await callback.answer()
    logger.info("New business registered: {} (id={})", data["name"], biz_id)


# ── Owner menu handlers ─────────────────────────────────────────────────


@router.message(F.text == "🔗 Моя ссылка")
async def btn_my_link(message: Message, business: Business | None) -> None:
    if not business:
        await message.answer("Сначала зарегистрируйте бизнес: /start")
        return

    bot_info = await message.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=biz_{business.id}"

    await message.answer(
        f"🔗 <b>Ссылка для клиентов</b>\n"
        f"{'━' * 28}\n\n"
        f"<code>{link}</code>\n\n"
        f"👆 Нажмите чтобы скопировать\n\n"
        f"<b>Где разместить:</b>\n"
        f"• Шапка Instagram / VK\n"
        f"• Кнопка на сайте\n"
        f"• QR-код на визитке / меню\n"
        f"• Рекламные объявления\n"
        f"• Подпись в email\n\n"
        f"Клиент нажмёт → напишет → получит ответ за 5 секунд ⚡",
        parse_mode="HTML",
    )


@router.message(F.text == "📊 Статистика")
async def btn_stats(message: Message, business: Business | None) -> None:
    if not business:
        await message.answer("Сначала зарегистрируйте бизнес: /start")
        return

    async with get_session() as session:
        total_dialogues = (await session.execute(
            select(func.count()).select_from(Dialogue).where(Dialogue.business_id == business.id)
        )).scalar() or 0

        active_dialogues = (await session.execute(
            select(func.count()).select_from(Dialogue).where(
                Dialogue.business_id == business.id,
                Dialogue.status == DialogueStatus.ACTIVE,
            )
        )).scalar() or 0

        total_messages = (await session.execute(
            select(func.count()).select_from(DbMessage)
            .join(Dialogue)
            .where(Dialogue.business_id == business.id)
        )).scalar() or 0

        total_leads = (await session.execute(
            select(func.count()).select_from(Lead).where(Lead.business_id == business.id)
        )).scalar() or 0

        new_leads = (await session.execute(
            select(func.count()).select_from(Lead).where(
                Lead.business_id == business.id,
                Lead.status == LeadStatus.NEW,
            )
        )).scalar() or 0

    # Конверсия
    conv = f"{(total_leads / total_dialogues * 100):.0f}%" if total_dialogues > 0 else "—"

    await message.answer(
        f"📊 <b>{_esc(business.name)}</b>\n"
        f"{'━' * 28}\n\n"
        f"<b>Диалоги</b>\n"
        f"  💬 Всего: <b>{total_dialogues}</b>\n"
        f"  🟢 Активных: <b>{active_dialogues}</b>\n"
        f"  📨 Сообщений: <b>{total_messages}</b>\n\n"
        f"<b>Заявки</b>\n"
        f"  🎯 Всего: <b>{total_leads}</b>\n"
        f"  🆕 Новых: <b>{new_leads}</b>\n"
        f"  📈 Конверсия: <b>{conv}</b>\n\n"
        f"<b>Совет:</b> чем подробнее база знаний (📝) — тем точнее ответы бота и больше заявок.",
        parse_mode="HTML",
    )


@router.message(F.text == "💬 Диалоги")
async def btn_dialogues(message: Message, business: Business | None) -> None:
    if not business:
        await message.answer("Сначала зарегистрируйте бизнес: /start")
        return

    async with get_session() as session:
        stmt = (
            select(Dialogue)
            .where(Dialogue.business_id == business.id)
            .order_by(Dialogue.updated_at.desc())
            .limit(10)
        )
        result = await session.execute(stmt)
        dialogues = result.scalars().all()

    if not dialogues:
        await message.answer(
            "💬 <b>Пока нет диалогов</b>\n\n"
            "Поделитесь ссылкой (🔗) с клиентами — они начнут писать, бот начнёт отвечать.",
        parse_mode="HTML",
        )
        return

    status_icon = {"active": "🟢", "handed_off": "🟡", "closed": "⚪"}
    lines = [
        f"💬 <b>Последние диалоги</b>\n"
        f"{'━' * 28}\n"
    ]
    for d in dialogues:
        icon = status_icon.get(d.status.value, "")
        name = _esc(d.client_name or "Аноним")
        status_text = {"active": "активен", "handed_off": "ждёт вас", "closed": "завершён"}
        st = status_text.get(d.status.value, d.status.value)
        lines.append(f"{icon} <b>{name}</b> · {st} · {d.created_at:%d.%m %H:%M}")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(F.text == "📝 База знаний")
async def btn_knowledge(message: Message, state: FSMContext, business: Business | None) -> None:
    if not business:
        await message.answer("Сначала зарегистрируйте бизнес: /start")
        return

    kb_preview = (business.knowledge_base or "Не заполнена")[:500]
    await message.answer(
        f"📝 <b>База знаний</b>\n\n"
        f"<code>{_esc(kb_preview)}</code>\n\n"
        f"Отправьте новый текст чтобы обновить, или /cancel для отмены.",
        parse_mode="HTML",
    )
    await state.set_state(EditKBFSM.waiting_text)


@router.message(EditKBFSM.waiting_text, Command("cancel"))
async def fsm_kb_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Отменено.", reply_markup=owner_main_kb(is_admin=message.from_user.id in settings.ADMIN_IDS))


@router.message(EditKBFSM.waiting_text)
async def fsm_kb_update(message: Message, state: FSMContext, business: Business | None) -> None:
    await state.clear()
    if not business:
        return

    new_kb = message.text.strip()
    if len(new_kb) > settings.MAX_KNOWLEDGE_BASE_SIZE:
        await message.answer(
            f"⚠️ Слишком длинный текст ({len(new_kb)} симв.). Максимум: {settings.MAX_KNOWLEDGE_BASE_SIZE}."
        )
        return

    async with get_session() as session:
        biz = await session.get(Business, business.id)
        if biz:
            biz.knowledge_base = new_kb

    await message.answer(
        "✅ База знаний обновлена! Бот сразу начнёт использовать новые данные.",
        reply_markup=owner_main_kb(is_admin=message.from_user.id in settings.ADMIN_IDS),
    )
    logger.info("Knowledge base updated for biz {}", business.id)


@router.message(F.text == "⚙️ Настройки")
async def btn_settings(message: Message, business: Business | None) -> None:
    if not business:
        await message.answer("Сначала зарегистрируйте бизнес: /start")
        return

    trial_info = ""
    if business.trial_ends_at:
        days_left = (business.trial_ends_at - datetime.utcnow()).days
        if days_left > 0:
            trial_info = f"\n🆓 Пробный период: <b>{days_left} дней</b>"
        else:
            trial_info = "\n⚠️ Пробный период истёк"

    await message.answer(
        f"⚙️ <b>Настройки — {_esc(business.name)}</b>\n"
        f"{'━' * 24}\n\n"
        f"📂 Категория: {_esc(business.category or '—')}\n"
        f"📱 Телефон: {_esc(business.phone or '—')}\n"
        f"📍 Адрес: {_esc(business.address or '—')}\n"
        f"🕐 Часы: {_esc(business.working_hours or '—')}\n"
        f"🎭 Тон: {business.tone}\n"
        f"{trial_info}\n\n"
        f"Для изменения напишите в поддержку: @{settings.SUPPORT_USERNAME}",
        parse_mode="HTML",
    )


@router.message(F.text == "💳 Подписка")
async def btn_subscription(message: Message, business: Business | None) -> None:
    if not business:
        await message.answer("Сначала зарегистрируйте бизнес: /start")
        return

    plan_names = {"free": "Free", "start": "Старт", "business": "Бизнес", "pro": "Про"}
    status_icons = {"active": "✅", "paused": "⏸", "trial": "🆓"}

    expires = ""
    if business.trial_ends_at:
        days_left = (business.trial_ends_at - datetime.utcnow()).days
        if days_left > 0:
            expires = f"\n⏰ Активна до: <b>{business.trial_ends_at:%d.%m.%Y}</b> ({days_left} дн.)"
        else:
            expires = "\n⚠️ Подписка истекла"

    from src.bot.handlers.payment import payment_kb
    await message.answer(
        f"💳 <b>Подписка — {_esc(business.name)}</b>\n\n"
        f"{status_icons.get(business.status.value, '')} Статус: <b>{business.status.value}</b>\n"
        f"📦 Тариф: <b>{plan_names.get(business.plan.value, business.plan.value)}</b>"
        f"{expires}\n\n"
        f"Выберите тариф для продления или смены:",
        parse_mode="HTML",
        reply_markup=payment_kb(),
    )


@router.message(F.text == "⏸ Остановить бот")
async def btn_stop_bot(message: Message, business: Business | None) -> None:
    if not business:
        await message.answer("Сначала зарегистрируйте бизнес: /start")
        return

    if business.status == BizStatus.PAUSED:
        await message.answer("Бот уже на паузе.")
        return

    from src.bot.keyboards import confirm_kb
    await message.answer(
        f"⏸ Остановить бот <b>{_esc(business.name)}</b>?\n\n"
        f"Клиенты не смогут общаться с ботом до повторной активации.",
        parse_mode="HTML",
        reply_markup=confirm_kb("stop_bot"),
    )


@router.callback_query(F.data == "confirm:stop_bot:yes")
async def cb_stop_yes(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    async with get_session() as session:
        from sqlalchemy import select as sa_select
        biz = (await session.execute(
            sa_select(Business).where(Business.owner_tg_id == user_id).limit(1)
        )).scalar_one_or_none()
        if biz:
            biz.status = BizStatus.PAUSED

    await callback.message.edit_text("⏸ Бот остановлен. Для активации оплатите подписку (💳).")
    await callback.answer()


@router.callback_query(F.data == "confirm:stop_bot:no")
async def cb_stop_no(callback: CallbackQuery) -> None:
    await callback.message.edit_text("✅ Бот продолжает работать.")
    await callback.answer()


@router.message(F.text == "❓ Помощь")
async def btn_help(message: Message) -> None:
    await message.answer(
        f"{'━' * 28}\n"
        f"  ❓ <b>Как работает Replly</b>\n"
        f"{'━' * 28}\n\n"
        f"<b>Шаг 1.</b> Вы регистрируете бизнес ✅\n"
        f"<b>Шаг 2.</b> Загружаете прайс / FAQ (📝)\n"
        f"<b>Шаг 3.</b> Получаете ссылку (🔗)\n"
        f"<b>Шаг 4.</b> Размещаете в Instagram, VK, на сайте\n"
        f"<b>Шаг 5.</b> Клиент пишет → бот отвечает за 5 сек\n"
        f"<b>Шаг 6.</b> Вам приходит заявка с именем и телефоном\n\n"
        f"<b>Кнопки меню:</b>\n"
        f"📊 Статистика — диалоги, заявки, конверсия\n"
        f"💬 Диалоги — последние разговоры с клиентами\n"
        f"📝 База знаний — обновить прайс/услуги/FAQ\n"
        f"🔗 Моя ссылка — ссылка для клиентов\n"
        f"💳 Подписка — тарифы и оплата\n"
        f"⏸ Остановить — временно отключить бот\n"
        f"⚙️ Настройки — данные бизнеса\n\n"
        f"💬 Поддержка: @{settings.SUPPORT_USERNAME}\n"
        f"🌐 Сайт: {settings.SITE_URL}",
        parse_mode="HTML",
    )
