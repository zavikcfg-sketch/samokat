import asyncio
import logging
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlencode

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "8655954492:AAHOztCppzZL71tjVJglnZ0hfvGl_mSiWzM").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()
YOOMONEY_ACCESS_TOKEN = os.getenv("YOOMONEY_ACCESS_TOKEN", "4100118889570559.3288B2E716CEEB922A26BD6BEAC58648FBFB680CCF64E4E1447D714D6FB5EA5F01F1478FAC686BEF394C8A186C98982DE563C1ABCDF9F2F61D971B61DA3C7E486CA818F98B9E0069F1C0891E090DD56A11319D626A40F0AE8302A8339DED9EB7969617F191D93275F64C4127A3ECB7AED33FCDE91CA68690EB7534C67E6C219E").strip()
YOOMONEY_WALLET = os.getenv("YOOMONEY_WALLET", "").strip()
ENABLE_STARS = os.getenv("ENABLE_STARS", "true").lower() == "true"

DB_PATH = "bot_data.db"

router = Router()


@dataclass(frozen=True)
class Product:
    code: str
    title: str
    amount_rub: Decimal
    category: str


PRODUCTS = {
    "tariff_60": Product("tariff_60", "60 минут · 150 RUB", Decimal("150"), "tariffs"),
    "tariff_60_duo": Product("tariff_60_duo", "60 минут для двоих · 250 RUB", Decimal("250"), "tariffs"),
    "tariff_120": Product("tariff_120", "120 минут · 300 RUB", Decimal("300"), "tariffs"),
    "tariff_180": Product("tariff_180", "180 минут · 450 RUB", Decimal("450"), "tariffs"),
    "tariff_300": Product("tariff_300", "300 минут · 600 RUB", Decimal("600"), "tariffs"),
    "sub_day": Product("sub_day", "Подписка 1 день за 1 RUB · 500 RUB", Decimal("500"), "subscriptions"),
    "sub_5days": Product("sub_5days", "Подписка 5 дней за 1 RUB · 1250 RUB", Decimal("1250"), "subscriptions"),
    "sub_worker": Product("sub_worker", "Аккаунт работника (безлимит) · 3000 RUB", Decimal("3000"), "subscriptions"),
}


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                product_code TEXT NOT NULL,
                amount_rub TEXT NOT NULL,
                label TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'created',
                promo_code TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Аккаунт", callback_data="menu_account")],
            [InlineKeyboardButton(text="🛴 Тарифы", callback_data="menu_tariffs")],
            [InlineKeyboardButton(text="💎 Подписки", callback_data="menu_subscriptions")],
            [InlineKeyboardButton(text="🆘 Помощь", callback_data="menu_help")],
        ]
    )


def products_keyboard(category: str) -> InlineKeyboardMarkup:
    rows = []
    for product in PRODUCTS.values():
        if product.category == category:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=product.title, callback_data=f"product:{product.code}"
                    )
                ]
            )
    rows.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_methods_keyboard(product_code: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="💳 ЮMoney", callback_data=f"pay_ym:{product_code}")]
    ]
    if ENABLE_STARS:
        rows.append([InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"pay_stars:{product_code}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def after_payment_keyboard(label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check:{label}")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu_main")],
        ]
    )


def create_order(user_id: int, username: str | None, product: Product) -> str:
    label = f"order_{user_id}_{secrets.token_hex(8)}"
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO orders (user_id, username, product_code, amount_rub, label, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                product.code,
                str(product.amount_rub),
                label,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
    return label


def build_yoomoney_quickpay_link(label: str, product: Product) -> str:
    params = {
        "receiver": YOOMONEY_WALLET,
        "quickpay-form": "shop",
        "targets": f"Покупка {product.title}",
        "paymentType": "SB",
        "sum": str(product.amount_rub),
        "label": label,
        "successURL": "https://t.me/",
    }
    return f"https://yoomoney.ru/quickpay/confirm.xml?{urlencode(params)}"


async def yoomoney_payment_success(label: str, expected_amount: Decimal) -> bool:
    if not YOOMONEY_ACCESS_TOKEN:
        return False
    url = "https://yoomoney.ru/api/operation-history"
    headers = {"Authorization": f"Bearer {YOOMONEY_ACCESS_TOKEN}"}
    payload = {"label": label, "records": 10}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=payload, headers=headers, timeout=30) as resp:
            if resp.status != 200:
                return False
            data = await resp.json()
    operations = data.get("operations", [])
    for op in operations:
        if op.get("status") == "success":
            amount = Decimal(str(op.get("amount", "0")))
            if amount >= expected_amount:
                return True
    return False


def generate_promo_code() -> str:
    return f"SCOOTER-{secrets.token_hex(4).upper()}"


def complete_order(label: str) -> tuple[bool, str]:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT status, promo_code FROM orders WHERE label = ?", (label,)
        ).fetchone()
        if not row:
            return False, "Заказ не найден."
        status, promo_code = row
        if status == "paid" and promo_code:
            return True, promo_code
        promo = generate_promo_code()
        conn.execute(
            "UPDATE orders SET status = 'paid', promo_code = ? WHERE label = ?",
            (promo, label),
        )
        conn.commit()
    return True, promo


