# bot.py
# Foxyma-style Telegram management bot template
# Python 3.10+
#
# Install:
#   pip install python-telegram-bot==22.3
#
# Set your token:
#   Linux/macOS: export BOT_TOKEN="YOUR_BOT_TOKEN"
#   Windows CMD: set BOT_TOKEN=YOUR_BOT_TOKEN
#
# Run:
#   python bot.py

import os
import sqlite3
import logging
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
DB_PATH = "bot.db"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("foxyma-style-bot")


# -------------------- Database --------------------

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT NOT NULL,
            balance INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            price INTEGER NOT NULL,
            stock INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            price INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()


def save_user(user):
    conn = db()
    conn.execute("""
        INSERT INTO users(user_id, username, first_name, joined_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
    """, (
        user.id,
        user.username or "",
        user.first_name or "",
        datetime.utcnow().isoformat(),
    ))
    conn.commit()
    conn.close()


def get_user(user_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row


def is_banned(user_id):
    row = get_user(user_id)
    return bool(row and row["is_banned"])


def is_admin(user_id):
    return user_id in ADMIN_IDS


def money(n):
    return f"{int(n):,} تومان"


# -------------------- UI --------------------

def main_keyboard(user_id):
    rows = [
        [
            InlineKeyboardButton("🛍 فروشگاه", callback_data="shop"),
            InlineKeyboardButton("👤 حساب من", callback_data="account"),
        ],
        [
            InlineKeyboardButton("💳 افزایش موجودی", callback_data="deposit"),
            InlineKeyboardButton("📦 سفارش‌های من", callback_data="orders"),
        ],
        [
            InlineKeyboardButton("📞 پشتیبانی", callback_data="support"),
            InlineKeyboardButton("ℹ️ راهنما", callback_data="help"),
        ],
    ]

    if is_admin(user_id):
        rows.append([
            InlineKeyboardButton("⚙️ مدیریت", callback_data="admin")
        ])

    return InlineKeyboardMarkup(rows)


def back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data="home")]
    ])


# -------------------- Commands --------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    if is_banned(user.id):
        await update.message.reply_text("⛔ حساب شما مسدود شده است.")
        return

    text = (
        f"👋 سلام {user.first_name}!\n\n"
        "به ربات فروش و مدیریت خدمات خوش آمدی.\n"
        "از منوی زیر بخش موردنظرت را انتخاب کن."
    )
    await update.message.reply_text(
        text,
        reply_markup=main_keyboard(user.id),
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ دسترسی ندارید.")
        return

    await update.message.reply_text(
        "⚙️ پنل مدیریت",
        reply_markup=admin_keyboard(),
    )


# -------------------- Menus --------------------

def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 آمار", callback_data="admin_stats"),
            InlineKeyboardButton("👥 کاربران", callback_data="admin_users"),
        ],
        [
            InlineKeyboardButton("➕ محصول", callback_data="admin_add"),
            InlineKeyboardButton("📦 محصولات", callback_data="admin_products"),
        ],
        [
            InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"),
        ],
        [
            InlineKeyboardButton("🔙 منوی اصلی", callback_data="home")
        ],
    ])


async def show_home(query, user_id):
    await query.edit_message_text(
        "🏠 منوی اصلی\n\nیک گزینه را انتخاب کن:",
        reply_markup=main_keyboard(user_id),
    )


async def show_account(query, user_id):
    row = get_user(user_id)
    balance = row["balance"] if row else 0

    text = (
        "👤 <b>حساب کاربری</b>\n\n"
        f"🆔 شناسه: <code>{user_id}</code>\n"
        f"💰 موجودی: <b>{money(balance)}</b>\n"
    )
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )


