from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def owner_main_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [
            KeyboardButton(text="📊 Статистика"),
            KeyboardButton(text="💬 Диалоги"),
        ],
        [
            KeyboardButton(text="📝 База знаний"),
            KeyboardButton(text="⚙️ Настройки"),
        ],
        [
            KeyboardButton(text="🔗 Моя ссылка"),
            KeyboardButton(text="💳 Подписка"),
        ],
        [
            KeyboardButton(text="⏸ Остановить бот"),
            KeyboardButton(text="❓ Помощь"),
        ],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="🔐 Админ панель")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def setup_category_kb() -> InlineKeyboardMarkup:
    categories = [
        ("💇 Салон красоты", "cat:beauty"),
        ("🏥 Клиника/Стоматология", "cat:clinic"),
        ("🔧 Автосервис", "cat:auto"),
        ("🍕 Доставка еды", "cat:food"),
        ("💪 Фитнес", "cat:fitness"),
        ("🔨 Ремонт/Сервис", "cat:repair"),
        ("🛍 Магазин", "cat:shop"),
        ("📚 Образование", "cat:education"),
        ("🏠 Недвижимость", "cat:realty"),
        ("🎯 Другое", "cat:other"),
    ]
    buttons = [[InlineKeyboardButton(text=label, callback_data=data)] for label, data in categories]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def setup_tone_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😊 Дружелюбный", callback_data="tone:friendly")],
        [InlineKeyboardButton(text="👔 Деловой", callback_data="tone:formal")],
        [InlineKeyboardButton(text="😎 Неформальный", callback_data="tone:casual")],
    ])


def payment_kb() -> InlineKeyboardMarkup:
    """Клавиатура с тарифами — из payment.py."""
    from src.bot.handlers.payment import payment_kb as _pk
    return _pk()


def confirm_kb(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да", callback_data=f"confirm:{action}:yes"),
        InlineKeyboardButton(text="❌ Нет", callback_data=f"confirm:{action}:no"),
    ]])
