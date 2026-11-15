"""Scheduler jobs для Replly — автоматические задачи."""

from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
from sqlalchemy import func, select

from config import settings
from src.db.database import get_session
from src.db.models import Business, BizStatus, Dialogue, Lead, LeadStatus


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

    # Daily summary to business owners (10:00 MSK)
    scheduler.add_job(
        daily_owner_summary,
        trigger=CronTrigger(hour=10, minute=0, timezone="Europe/Moscow"),
        kwargs={"bot": bot},
        id="daily_owner_summary",
        name="Daily summary to owners",
        replace_existing=True,
    )

    # Daily outreach report to admin (10:30 MSK)
    scheduler.add_job(
        daily_admin_report,
        trigger=CronTrigger(hour=10, minute=30, timezone="Europe/Moscow"),
        kwargs={"bot": bot},
        id="daily_admin_report",
        name="Daily admin report",
        replace_existing=True,
    )

    # Reset email quota (03:00 MSK = 00:00 UTC)
    scheduler.add_job(
        reset_quota_job,
        trigger=CronTrigger(hour=3, minute=0, timezone="Europe/Moscow"),
        id="reset_quota",
        name="Reset email quota",
        replace_existing=True,
    )

    logger.info("Scheduler configured with {} jobs", len(scheduler.get_jobs()))
    return scheduler


async def daily_owner_summary(*, bot: Bot) -> None:
    """Ежедневная сводка для каждого владельца бизнеса."""
    logger.info("daily_owner_summary: starting")
    try:
        async with get_session() as session:
            stmt = select(Business).where(
                Business.status.in_([BizStatus.ACTIVE, BizStatus.TRIAL])
            )
            result = await session.execute(stmt)
            businesses = result.scalars().all()

        now = datetime.utcnow()
        since = now - timedelta(hours=24)

        for biz in businesses:
            try:
                async with get_session() as session:
                    new_dialogues = (await session.execute(
                        select(func.count()).select_from(Dialogue)
                        .where(Dialogue.business_id == biz.id, Dialogue.created_at >= since)
                    )).scalar() or 0

                    new_leads = (await session.execute(
                        select(func.count()).select_from(Lead)
                        .where(Lead.business_id == biz.id, Lead.created_at >= since)
                    )).scalar() or 0

                    total_leads = (await session.execute(
                        select(func.count()).select_from(Lead)
                        .where(Lead.business_id == biz.id)
                    )).scalar() or 0

                if new_dialogues == 0 and new_leads == 0:
                    continue

                text = (
                    f"📊 <b>Сводка за сутки — {biz.name}</b>\n\n"
                    f"💬 Новых диалогов: <b>{new_dialogues}</b>\n"
                    f"🎯 Новых заявок: <b>{new_leads}</b>\n"
                    f"📋 Всего заявок: <b>{total_leads}</b>\n\n"
                    f"Хорошего дня! 🚀"
                )

                await bot.send_message(biz.owner_tg_id, text, parse_mode="HTML")

            except Exception as exc:
                logger.error("Summary failed for biz {}: {}", biz.id, exc)

    except Exception as exc:
        logger.error("daily_owner_summary failed: {}", exc)


async def daily_admin_report(*, bot: Bot) -> None:
    """Ежедневный отчёт для админа Replly."""
    logger.info("daily_admin_report: starting")
    try:
        async with get_session() as session:
            total_biz = (await session.execute(
                select(func.count()).select_from(Business)
            )).scalar() or 0

            active_biz = (await session.execute(
                select(func.count()).select_from(Business)
                .where(Business.status.in_([BizStatus.ACTIVE, BizStatus.TRIAL]))
            )).scalar() or 0

            total_dialogues = (await session.execute(
                select(func.count()).select_from(Dialogue)
            )).scalar() or 0

            total_leads = (await session.execute(
                select(func.count()).select_from(Lead)
            )).scalar() or 0

        text = (
            f"📊 <b>Replly — ежедневный отчёт</b>\n\n"
            f"🏢 Бизнесов: <b>{total_biz}</b> (активных: {active_biz})\n"
            f"💬 Диалогов всего: <b>{total_dialogues}</b>\n"
            f"🎯 Заявок всего: <b>{total_leads}</b>"
        )

        for admin_id in settings.ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception:
                pass

    except Exception as exc:
        logger.error("daily_admin_report failed: {}", exc)


async def reset_quota_job() -> None:
    from src.outreach.sender import reset_daily_quota
    reset_daily_quota()