def get_order(label: str):
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            "SELECT user_id, product_code, amount_rub, status, promo_code FROM orders WHERE label = ?",
            (label,),
        ).fetchone()


@router.message(CommandStart())
async def start_handler(message: Message):
    text = (
        "Привет! Это Scooter Promo Bot 🛴\n\n"
        "Здесь вы можете быстро купить тариф или подписку и получить персональный промокод.\n\n"
        "Выберите нужный раздел:"
    )
    await message.answer(text, reply_markup=main_menu_keyboard())


@router.callback_query(F.data == "menu_main")
async def menu_main(callback):
    await callback.message.edit_text("🏠 Главное меню", reply_markup=main_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "menu_account")
async def menu_account(callback):
    user = callback.from_user
    text = (
        "👤 Ваш аккаунт\n\n"
        f"ID: {user.id}\n"
        f"Username: @{user.username or 'не указан'}\n\n"
        "Все покупки и промокоды привязываются к этому профилю."
    )
    await callback.message.edit_text(text, reply_markup=main_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "menu_help")
async def menu_help(callback):
    text = (
        "🆘 Как это работает\n\n"
        "1) Выберите тариф или подписку.\n"
        "2) Оплатите заказ удобным способом.\n"
        "3) Нажмите кнопку «Проверить оплату».\n"
        "4) Получите ваш персональный промокод.\n\n"
        "Если оплата не подтверждается, попробуйте снова через 1-2 минуты."
    )
    await callback.message.edit_text(text, reply_markup=main_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "menu_tariffs")
async def menu_tariffs(callback):
    await callback.message.edit_text("🛴 Тарифы", reply_markup=products_keyboard("tariffs"))
    await callback.answer()


@router.callback_query(F.data == "menu_subscriptions")
async def menu_subscriptions(callback):
    await callback.message.edit_text(
        "💎 Подписки", reply_markup=products_keyboard("subscriptions")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("product:"))
async def select_product(callback):
    product_code = callback.data.split(":", maxsplit=1)[1]
    product = PRODUCTS.get(product_code)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    text = (
        f"🧾 Вы выбрали:\n{product.title}\n\n"
        "Выберите способ оплаты:"
    )
    await callback.message.edit_text(
        text, reply_markup=payment_methods_keyboard(product_code)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pay_ym:"))
async def pay_yoomoney(callback):
    product_code = callback.data.split(":", maxsplit=1)[1]
    product = PRODUCTS.get(product_code)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    if not YOOMONEY_WALLET:
        await callback.answer("ЮMoney кошелек не настроен", show_alert=True)
        return

    label = create_order(callback.from_user.id, callback.from_user.username, product)
    link = build_yoomoney_quickpay_link(label, product)
    text = (
        "✅ Заказ создан\n\n"
        f"Товар: {product.title}\n"
        f"Сумма: {product.amount_rub} RUB\n\n"
        f"Ссылка для оплаты:\n{link}\n\n"
        "После оплаты нажмите «Проверить оплату»."
    )
    await callback.message.edit_text(text, reply_markup=after_payment_keyboard(label))
    await callback.answer()


@router.callback_query(F.data.startswith("pay_stars:"))
async def pay_stars_info(callback):
    product_code = callback.data.split(":", maxsplit=1)[1]
    product = PRODUCTS.get(product_code)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    text = (
        f"⭐ Telegram Stars для позиции:\n{product.title}\n\n"
        "Сейчас режим Stars работает как демонстрационный.\n"
        "При необходимости можно подключить полноценный Telegram Invoice (XTR)."
    )
    await callback.message.edit_text(text, reply_markup=main_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("check:"))
async def check_payment(callback):
    label = callback.data.split(":", maxsplit=1)[1]
    row = get_order(label)
    if not row:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    user_id, product_code, amount_rub, status, promo_code = row
    if user_id != callback.from_user.id:
        await callback.answer("Это не ваш заказ", show_alert=True)
        return

    if status == "paid" and promo_code:
        await callback.message.edit_text(
            f"✅ Оплата уже подтверждена.\n\nВаш промокод: {promo_code}",
            reply_markup=main_menu_keyboard(),
        )
        await callback.answer()
        return

    paid = await yoomoney_payment_success(label, Decimal(amount_rub))
    if not paid:
        await callback.answer("Платеж пока не найден. Попробуйте через минуту.", show_alert=True)
        return

    ok, promo = complete_order(label)
    if not ok:
        await callback.answer(promo, show_alert=True)
        return

    product = PRODUCTS.get(product_code)
    product_title = product.title if product else product_code
    text = (
        "🎉 Оплата подтверждена\n"
        f"Товар: {product_title}\n"
        f"Ваш промокод: {promo}\n\n"
        "Сохраните промокод: он выдан только для этого аккаунта."
    )
    await callback.message.edit_text(text, reply_markup=main_menu_keyboard())
    await callback.answer("Успешно")

    if ADMIN_ID.isdigit():
        await callback.bot.send_message(
            int(ADMIN_ID),
            f"Новая оплата\nUser: {callback.from_user.id}\nProduct: {product_title}\nPromo: {promo}",
        )


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty. Fill .env file.")
    init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
