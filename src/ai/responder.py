"""
AI-движок Replly.
GPT-4o-mini отвечает клиентам от имени бизнеса.
Если клиент оставляет контакт — создаёт лид.
Если не может ответить — передаёт менеджеру.
"""

from __future__ import annotations

import json
import re
from typing import Optional

import aiohttp
from loguru import logger

from config import settings
from src.db.models import Business


def _build_system_prompt(biz: Business) -> str:
    """Собирает системный промпт из данных бизнеса."""
    tone_map = {
        "friendly": "Дружелюбный, но профессиональный",
        "formal": "Строго деловой",
        "casual": "Неформальный, как друг",
    }
    tone_desc = tone_map.get(biz.tone, tone_map["friendly"])

    parts = [
        f"Ты — AI-ассистент компании «{biz.name}».",
        f"Тон общения: {tone_desc}.",
        "",
        "ПРАВИЛА:",
        "1. Отвечай КОРОТКО — 1-3 предложения. Не пиши стены текста.",
        "2. Отвечай на языке клиента (русский по умолчанию).",
        "3. Используй ТОЛЬКО информацию из базы знаний ниже. НЕ выдумывай цены, услуги, адреса.",
        "4. Если не знаешь ответ — скажи: «Уточню у менеджера и напишу вам. Можете также написать напрямую» и верни JSON.",
        "5. Если клиент хочет записаться/заказать — попроси имя и телефон, затем верни JSON.",
        "6. НЕ упоминай что ты AI/бот/ИИ. Ты — сотрудник компании.",
        "7. Будь полезным. Цель — довести клиента до записи/заказа.",
        "",
    ]

    if biz.greeting:
        parts.append(f"ПРИВЕТСТВИЕ (используй при первом сообщении клиента):\n{biz.greeting}")
        parts.append("")

    parts.append("ИНФОРМАЦИЯ О КОМПАНИИ:")
    if biz.category:
        parts.append(f"Категория: {biz.category}")
    if biz.description:
        parts.append(f"Описание: {biz.description}")
    if biz.phone:
        parts.append(f"Телефон: {biz.phone}")
    if biz.address:
        parts.append(f"Адрес: {biz.address}")
    if biz.working_hours:
        parts.append(f"Режим работы: {biz.working_hours}")
    if biz.website:
        parts.append(f"Сайт: {biz.website}")

    parts.append("")

    if biz.knowledge_base:
        parts.append("БАЗА ЗНАНИЙ (прайс, услуги, FAQ):")
        parts.append(biz.knowledge_base)
        parts.append("")

    parts.extend([
        "СПЕЦИАЛЬНЫЕ ДЕЙСТВИЯ (верни JSON вместо текста):",
        "",
        'Если клиент оставил телефон и имя для записи/заказа:',
        '→ {"action": "lead", "name": "Имя", "phone": "+7...", "request": "что хочет"}',
        "",
        'Если не можешь ответить на вопрос:',
        '→ {"action": "handoff", "reason": "причина"}',
        "",
        "В остальных случаях просто отвечай текстом.",
    ])

    return "\n".join(parts)


async def generate_response(
    biz: Business,
    message_history: list[dict],
    client_message: str,
) -> dict:
    """Генерирует ответ AI.

    Returns dict:
        {"type": "text", "text": "ответ"}
        {"type": "lead", "text": "ответ клиенту", "name": ..., "phone": ..., "request": ...}
        {"type": "handoff", "text": "ответ клиенту", "reason": ...}
    """
    if not settings.OPENAI_API_KEY:
        return {"type": "text", "text": "Менеджер скоро ответит вам!"}

    system_prompt = _build_system_prompt(biz)

    messages = [{"role": "system", "content": system_prompt}]

    # Последние 10 сообщений для контекста
    for msg in message_history[-10:]:
        role = "assistant" if msg["role"] == "assistant" else "user"
        messages.append({"role": role, "content": msg["content"]})

    messages.append({"role": "user", "content": client_message})

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.OPENAI_MODEL,
                    "messages": messages,
                    "max_tokens": 300,
                    "temperature": 0.5,
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error("[AI] OpenAI error {}: {}", resp.status, error[:200])
                    return {"type": "text", "text": "Секунду, уточню информацию и напишу вам."}

                data = await resp.json()
                content = data["choices"][0]["message"]["content"].strip()

        return _parse_response(content)

    except Exception as exc:
        logger.error("[AI] Error: {}", exc)
        return {"type": "text", "text": "Секунду, уточню информацию и напишу вам."}


def _parse_response(content: str) -> dict:
    """Парсит ответ GPT — текст или JSON action."""
    # Пробуем JSON
    if "{" in content:
        # Ищем JSON в ответе
        json_match = re.search(r'\{[^{}]+\}', content)
        if json_match:
            try:
                action = json.loads(json_match.group())
                act_type = action.get("action", "")

                # Текст до JSON — это ответ клиенту
                text_before = content[:json_match.start()].strip()
                text_after = content[json_match.end():].strip()
                reply_text = text_before or text_after

                if act_type == "lead":
                    return {
                        "type": "lead",
                        "text": reply_text or "Отлично! Записал вас, менеджер свяжется в ближайшее время.",
                        "name": action.get("name", ""),
                        "phone": action.get("phone", ""),
                        "request": action.get("request", ""),
                    }
                elif act_type == "handoff":
                    return {
                        "type": "handoff",
                        "text": reply_text or "Хороший вопрос! Уточню у менеджера и напишу вам.",
                        "reason": action.get("reason", ""),
                    }
            except (json.JSONDecodeError, KeyError):
                pass

    return {"type": "text", "text": content}
