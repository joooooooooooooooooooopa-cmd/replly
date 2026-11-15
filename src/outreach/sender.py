"""Отправка email через Resend API для outreach Replly."""

import time
from collections import deque

import aiohttp
from loguru import logger

from config import settings

_MAX_PER_HOUR = 100
_WINDOW_SECONDS = 3600
RESEND_API_URL = "https://api.resend.com/emails"

_daily_quota_hit = False
_quota_hit_time = 0.0


def reset_daily_quota():
    global _daily_quota_hit, _quota_hit_time
    _daily_quota_hit = False
    _quota_hit_time = 0.0
    logger.info("Daily email quota reset")


def is_quota_hit() -> bool:
    global _daily_quota_hit, _quota_hit_time
    if _daily_quota_hit and _quota_hit_time > 0:
        if time.monotonic() - _quota_hit_time > 86400:
            _daily_quota_hit = False
            _quota_hit_time = 0.0
    return _daily_quota_hit


class EmailSender:
    def __init__(self):
        self._send_timestamps = deque()

    @staticmethod
    def has_credentials() -> bool:
        return bool(settings.RESEND_API_KEY)

    def _prune_window(self):
        cutoff = time.monotonic() - _WINDOW_SECONDS
        while self._send_timestamps and self._send_timestamps[0] < cutoff:
            self._send_timestamps.popleft()

    def _can_send(self) -> bool:
        self._prune_window()
        return len(self._send_timestamps) < _MAX_PER_HOUR

    async def send_email(self, to_email: str, subject: str, body_html: str, body_text: str) -> bool:
        global _daily_quota_hit, _quota_hit_time

        if not self.has_credentials():
            logger.warning("Resend API key not configured")
            return False
        if is_quota_hit():
            return False
        if not self._can_send():
            return False

        from_email = settings.RESEND_FROM

        payload = {
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": body_html,
            "text": body_text,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    RESEND_API_URL,
                    headers={
                        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status in (200, 201):
                        self._send_timestamps.append(time.monotonic())
                        data = await resp.json()
                        logger.info("Email sent to {} — id={}", to_email, data.get("id"))
                        return True
                    elif resp.status == 429:
                        _daily_quota_hit = True
                        _quota_hit_time = time.monotonic()
                        return False
                    else:
                        error = await resp.text()
                        logger.error("Resend error {}: {}", resp.status, error[:200])
                        return False
        except Exception as exc:
            logger.error("Error sending email to {}: {}", to_email, exc)
            return False