async def show_shop(query):
    conn = db()
    products = conn.execute(
        "SELECT * FROM products WHERE active=1 ORDER BY id DESC"
    ).fetchall()
    conn.close()

    if not products:
        await query.edit_message_text(
            "🛍 فروشگاه خالی است.",
            reply_markup=back_keyboard(),
        )
        return

    buttons = []
    for p in products:
        buttons.append([
            InlineKeyboardButton(
                f"{p['name']} — {money(p['price'])}",
                callback_data=f"product:{p['id']}"
            )
        ])

    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="home")])

    await query.edit_message_text(
        "🛍 <b>فروشگاه</b>\n\nمحصول موردنظر را انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_product(query, product_id):
    conn = db()
    p = conn.execute(
        "SELECT * FROM products WHERE id=? AND active=1",
        (product_id,),
    ).fetchone()
    conn.close()

    if not p:
        await query.answer("محصول پیدا نشد.", show_alert=True)
        return

    text = (
        f"🛒 <b>{p['name']}</b>\n\n"
        f"{p['description'] or 'بدون توضیحات'}\n\n"
        f"💵 قیمت: <b>{money(p['price'])}</b>\n"
        f"📦 موجودی: <b>{p['stock']}</b>"
    )

    buttons = []
    if p["stock"] > 0:
        buttons.append([
            InlineKeyboardButton(
                "✅ خرید",
                callback_data=f"buy:{p['id']}"
            )
        ])
    buttons.append([
        InlineKeyboardButton("🔙 فروشگاه", callback_data="shop")
    ])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def buy_product(query, user_id, product_id):
    conn = db()

    user = conn.execute(
        "SELECT * FROM users WHERE user_id=?", (user_id,)
    ).fetchone()
    product = conn.execute(
        "SELECT * FROM products WHERE id=? AND active=1",
        (product_id,),
    ).fetchone()

    if not product:
        conn.close()
        await query.answer("محصول موجود نیست.", show_alert=True)
        return

    if product["stock"] <= 0:
        conn.close()
        await query.answer("موجودی محصول تمام شده.", show_alert=True)
        return

    if user["balance"] < product["price"]:
        conn.close()
        await query.answer("موجودی کافی نیست.", show_alert=True)
        return

    conn.execute(
        "UPDATE users SET balance=balance-? WHERE user_id=?",
        (product["price"], user_id),
    )
    conn.execute(
        "UPDATE products SET stock=stock-1 WHERE id=?",
        (product_id,),
    )
    conn.execute("""
        INSERT INTO orders(user_id, product_id, price, status, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        product_id,
        product["price"],
        "paid",
        datetime.utcnow().isoformat(),
    ))
    conn.commit()
    order_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    await query.edit_message_text(
        f"✅ <b>خرید با موفقیت انجام شد!</b>\n\n"
        f"📦 محصول: {product['name']}\n"
        f"💵 مبلغ: {money(product['price'])}\n"
        f"🧾 شماره سفارش: <code>#{order_id}</code>\n\n"
        "برای تحویل خودکار محصول می‌توانی بخش delivery را در کد توسعه بدهی.",
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )


async def show_orders(query, user_id):
    conn = db()
    orders = conn.execute("""
        SELECT o.*, p.name
        FROM orders o
        LEFT JOIN products p ON p.id=o.product_id
        WHERE o.user_id=?
        ORDER BY o.id DESC
        LIMIT 10
    """, (user_id,)).fetchall()
    conn.close()

    if not orders:
        text = "📦 هنوز سفارشی ثبت نکرده‌ای."
    else:
        lines = ["📦 <b>آخرین سفارش‌ها</b>\n"]
        for o in orders:
            lines.append(
                f"#{o['id']} — {o['name'] or 'محصول حذف‌شده'} — "
                f"{money(o['price'])} — {o['status']}"
            )
        text = "\n".join(lines)

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )


async def show_help(query):
    text = (
        "ℹ️ <b>راهنما</b>\n\n"
        "🛍 از فروشگاه محصول انتخاب کن.\n"
        "👤 در حساب من موجودی و شناسه‌ات را ببین.\n"
        "📦 سفارش‌های قبلی را مشاهده کن.\n"
        "💳 برای سیستم پرداخت واقعی، درگاه موردنظرت را به بخش deposit متصل کن.\n\n"
        "این پروژه یک قالب تمیز و قابل توسعه است و می‌توانی امکانات اختصاصی خودت را به آن اضافه کنی."
    )
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )


async def show_support(query):
    text = (
        "📞 <b>پشتیبانی</b>\n\n"
        "برای پشتیبانی، آیدی ادمین یا لینک کانال خودت را در این بخش قرار بده.\n\n"
        "مثال:\n"
        "@YourSupportUsername"
    )
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )


async def show_deposit(query):
    text = (
        "💳 <b>افزایش موجودی</b>\n\n"
        "این قسمت آماده اتصال به درگاه پرداخت است.\n"
        "برای پرداخت واقعی باید API درگاه معتبر خودت را اضافه کنی."
    )
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )


# -------------------- Admin --------------------

async def admin_stats(query):
    conn = db()
    users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    orders = conn.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
    revenue = conn.execute(
        "SELECT COALESCE(SUM(price),0) total FROM orders WHERE status='paid'"
    ).fetchone()["total"]
    products = conn.execute(
        "SELECT COUNT(*) c FROM products WHERE active=1"
    ).fetchone()["c"]
    conn.close()

    text = (
        "📊 <b>آمار ربات</b>\n\n"
        f"👥 کاربران: <b>{users}</b>\n"
        f"🛒 سفارش‌ها: <b>{orders}</b>\n"
        f"📦 محصولات فعال: <b>{products}</b>\n"
        f"💰 فروش ثبت‌شده: <b>{money(revenue)}</b>"
    )
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


async def admin_users(query):
    conn = db()
    rows = conn.execute(
        "SELECT user_id, username, balance FROM users ORDER BY joined_at DESC LIMIT 20"
    ).fetchall()
    conn.close()

    if not rows:
        text = "👥 کاربری وجود ندارد."
    else:
        lines = ["👥 <b>آخرین کاربران</b>\n"]
        for r in rows:
            name = f"@{r['username']}" if r["username"] else "بدون یوزرنیم"
            lines.append(
                f"🆔 <code>{r['user_id']}</code> | {name} | {money(r['balance'])}"
            )
        text = "\n".join(lines)

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


async def admin_products(query):
    conn = db()
    rows = conn.execute(
        "SELECT * FROM products ORDER BY id DESC"
    ).fetchall()
    conn.close()

    if not rows:
        text = "📦 محصولی ثبت نشده."
    else:
        lines = ["📦 <b>محصولات</b>\n"]
        for p in rows:
            state = "فعال" if p["active"] else "غیرفعال"
            lines.append(
                f"#{p['id']} — {p['name']} — {money(p['price'])} — "
                f"موجودی: {p['stock']} — {state}"
            )
        text = "\n".join(lines)

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


# -------------------- Callback Router --------------------

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if is_banned(user_id):
        await query.edit_message_text("⛔ حساب شما مسدود شده است.")
        return

    data = query.data

    if data == "home":
        await show_home(query, user_id)

    elif data == "account":
        await show_account(query, user_id)

    elif data == "shop":
        await show_shop(query)

    elif data == "orders":
        await show_orders(query, user_id)

    elif data == "help":
        await show_help(query)

    elif data == "support":
        await show_support(query)

    elif data == "deposit":
        await show_deposit(query)

    elif data.startswith("product:"):
        await show_product(query, int(data.split(":")[1]))

    elif data.startswith("buy:"):
        await buy_product(query, user_id, int(data.split(":")[1]))

    elif data == "admin":
        if is_admin(user_id):
            await query.edit_message_text(
                "⚙️ <b>پنل مدیریت</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=admin_keyboard(),
            )
        else:
            await query.answer("دسترسی ندارید.", show_alert=True)

    elif data == "admin_stats":
        if is_admin(user_id):
            await admin_stats(query)

    elif data == "admin_users":
        if is_admin(user_id):
            await admin_users(query)

    elif data == "admin_products":
        if is_admin(user_id):
            await admin_products(query)

    elif data == "admin_add":
        if is_admin(user_id):
            await query.edit_message_text(
                "➕ افزودن محصول\n\n"
                "برای سادگی این نسخه، محصولات را از طریق تابع seed_products "
                "در همین فایل اضافه کن؛ بعداً می‌توانی فرم مدیریتی کامل به آن اضافه کنی.",
                reply_markup=admin_keyboard(),
            )

    elif data == "admin_broadcast":
        if is_admin(user_id):
            await query.edit_message_text(
                "📢 پیام همگانی\n\n"
                "برای جلوگیری از ارسال ناخواسته، سیستم broadcast را باید با "
                "تأیید دو مرحله‌ای و محدودیت نرخ کامل کنی.",
                reply_markup=admin_keyboard(),
            )


# -------------------- Text Handler --------------------

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    if is_banned(user.id):
        await update.message.reply_text("⛔ حساب شما مسدود شده است.")
        return

    await update.message.reply_text(
        "از دکمه‌های منوی اصلی استفاده کن 👇",
        reply_markup=main_keyboard(user.id),
    )


# -------------------- Seed Data --------------------

def seed_products():
    conn = db()
    count = conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]

    if count == 0:
        conn.executemany("""
            INSERT INTO products(name, description, price, stock)
            VALUES (?, ?, ?, ?)
        """, [
            ("محصول نمونه ۱", "توضیحات محصول نمونه", 50000, 10),
            ("محصول نمونه ۲", "توضیحات محصول نمونه", 100000, 5),
        ])
        conn.commit()

    conn.close()


# -------------------- Main --------------------

def main():
    if TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        raise SystemExit(
            "BOT_TOKEN را تنظیم کن. مثال: export BOT_TOKEN='123:ABC...'"
        )

    init_db()
    seed_products()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
    )

    log.info("Bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
  
