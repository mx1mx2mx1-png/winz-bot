# -*- coding: utf-8 -*-
"""
ViLd Winz - Telegram Giveaway Bot
Python 3.10+
python-telegram-bot 20.x / 21.x

نصب:
    pip install -U python-telegram-bot

اجرا:
    python bot.py

نکته:
- توکن ربات را در BOT_TOKEN قرار بده.
- آیدی عددی مدیر را در ADMIN_IDS قرار بده.
- برای @Mikilafee بهتر است بعد از اولین اجرای ربات، مقدار عددی آیدی خودت را
  در ADMIN_IDS بگذاری تا مدیریت بدون خطا کار کند.

این نسخه از استایل‌های رنگی جدید Inline Keyboard در Bot API پشتیبانی می‌کند.
دکمه‌ها بدون ایموجی و با استایل primary/ success/ danger ساخته می‌شوند.
"""

import asyncio
import html
import logging
import random
import secrets
import sqlite3
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton as _TelegramInlineKeyboardButton,
    InlineKeyboardMarkup,
)


def InlineKeyboardButton(text, **kwargs):
    # دکمه‌های رنگی جدید تلگرام (Bot API 9.4+)
    # متن دکمه بدون ایموجی نمایش داده می‌شود.
    import re
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", str(text)).strip()
    callback = kwargs.get("callback_data", "")
    if "style" not in kwargs:
        if callback in {"new", "cancel_create", "cancel", "prev", "back_main", "back", "support_cancel"} or callback.startswith(("cancel_", "back_")):
            kwargs["style"] = "danger"
        elif callback in {"about", "account", "help", "more"}:
            kwargs["style"] = "success"
        else:
            kwargs["style"] = "primary"
    return _TelegramInlineKeyboardButton(text, **kwargs)

from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    ConversationHandler,
    filters,
)

# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = "PUT_YOUR_BOT_TOKEN_HERE"

# آیدی عددی مدیر را اینجا قرار بده.
# مثال: ADMIN_IDS = {123456789}
ADMIN_IDS = set()

ADMIN_USERNAME = "Mikilafee"

DB_FILE = "winz.db"

# مراحل ساخت
(
    S_NAME,
    S_DURATION,
    S_CAPACITY,
    S_WINNERS,
    S_MINIMUM,
    S_ACCESS,
    S_CHANNEL_COUNT,
    S_CHANNELS,
    S_REFERRAL,
    S_REF_LIMIT,
    S_PRIZE,
    S_SECURITY,
    S_WINNER_METHOD,
    S_MANUAL_WINNER,
) = range(14)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("winz")


# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(DB_FILE)
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
            language TEXT DEFAULT 'fa',
            joined_at TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            premium INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            owner_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            duration_seconds INTEGER NOT NULL,
            ends_at TEXT NOT NULL,
            capacity INTEGER,
            winners_count INTEGER NOT NULL,
            minimum INTEGER DEFAULT 0,
            access_type TEXT DEFAULT 'all',
            channel_count INTEGER DEFAULT 0,
            channels TEXT DEFAULT '',
            referral_enabled INTEGER DEFAULT 0,
            referral_limit INTEGER,
            prize TEXT NOT NULL,
            security INTEGER DEFAULT 1,
            winner_method TEXT DEFAULT 'random',
            manual_winners TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            status TEXT DEFAULT 'active'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            giveaway_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at TEXT NOT NULL,
            referral_count INTEGER DEFAULT 0,
            PRIMARY KEY (giveaway_id, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            giveaway_id INTEGER NOT NULL,
            inviter_id INTEGER NOT NULL,
            invited_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (giveaway_id, invited_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS winners (
            giveaway_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            announced_at TEXT NOT NULL,
            PRIMARY KEY (giveaway_id, user_id)
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# HELPERS
# ============================================================

def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def parse_dt(value):
    return datetime.fromisoformat(value)


def esc(value):
    return html.escape(str(value))


def make_code(length=10):
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def is_admin(user_id: int):
    # علاوه بر ADMIN_IDS، یوزرنیم مدیر اصلی هم بررسی می‌شود.
    # بنابراین اگر مدیر با @Mikilafee قبلاً /start زده باشد،
    # بدون وارد کردن آیدی عددی هم دسترسی مدیریت خواهد داشت.
    if user_id in ADMIN_IDS:
        return True

    conn = db()
    row = conn.execute(
        "SELECT username FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()
    conn.close()

    return bool(row and row["username"] and row["username"].lower() == ADMIN_USERNAME.lower())


def touch_user(user):
    conn = db()
    cur = conn.cursor()
    t = iso(now())
    cur.execute("""
        INSERT INTO users(user_id, username, first_name, joined_at, last_seen)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            last_seen=excluded.last_seen
    """, (
        user.id,
        user.username or "",
        user.first_name or "",
        t,
        t,
    ))
    conn.commit()
    conn.close()


def get_user(user_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()
    conn.close()
    return row


def get_giveaway(gid):
    conn = db()
    row = conn.execute(
        "SELECT * FROM giveaways WHERE id=?",
        (gid,)
    ).fetchone()
    conn.close()
    return row


def get_active_giveaways():
    conn = db()
    rows = conn.execute(
        "SELECT * FROM giveaways WHERE status='active' ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return rows


def participant_count(gid):
    conn = db()
    n = conn.execute(
        "SELECT COUNT(*) FROM participants WHERE giveaway_id=?",
        (gid,)
    ).fetchone()[0]
    conn.close()
    return n


def user_referral_count(gid, uid):
    conn = db()
    n = conn.execute("""
        SELECT COUNT(*) FROM referrals
        WHERE giveaway_id=? AND inviter_id=?
    """, (gid, uid)).fetchone()[0]
    conn.close()
    return n


def already_joined(gid, uid):
    conn = db()
    row = conn.execute("""
        SELECT 1 FROM participants
        WHERE giveaway_id=? AND user_id=?
    """, (gid, uid)).fetchone()
    conn.close()
    return bool(row)


def remaining_text(g):
    left = parse_dt(g["ends_at"]) - now()
    sec = max(0, int(left.total_seconds()))
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)

    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"


def capacity_text(g):
    return "∞" if g["capacity"] is None else str(g["capacity"])


def access_text(g):
    if g["access_type"] == "all":
        return "همه کاربران"
    if g["access_type"] == "premium":
        return "فقط پرمیوم"
    return g["access_type"]


def winner_method_text(g):
    return "انتخاب تصادفی" if g["winner_method"] == "random" else "بر اساس تیکت"


def giveaway_card(g):
    count = participant_count(g["id"])
    ref = "∞" if g["referral_limit"] is None else str(g["referral_limit"])

    text = (
        f"<b>╭─「 {esc(g['title'])} 」─╮</b>\n\n"
        f"<b>جایزه:</b> {esc(g['prize'])}\n"
        f"<b>برنده:</b> {g['winners_count']} نفر\n"
        f"<b>ظرفیت:</b> {capacity_text(g)}\n"
        f"<b>دسترسی:</b> {esc(access_text(g))}\n"
        f"<b>برگزارکننده:</b> @{esc(ADMIN_USERNAME if g['owner_id'] in ADMIN_IDS else 'مدیریت')}\n"
        f"<b>کانال‌ها:</b> {g['channel_count']} کانال\n"
        f"<b>رفرال:</b> {ref}\n\n"
        f"<b>شرکت‌کنندگان:</b> {count} نفر\n"
        f"<b>زمان باقی‌مانده:</b> {remaining_text(g)}\n"
        f"<b>دعوت موفق شما:</b> 0 نفر\n\n"
        f"<b>╰─ 🆒 فعال ─╯</b>"
    )
    return text


def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ساخت قرعه‌کشی", callback_data="new", style="danger")],
        [
            InlineKeyboardButton("قرعه‌کشی‌های من", callback_data="mine", style="primary"),
            InlineKeyboardButton("قرعه‌کشی‌های فعال", callback_data="active", style="primary"),
        ],
        [
            InlineKeyboardButton("درباره ربات", callback_data="about", style="success"),
            InlineKeyboardButton("حساب من", callback_data="account", style="success"),
        ],
        [
            InlineKeyboardButton("تغییر زبان", callback_data="language", style="primary"),
            InlineKeyboardButton("ارتباط با ما", callback_data="support", style="primary"),
        ],
        [
            InlineKeyboardButton("امکانات بیشتر", callback_data="more", style="primary"),
            InlineKeyboardButton("راهنما", callback_data="help", style="success"),
        ],
    ])


def back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 بازگشت", callback_data="home")]
    ])


def prev_cancel_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔴 مرحله قبل", callback_data="prev"),
            InlineKeyboardButton("🔴 لغو", callback_data="cancel_create"),
        ]
    ])


def parse_number(text):
    text = text.strip().replace(",", "").replace("٬", "")
    if text.isdigit():
        return int(text)
    return None


# ============================================================
# START / HOME
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    touch_user(user)

    # رفرال: /start ref_CODE
    args = context.args
    if args and args[0].startswith("ref_"):
        await process_referral(user.id, args[0][4:])

    text = (
        "<b>به ViLd 𝚆𝚒𝚗𝚣 خوش اومدی</b>\n\n"
        "<blockquote>"
        "<b>دنیای جایزه‌های خاص و شانس‌های بزرگ</b>\n"
        "<b>اینجا هر قرعه، می‌تونه مسیرتو عوض کنه</b>\n"
        "<b>شاید این بار، اسم برنده اسم تو باشه</b>\n"
        "<b>خوش اومدی به سرزمین شانس و برنده‌ها</b>"
        "</blockquote>"
    )

    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


async def home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await send_home(q)


async def send_home(q):
    text = (
        "<b>به ViLd 𝚆𝚒𝚗𝚣 خوش اومدی</b>\n\n"
        "<blockquote>"
        "<b>دنیای جایزه‌های خاص و شانس‌های بزرگ</b>\n"
        "<b>اینجا هر قرعه، می‌تونه مسیرتو عوض کنه</b>\n"
        "<b>شاید این بار، اسم برنده اسم تو باشه</b>\n"
        "<b>خوش اومدی به سرزمین شانس و برنده‌ها</b>"
        "</blockquote>"
    )
    await q.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


# ============================================================
# CREATE GIVEAWAY
# ============================================================

async def new_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    context.user_data["create"] = {}
    context.user_data["step"] = 1

    await q.edit_message_text(
        "<b>گام ۱/۱۱ — نام قرعه‌کشی</b>\n\n"
        "<blockquote><b>یک اسم دلخواه برای قرعه‌کشیت انتخاب کن\n"
        "مثال: گیفت NFT، استارز تلگرام، ...</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 لغو", callback_data="cancel_create")]
        ]),
    )
    return S_NAME


async def create_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["create"]["title"] = update.message.text.strip()
    context.user_data["step"] = 2

    await update.message.reply_text(
        "<b>گام ۲/۱۱ — مدت زمان</b>\n\n"
        "<blockquote><b>قرعه‌کشی چقدر طول بکشد؟</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔵 5 دقیقه", callback_data="dur_300")],
            [InlineKeyboardButton("🔵 10 دقیقه", callback_data="dur_600")],
            [InlineKeyboardButton("🔵 30 دقیقه", callback_data="dur_1800")],
            [InlineKeyboardButton("🔵 1 ساعت", callback_data="dur_3600")],
            [InlineKeyboardButton("🔵 5 ساعت", callback_data="dur_18000")],
            [InlineKeyboardButton("🔵 24 ساعت", callback_data="dur_86400")],
            [InlineKeyboardButton("🔵 دستی", callback_data="dur_manual")],
            [
                InlineKeyboardButton("🔴 مرحله قبل", callback_data="prev"),
                InlineKeyboardButton("🔴 لغو", callback_data="cancel_create"),
            ],
        ]),
    )
    return S_DURATION


async def duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    value = q.data.split("_", 1)[1]

    if value == "manual":
        context.user_data["awaiting"] = "duration_manual"
        await q.edit_message_text(
            "<b>گام ۲/۱۱ — مدت زمان</b>\n\n"
            "<blockquote><b>مدت زمان را بر حسب دقیقه وارد کن.</b></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=prev_cancel_keyboard(),
        )
        return S_DURATION

    context.user_data["create"]["duration"] = int(value)
    await show_capacity(q, context)
    return S_CAPACITY


async def duration_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = parse_number(update.message.text)
    if not n or n <= 0:
        await update.message.reply_text("یک عدد معتبر بر حسب دقیقه ارسال کن.")
        return S_DURATION

    context.user_data["create"]["duration"] = n * 60
    context.user_data.pop("awaiting", None)
    await show_capacity_message(update.message, context)
    return S_CAPACITY


async def show_capacity(q, context):
    await q.edit_message_text(
        "<b>گام ۳/۱۱ — ظرفیت</b>\n\n"
        "<blockquote><b>حداکثر چند نفر می‌توانند شرکت کنند؟</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔵 10 نفر", callback_data="cap_10")],
            [InlineKeyboardButton("🔵 50 نفر", callback_data="cap_50")],
            [InlineKeyboardButton("🔵 100 نفر", callback_data="cap_100")],
            [InlineKeyboardButton("🔵 500 نفر", callback_data="cap_500")],
            [InlineKeyboardButton("🔵 1000 نفر", callback_data="cap_1000")],
            [InlineKeyboardButton("🔵 بی‌نهایت", callback_data="cap_inf")],
            [InlineKeyboardButton("🔵 دستی", callback_data="cap_manual")],
            [
                InlineKeyboardButton("🔴 مرحله قبل", callback_data="prev"),
                InlineKeyboardButton("🔴 لغو", callback_data="cancel_create"),
            ],
        ]),
    )


async def show_capacity_message(message, context):
    await message.reply_text(
        "<b>گام ۳/۱۱ — ظرفیت</b>\n\n"
        "<blockquote><b>حداکثر چند نفر می‌توانند شرکت کنند؟</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔵 10 نفر", callback_data="cap_10")],
            [InlineKeyboardButton("🔵 50 نفر", callback_data="cap_50")],
            [InlineKeyboardButton("🔵 100 نفر", callback_data="cap_100")],
            [InlineKeyboardButton("🔵 500 نفر", callback_data="cap_500")],
            [InlineKeyboardButton("🔵 1000 نفر", callback_data="cap_1000")],
            [InlineKeyboardButton("🔵 بی‌نهایت", callback_data="cap_inf")],
            [InlineKeyboardButton("🔵 دستی", callback_data="cap_manual")],
            [
                InlineKeyboardButton("🔴 مرحله قبل", callback_data="prev"),
                InlineKeyboardButton("🔴 لغو", callback_data="cancel_create"),
            ],
        ]),
    )


async def capacity_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    value = q.data.split("_", 1)[1]

    if value == "manual":
        context.user_data["awaiting"] = "capacity_manual"
        await q.edit_message_text(
            "<b>گام ۳/۱۱ — ظرفیت</b>\n\n"
            "<blockquote><b>تعداد ظرفیت را وارد کن.</b></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=prev_cancel_keyboard(),
        )
        return S_CAPACITY

    context.user_data["create"]["capacity"] = None if value == "inf" else int(value)
    await show_winners(q)
    return S_WINNERS


async def capacity_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = parse_number(update.message.text)
    if not n or n <= 0:
        await update.message.reply_text("یک عدد معتبر وارد کن.")
        return S_CAPACITY

    context.user_data["create"]["capacity"] = n
    context.user_data.pop("awaiting", None)
    await show_winners_message(update.message)
    return S_WINNERS


async def show_winners(q):
    await q.edit_message_text(
        "<b>گام ۴/۱۱ — تعداد برنده‌ها</b>\n\n"
        "<blockquote><b>چند نفر برنده می‌شوند؟</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔵 1 برنده", callback_data="win_1")],
            [InlineKeyboardButton("🔵 2 برنده", callback_data="win_2")],
            [InlineKeyboardButton("🔵 3 برنده", callback_data="win_3")],
            [InlineKeyboardButton("🔵 5 برنده", callback_data="win_5")],
            [InlineKeyboardButton("🔵 10 برنده", callback_data="win_10")],
            [InlineKeyboardButton("🔵 دستی", callback_data="win_manual")],
            [
                InlineKeyboardButton("🔴 مرحله قبل", callback_data="prev"),
                InlineKeyboardButton("🔴 لغو", callback_data="cancel_create"),
            ],
        ]),
    )


async def show_winners_message(message):
    await message.reply_text(
        "<b>گام ۴/۱۱ — تعداد برنده‌ها</b>\n\n"
        "<blockquote><b>چند نفر برنده می‌شوند؟</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔵 1 برنده", callback_data="win_1")],
            [InlineKeyboardButton("🔵 2 برنده", callback_data="win_2")],
            [InlineKeyboardButton("🔵 3 برنده", callback_data="win_3")],
            [InlineKeyboardButton("🔵 5 برنده", callback_data="win_5")],
            [InlineKeyboardButton("🔵 10 برنده", callback_data="win_10")],
            [InlineKeyboardButton("🔵 دستی", callback_data="win_manual")],
            [
                InlineKeyboardButton("🔴 مرحله قبل", callback_data="prev"),
                InlineKeyboardButton("🔴 لغو", callback_data="cancel_create"),
            ],
        ]),
    )


async def winners_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    value = q.data.split("_", 1)[1]

    if value == "manual":
        context.user_data["awaiting"] = "winners_manual"
        await q.edit_message_text(
            "<b>گام ۴/۱۱ — تعداد برنده‌ها</b>\n\n"
            "<blockquote><b>تعداد برنده‌ها را وارد کن.</b></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=prev_cancel_keyboard(),
        )
        return S_WINNERS

    context.user_data["create"]["winners"] = int(value)
    await show_minimum(q)
    return S_MINIMUM


async def winners_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = parse_number(update.message.text)
    if not n or n <= 0:
        await update.message.reply_text("یک عدد معتبر وارد کن.")
        return S_WINNERS
    context.user_data["create"]["winners"] = n
    context.user_data.pop("awaiting", None)
    await show_minimum_message(update.message)
    return S_MINIMUM


async def show_minimum(q):
    await q.edit_message_text(
        "<b>گام ۵/۱۱ — حداقل شرکت‌کننده</b>\n\n"
        "<blockquote><b>اگر به این تعداد نرسد، قرعه‌کشی لغو می‌شود\n"
        "(۰ = بدون محدودیت)</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔵 بدون حداقل", callback_data="min_0")],
            [InlineKeyboardButton("🔵 5", callback_data="min_5")],
            [InlineKeyboardButton("🔵 10", callback_data="min_10")],
            [InlineKeyboardButton("🔵 20", callback_data="min_20")],
            [InlineKeyboardButton("🔵 50", callback_data="min_50")],
            [
                InlineKeyboardButton("🔴 مرحله قبل", callback_data="prev"),
                InlineKeyboardButton("🔴 لغو", callback_data="cancel_create"),
            ],
        ]),
    )


async def show_minimum_message(message):
    await message.reply_text(
        "<b>گام ۵/۱۱ — حداقل شرکت‌کننده</b>\n\n"
        "<blockquote><b>اگر به این تعداد نرسد، قرعه‌کشی لغو می‌شود\n"
        "(۰ = بدون محدودیت)</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔵 بدون حداقل", callback_data="min_0")],
            [InlineKeyboardButton("🔵 5", callback_data="min_5")],
            [InlineKeyboardButton("🔵 10", callback_data="min_10")],
            [InlineKeyboardButton("🔵 20", callback_data="min_20")],
            [InlineKeyboardButton("🔵 50", callback_data="min_50")],
            [
                InlineKeyboardButton("🔴 مرحله قبل", callback_data="prev"),
                InlineKeyboardButton("🔴 لغو", callback_data="cancel_create"),
            ],
        ]),
    )


async def minimum_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["create"]["minimum"] = int(q.data.split("_")[1])
    await show_access(q)
    return S_ACCESS


async def show_access(q):
    await q.edit_message_text(
        "<b>گام ۶/۱۱ — محدودیت دسترسی</b>\n\n"
        "<blockquote><b>چه کسانی می‌توانند شرکت کنند؟</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔵 همه کاربران", callback_data="access_all")],
            [InlineKeyboardButton("🔵 پرمیوم‌دار", callback_data="access_premium")],
            [InlineKeyboardButton("🔵 همه کاربران + لول اکانت", callback_data="access_all")],
            [
                InlineKeyboardButton("🔴 مرحله قبل", callback_data="prev"),
                InlineKeyboardButton("🔴 لغو", callback_data="cancel_create"),
            ],
        ]),
    )


async def access_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["create"]["access"] = q.data.replace("access_", "")
    await show_channel_count(q)
    return S_CHANNEL_COUNT


async def show_channel_count(q):
    await q.edit_message_text(
        "<b>گام ۷/۱۱ — کانال اسپانسر</b>\n\n"
        "<blockquote><b>کانالی که می‌خواهید گیواوی در آن منتشر شود را وارد کنید.\n"
        "شما و ربات باید در آن کانال ادمین باشید.</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔵 بدون نیاز به کانال", callback_data="channels_0")],
            [InlineKeyboardButton("🔵 1 کانال", callback_data="channels_1")],
            [InlineKeyboardButton("🔵 2 کانال", callback_data="channels_2")],
            [InlineKeyboardButton("🔵 3 کانال", callback_data="channels_3")],
            [InlineKeyboardButton("🔵 4 کانال", callback_data="channels_4")],
            [InlineKeyboardButton("🔵 5 کانال", callback_data="channels_5")],
            [InlineKeyboardButton("🔵 6 کانال", callback_data="channels_6")],
            [InlineKeyboardButton("🔵 دستی", callback_data="channels_manual")],
            [
                InlineKeyboardButton("🔴 مرحله قبل", callback_data="prev"),
                InlineKeyboardButton("🔴 لغو", callback_data="cancel_create"),
            ],
        ]),
    )


async def channel_count_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    value = q.data.split("_")[1]

    if value == "manual":
        context.user_data["awaiting"] = "channel_count_manual"
        await q.edit_message_text(
            "<b>گام ۷/۱۱ — تعداد کانال</b>\n\n"
            "<blockquote><b>تعداد کانال‌ها را وارد کن.</b></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=prev_cancel_keyboard(),
        )
        return S_CHANNEL_COUNT

    count = int(value)
    context.user_data["create"]["channel_count"] = count
    context.user_data["create"]["channels"] = []

    if count == 0:
        await show_referral(q)
        return S_REFERRAL

    context.user_data["channel_index"] = 1
    await ask_channel(q, 1, count)
    return S_CHANNELS


async def channel_count_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = parse_number(update.message.text)
    if n is None or n < 0 or n > 20:
        await update.message.reply_text("عدد کانال باید بین ۰ تا ۲۰ باشد.")
        return S_CHANNEL_COUNT

    context.user_data["create"]["channel_count"] = n
    context.user_data["create"]["channels"] = []
    context.user_data.pop("awaiting", None)

    if n == 0:
        await show_referral_message(update.message)
        return S_REFERRAL

    context.user_data["channel_index"] = 1
    await ask_channel_message(update.message, 1, n)
    return S_CHANNELS


async def ask_channel(q, index, count):
    await q.edit_message_text(
        f"<b>لطفاً لینک کانال شماره {index} را ارسال کنید:</b>\n\n"
        "<blockquote><b>(ربات را در کانال ادمین کنید)</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=prev_cancel_keyboard(),
    )


async def ask_channel_message(message, index, count):
    await message.reply_text(
        f"<b>لطفاً لینک کانال شماره {index} را ارسال کنید:</b>\n\n"
        "<blockquote><b>(ربات را در کانال ادمین کنید)</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=prev_cancel_keyboard(),
    )


async def channel_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text.strip()
    if not (value.startswith("@") or value.startswith("https://t.me/")):
        await update.message.reply_text("لطفاً @username یا لینک t.me کانال را ارسال کن.")
        return S_CHANNELS

    context.user_data["create"]["channels"].append(value)
    idx = context.user_data["channel_index"]
    count = context.user_data["create"]["channel_count"]

    if idx < count:
        idx += 1
        context.user_data["channel_index"] = idx
        await ask_channel_message(update.message, idx, count)
        return S_CHANNELS

    await show_referral_message(update.message)
    return S_REFERRAL


async def show_referral(q):
    await q.edit_message_text(
        "<b>گام ۸/۱۱ — رفرال‌گیری</b>\n\n"
        "<blockquote><b>می‌خواهی این قرعه‌کشی سیستم رفرال داشته باشد؟</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔴 حذف رفرال", callback_data="ref_no"),
                InlineKeyboardButton("🔵 افزودن رفرال", callback_data="ref_yes"),
            ],
            [
                InlineKeyboardButton("🔵 مرحله قبل", callback_data="prev"),
                InlineKeyboardButton("🔴 لغو", callback_data="cancel_create"),
            ],
        ]),
    )


async def show_referral_message(message):
    await message.reply_text(
        "<b>گام ۸/۱۱ — رفرال‌گیری</b>\n\n"
        "<blockquote><b>می‌خواهی این قرعه‌کشی سیستم رفرال داشته باشد؟</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔴 حذف رفرال", callback_data="ref_no"),
                InlineKeyboardButton("🔵 افزودن رفرال", callback_data="ref_yes"),
            ],
            [
                InlineKeyboardButton("🔵 مرحله قبل", callback_data="prev"),
                InlineKeyboardButton("🔴 لغو", callback_data="cancel_create"),
            ],
        ]),
    )


async def referral_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    yes = q.data == "ref_yes"
    context.user_data["create"]["referral_enabled"] = 1 if yes else 0

    if yes:
        await q.edit_message_text(
            "<b>حداکثر تعداد رفرال</b>\n\n"
            "<blockquote><b>حداکثر چند نفر دعوت‌شده به‌شان تیکت رایگان بدهد؟</b></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔵 بدون محدودیت", callback_data="reflimit_inf")],
                [InlineKeyboardButton("🔵 مرحله قبل", callback_data="prev")],
                [InlineKeyboardButton("🔴 لغو", callback_data="cancel_create")],
            ]),
        )
        return S_REF_LIMIT

    context.user_data["create"]["referral_limit"] = None
    await show_prize(q)
    return S_PRIZE


async def referral_limit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["create"]["referral_limit"] = None
    await show_prize(q)
    return S_PRIZE


async def show_prize(q):
    await q.edit_message_text(
        "<b>گام ۹/۱۱ — جایزه</b>\n\n"
        "<blockquote><b>یکی از جایزه‌های زیر را انتخاب کن، یا با «دستی» جایزه دلخواه خودت را وارد کن:</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔵 استارز تلگرام", callback_data="prize_استارز تلگرام")],
            [InlineKeyboardButton("🔵 پرمیوم تلگرام", callback_data="prize_پرمیوم تلگرام")],
            [InlineKeyboardButton("🔵 گیفت تلگرام", callback_data="prize_گیفت تلگرام")],
            [InlineKeyboardButton("🔵 دستی", callback_data="prize_manual")],
            [InlineKeyboardButton("🔵 مرحله قبل", callback_data="prev")],
            [InlineKeyboardButton("🔴 لغو", callback_data="cancel_create")],
        ]),
    )


async def prize_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    value = q.data.split("_", 1)[1]

    if value == "manual":
        context.user_data["awaiting"] = "prize_manual"
        await q.edit_message_text(
            "<b>گام ۹/۱۱ — جایزه</b>\n\n"
            "<blockquote><b>نام جایزه را ارسال کن.</b></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=prev_cancel_keyboard(),
        )
        return S_PRIZE

    context.user_data["create"]["prize"] = value
    await show_security(q)
    return S_SECURITY


async def prize_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text.strip()
    if len(value) < 2:
        await update.message.reply_text("نام جایزه را واضح‌تر وارد کن.")
        return S_PRIZE
    context.user_data["create"]["prize"] = value
    context.user_data.pop("awaiting", None)
    await show_security_message(update.message)
    return S_SECURITY


async def show_security(q):
    await q.edit_message_text(
        "<b>گام ۱۰/۱۱ — تأیید امنیتی</b>\n\n"
        "<blockquote><b>برای ورود به قرعه‌کشی، سوال ریاضی فعال باشد یا بدون سوال وارد شوند؟</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 فعال", callback_data="security_1")],
            [InlineKeyboardButton("🔴 غیرفعال", callback_data="security_0")],
            [
                InlineKeyboardButton("🔵 مرحله قبل", callback_data="prev"),
                InlineKeyboardButton("🔴 لغو", callback_data="cancel_create"),
            ],
        ]),
    )


async def show_security_message(message):
    await message.reply_text(
        "<b>گام ۱۰/۱۱ — تأیید امنیتی</b>\n\n"
        "<blockquote><b>برای ورود به قرعه‌کشی، سوال ریاضی فعال باشد یا بدون سوال وارد شوند؟</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 فعال", callback_data="security_1")],
            [InlineKeyboardButton("🔴 غیرفعال", callback_data="security_0")],
            [
                InlineKeyboardButton("🔵 مرحله قبل", callback_data="prev"),
                InlineKeyboardButton("🔴 لغو", callback_data="cancel_create"),
            ],
        ]),
    )


async def security_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["create"]["security"] = int(q.data.split("_")[1])
    await show_winner_method(q)
    return S_WINNER_METHOD


async def show_winner_method(q):
    await q.edit_message_text(
        "<b>گام ۱۱/۱۱ — نوع انتخاب برنده</b>\n\n"
        "<blockquote><b>روش انتخاب برنده را مشخص کن</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔵 انتخاب تصادفی", callback_data="method_random"),
                InlineKeyboardButton("🟢 بر اساس تیکت", callback_data="method_ticket"),
            ],
            [
                InlineKeyboardButton("🔴 مرحله قبل", callback_data="prev"),
                InlineKeyboardButton("🔴 لغو", callback_data="cancel_create"),
            ],
        ]),
    )


async def winner_method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    method = q.data.replace("method_", "")

    if "create" not in context.user_data:
        await q.answer("اطلاعات ساخت قرعه‌کشی پیدا نشد. دوباره شروع کنید.", show_alert=True)
        return ConversationHandler.END

    context.user_data["create"]["winner_method"] = method

    c = context.user_data["create"]
    duration = c["duration"]
    ends = now() + timedelta(seconds=duration)

    code = make_code()
    while get_giveaway_by_code(code):
        code = make_code()

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO giveaways(
            code, owner_id, title, duration_seconds, ends_at,
            capacity, winners_count, minimum, access_type,
            channel_count, channels, referral_enabled,
            referral_limit, prize, security, winner_method,
            created_at, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
    """, (
        code,
        update.effective_user.id,
        c["title"],
        duration,
        iso(ends),
        c["capacity"],
        c["winners"],
        c["minimum"],
        c["access"],
        c["channel_count"],
        "\n".join(c["channels"]),
        c["referral_enabled"],
        c.get("referral_limit"),
        c["prize"],
        c["security"],
        method,
        iso(now()),
    ))
    gid = cur.lastrowid
    conn.commit()
    conn.close()

    context.user_data.clear()

    bot_username = (await bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=ref_{code}_{update.effective_user.id}"

    text = (
        "<b>قرعه‌کشی با موفقیت ساخته شد!</b>\n\n"
        f"<b>لینک قرعه‌کشی</b>\n"
        f"{esc(link)}\n\n"
        + giveaway_card(get_giveaway(gid))
    )

    await q.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=giveaway_keyboard(gid, update.effective_user.id),
        disable_web_page_preview=True,
    )
    return ConversationHandler.END


def get_giveaway_by_code(code):
    conn = db()
    row = conn.execute(
        "SELECT * FROM giveaways WHERE code=?",
        (code,)
    ).fetchone()
    conn.close()
    return row


# ============================================================
# CREATE CONVERSATION TEXT ROUTER
# ============================================================

async def create_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get("awaiting")

    if awaiting == "duration_manual":
        return await duration_manual(update, context)
    if awaiting == "capacity_manual":
        return await capacity_manual(update, context)
    if awaiting == "winners_manual":
        return await winners_manual(update, context)
    if awaiting == "channel_count_manual":
        return await channel_count_manual(update, context)
    if awaiting == "prize_manual":
        return await prize_manual(update, context)

    state = context.user_data.get("step")

    if state == 1:
        return await create_name(update, context)

    if state == 8:
        return await channel_input(update, context)

    return ConversationHandler.END


# ============================================================
# GIVEAWAY BUTTONS / JOIN
# ============================================================

def giveaway_keyboard(gid, user_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔵 ارسال در کانال", callback_data=f"publish_{gid}"),
            InlineKeyboardButton("🔵 شرکت در قرعه‌کشی", callback_data=f"join_{gid}"),
        ],
        [InlineKeyboardButton("🟢 لینک رفرال من", callback_data=f"ref_link_{gid}")],
        [InlineKeyboardButton("🔴 بازگشت", callback_data="home")],
    ])


async def giveaway_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    gid = int(data.rsplit("_", 1)[1])
    g = get_giveaway(gid)

    if not g:
        await q.edit_message_text(
            "<b>این قرعه‌کشی پیدا نشد یا حذف شده است.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard(),
        )
        return

    if data.startswith("join_"):
        await join_giveaway(q, context, g)
    elif data.startswith("ref_link_"):
        await referral_link(q, context, g)
    elif data.startswith("publish_"):
        await publish_giveaway(q, context, g)


async def join_giveaway(q, context, g):
    uid = q.from_user.id

    if g["status"] != "active":
        await q.answer("این قرعه‌کشی فعال نیست.", show_alert=True)
        return

    if parse_dt(g["ends_at"]) <= now():
        await finish_giveaway(g["id"], context)
        await q.answer("زمان این قرعه‌کشی تمام شده است.", show_alert=True)
        return

    if already_joined(g["id"], uid):
        await q.answer("قبلاً در این قرعه‌کشی شرکت کرده‌ای.", show_alert=True)
        return

    if g["capacity"] is not None and participant_count(g["id"]) >= g["capacity"]:
        await q.answer("ظرفیت قرعه‌کشی تکمیل شده است.", show_alert=True)
        return

    if g["access_type"] == "premium":
        user = get_user(uid)
        if not user or not user["premium"]:
            await q.answer("این قرعه‌کشی فقط برای کاربران پرمیوم است.", show_alert=True)
            return

    # بررسی عضویت در کانال‌های اسپانسر
    if g["channel_count"] > 0:
        channels = [x for x in g["channels"].splitlines() if x.strip()]
        missing = []
        for ch in channels:
            try:
                member = await context.bot.get_chat_member(ch, uid)
                if member.status in ("left", "kicked"):
                    missing.append(ch)
            except Exception:
                # اگر ربات نتواند کانال را بررسی کند، عضویت را قطعی فرض نمی‌کنیم.
                missing.append(ch)

        if missing:
            buttons = [
                [InlineKeyboardButton(f"عضویت در {ch}", url=(
                    ch if ch.startswith("https://") else f"https://t.me/{ch.lstrip('@')}"
                ))]
                for ch in missing
            ]
            buttons.append([InlineKeyboardButton(
                "🔄 بررسی عضویت",
                callback_data=f"join_{g['id']}"
            )])
            await q.edit_message_text(
                "<b>برای شرکت ابتدا در کانال‌های زیر عضو شو:</b>\n\n"
                "<blockquote><b>بعد از عضویت روی «بررسی عضویت» بزن.</b></blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            return

    # سوال ریاضی ساده
    if g["security"]:
        a = random.randint(2, 9)
        b = random.randint(2, 9)
        context.user_data["math"] = {
            "gid": g["id"],
            "answer": a + b,
        }
        await q.edit_message_text(
            "<b>تأیید امنیتی</b>\n\n"
            f"<blockquote><b>{a} + {b} = ؟</b></blockquote>\n\n"
            "<b>جواب را ارسال کن.</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    await register_participant(uid, g["id"], context)
    await q.answer("با موفقیت وارد قرعه‌کشی شدی!", show_alert=True)


async def math_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data.get("math")
    if not data:
        return

    answer = parse_number(update.message.text)
    if answer != data["answer"]:
        await update.message.reply_text(
            "<b>پاسخ اشتباه است.</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    gid = data["gid"]
    g = get_giveaway(gid)
    if g:
        await register_participant(update.effective_user.id, gid, context)

    context.user_data.pop("math", None)


async def register_participant(uid, gid, context):
    g = get_giveaway(gid)
    if not g or already_joined(gid, uid):
        return

    conn = db()
    conn.execute("""
        INSERT INTO participants(giveaway_id, user_id, joined_at)
        VALUES (?, ?, ?)
    """, (gid, uid, iso(now())))
    conn.commit()
    conn.close()

    await context.bot.send_message(
        uid,
        "<b>ورودت به قرعه‌کشی ثبت شد.</b>\n\n"
        "<blockquote><b>حالا فقط منتظر پایان زمان قرعه‌کشی باش.</b></blockquote>",
        parse_mode=ParseMode.HTML,
    )


async def process_referral(uid, code):
    g = get_giveaway_by_code(code)
    if not g or not g["referral_enabled"]:
        return

    owner_id = g["owner_id"]
    if uid == owner_id:
        return

    # پیدا کردن دعوت‌کننده از start لینک
    # این نسخه در صورت وجود پارامتر ref_CODE_ID، ID را نیز می‌پذیرد.
    # پارامتر اصلی start به شکل ref_CODE_OWNERID است.
    parts = code.split("_")
    inviter_id = None

    # چون code واقعی فقط کد قرعه است، در start مقدار کامل از آرگومان
    # به process_referral ارسال شده و ممکن است بخش ID در آن باقی مانده باشد.
    if len(parts) >= 2:
        try:
            inviter_id = int(parts[-1])
            giveaway_code = "_".join(parts[:-1])
            g = get_giveaway_by_code(giveaway_code)
        except ValueError:
            inviter_id = None

    if inviter_id is None:
        return

    if g["referral_limit"] is not None:
        if user_referral_count(g["id"], inviter_id) >= g["referral_limit"]:
            return

    if already_joined(g["id"], uid):
        return

    conn = db()
    try:
        conn.execute("""
            INSERT INTO referrals(giveaway_id, inviter_id, invited_id, created_at)
            VALUES (?, ?, ?, ?)
        """, (g["id"], inviter_id, uid, iso(now())))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()


async def referral_link(q, context, g):
    bot_username = (await bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=ref_{g['code']}_{q.from_user.id}"
    count = user_referral_count(g["id"], q.from_user.id)

    await q.edit_message_text(
        "<b>لینک رفرال شما</b>\n\n"
        f"<blockquote><b>{esc(link)}</b>\n\n"
        f"دعوت موفق: {count} نفر</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 بازگشت", callback_data=f"back_g_{g['id']}")]
        ]),
        disable_web_page_preview=True,
    )


async def publish_giveaway(q, context, g):
    await q.answer()
    if g["owner_id"] != q.from_user.id and not is_admin(q.from_user.id):
        await q.answer("فقط سازنده قرعه‌کشی می‌تواند آن را ارسال کند.", show_alert=True)
        return

    await q.message.reply_text(
        "<b>لینک قرعه‌کشی آماده ارسال است:</b>\n\n"
        f"<blockquote><b>https://t.me/{(await context.bot.get_me()).username}?start=ref_{g['code']}_{g['owner_id']}</b></blockquote>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def back_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    gid = int(q.data.rsplit("_", 1)[1])
    g = get_giveaway(gid)
    if not g:
        await send_home(q)
        return
    await q.edit_message_text(
        giveaway_card(g),
        parse_mode=ParseMode.HTML,
        reply_markup=giveaway_keyboard(gid, q.from_user.id),
    )


# ============================================================
# MINE / ACTIVE
# ============================================================

async def mine_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    conn = db()
    rows = conn.execute("""
        SELECT * FROM giveaways
        WHERE owner_id=?
        ORDER BY id DESC
    """, (q.from_user.id,)).fetchall()
    conn.close()

    if not rows:
        await q.edit_message_text(
            "<b>مدیریت قرعه‌کشی</b>\n\n"
            "<blockquote><b>هنوز هیچ قرعه‌کشی‌ای نساختی.</b></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard(),
        )
        return

    buttons = []
    for g in rows[:30]:
        buttons.append([
            InlineKeyboardButton(
                f"{g['title']} — {'فعال' if g['status']=='active' else 'پایان‌یافته'}",
                callback_data=f"manage_{g['id']}"
            )
        ])
    buttons.append([InlineKeyboardButton("🔴 بازگشت", callback_data="home")])

    await q.edit_message_text(
        "<b>مدیریت قرعه‌کشی</b>\n\n"
        "<b>لطفاً یکی از قرعه‌کشی‌های خود را انتخاب کنید:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def active_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    rows = get_active_giveaways()
    if not rows:
        await q.edit_message_text(
            "<b>قرعه‌کشی‌های فعال</b>\n\n"
            "<blockquote><b>در حال حاضر قرعه‌کشی فعالی وجود ندارد.</b></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard(),
        )
        return

    chunks = []
    for g in rows[:15]:
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start=ref_{g['code']}_{g['owner_id']}"
        chunks.append(
            f"<b>🎁 {esc(g['title'])}</b>\n"
            f"<b>جایزه:</b> {esc(g['prize'])}\n"
            f"<b>شرکت‌کنندگان:</b> {participant_count(g['id'])}\n"
            f"<b>زمان:</b> {remaining_text(g)}\n"
            f"<b>لینک:</b> {esc(link)}"
        )

    await q.edit_message_text(
        "<b>قرعه‌کشی‌های فعال</b>\n\n" +
        "\n\n".join(chunks),
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
        disable_web_page_preview=True,
    )


async def manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    gid = int(q.data.rsplit("_", 1)[1])
    g = get_giveaway(gid)

    if not g or (g["owner_id"] != q.from_user.id and not is_admin(q.from_user.id)):
        await q.answer("دسترسی ندارید.", show_alert=True)
        return

    text = giveaway_card(g)
    buttons = [
        [InlineKeyboardButton("🔵 مشاهده لینک", callback_data=f"showlink_{gid}")],
    ]

    if g["status"] == "active":
        buttons.append([
            InlineKeyboardButton("🟢 پایان و انتخاب برنده", callback_data=f"finish_{gid}")
        ])

    if is_admin(q.from_user.id):
        buttons.append([
            InlineKeyboardButton("⚙️ مدیریت برنده دستی", callback_data=f"manual_{gid}")
        ])

    buttons.append([InlineKeyboardButton("🔴 بازگشت", callback_data="mine")])

    await q.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def showlink_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    gid = int(q.data.rsplit("_", 1)[1])
    g = get_giveaway(gid)
    if not g:
        return
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=ref_{g['code']}_{g['owner_id']}"
    await q.edit_message_text(
        f"<b>لینک قرعه‌کشی</b>\n\n<blockquote><b>{esc(link)}</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 بازگشت", callback_data=f"manage_{gid}")]
        ]),
        disable_web_page_preview=True,
    )


# ============================================================
# ABOUT / ACCOUNT / LANGUAGE / SUPPORT / MORE / HELP
# ============================================================

async def about_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    text = (
        "<b>به 𝐖𝐢𝐧𝐳 خوش اومدی!</b>\n\n"
        "<blockquote>"
        "<b>این ربات یک پلتفرم حرفه‌ای برای ساخت و شرکت در قرعه‌کشی و گیوایه؛ "
        "جایی که می‌تونی خیلی راحت گیوای خودت رو بسازی، شرکت‌کننده جذب کنی "
        "و شانس برنده شدنت رو با فعالیت‌های مختلف افزایش بدی.</b>\n\n"
        "<b>از دعوت دوستان و بوست گرفته تا روش‌های مختلف کسب شانس، همه‌چیز "
        "اینجاست تا تجربه‌ای ساده، جذاب و عادلانه از گیواوی داشته باشی.</b>\n\n"
        "<b>ساده بساز، هوشمندانه شرکت کن و با شانس بیشتر برنده شو!</b>"
        "</blockquote>"
    )
    await q.edit_message_text(
        text, parse_mode=ParseMode.HTML, reply_markup=back_keyboard()
    )


async def account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = get_user(q.from_user.id)

    conn = db()
    joined = conn.execute(
        "SELECT COUNT(*) FROM participants WHERE user_id=?",
        (q.from_user.id,)
    ).fetchone()[0]
    refs = conn.execute(
        "SELECT COUNT(*) FROM referrals WHERE inviter_id=?",
        (q.from_user.id,)
    ).fetchone()[0]
    conn.close()

    status = "فعال" if u and u["premium"] else "عادی"

    text = (
        "<b>حساب کاربری</b>\n\n"
        "<blockquote>"
        "<b>خوش اومدی به حساب کاربریت!</b>\n"
        "<b>اینجا می‌تونی اطلاعات، شانس‌ها و فعالیت‌های خودت در گیواوی‌ها رو مشاهده و مدیریت کنی.</b>"
        "</blockquote>\n\n"
        f"<b>نام:</b> {esc(q.from_user.full_name)}\n"
        f"<b>یوزرنیم:</b> @{esc(q.from_user.username or 'ندارد')}\n"
        f"<b>آیدی:</b> <code>{q.from_user.id}</code>\n"
        f"<b>گیوای‌های شرکت‌کرده:</b> {joined}\n"
        f"<b>دعوت‌های موفق:</b> {refs}\n"
        f"<b>عضویت در ربات:</b> {esc(u['joined_at'] if u else '-')}\n"
        f"<b>وضعیت پرو:</b> {status}"
    )

    buttons = [[InlineKeyboardButton("🔴 بازگشت", callback_data="home")]]

    if is_admin(q.from_user.id):
        buttons.insert(0, [
            InlineKeyboardButton("⚙️ مدیریت ربات", callback_data="admin")
        ])

    await q.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "<b>انتخاب زبان</b>\n\n"
        "<blockquote><b>زبان مورد نظر خود را انتخاب کنید:</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔵 فارسی", callback_data="lang_fa")],
            [InlineKeyboardButton("🔵 English", callback_data="lang_en")],
            [InlineKeyboardButton("🔵 Русский", callback_data="lang_ru")],
            [InlineKeyboardButton("🔴 بازگشت", callback_data="home")],
        ]),
    )


async def lang_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("زبان ذخیره شد.")
    lang = q.data.replace("lang_", "")
    conn = db()
    conn.execute("UPDATE users SET language=? WHERE user_id=?", (lang, q.from_user.id))
    conn.commit()
    conn.close()
    await q.edit_message_text(
        "<b>زبان انتخابی ذخیره شد.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )


async def support_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    text = (
        "<b>پشتیبانی و ارتباط با مدیریت</b>\n\n"
        "<blockquote>"
        "<b>اگر مشکلی داری، سوالی برات پیش اومده یا پیشنهادی برای بهتر شدن ربات داری، "
        "مستقیم با مدیریت در ارتباط باش.</b>\n\n"
        "<b>مالک و پشتیبانی: @Mikilafee</b>\n"
        "<b>پاسخگویی: ۲۴ ساعته</b>\n\n"
        "<b>با خیال راحت پیام بده؛ پیگیری میشه.</b>"
        "</blockquote>"
    )
    await q.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 بازگشت", callback_data="home")]
        ]),
    )


async def more_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "<b>امکانات بیشتر</b>\n\n"
        "<blockquote>"
        "<b>قابلیت‌های خاص و امکانات ویژه‌ی ربات همین‌جاست.</b>\n"
        "<b>یکی رو انتخاب کن و لذتشو ببر!</b>"
        "</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔵 برترین‌ها", callback_data="top")],
            [InlineKeyboardButton("🔴 بازگشت", callback_data="home")],
        ]),
    )


async def top_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    conn = db()
    rows = conn.execute("""
        SELECT inviter_id, COUNT(*) AS cnt
        FROM referrals
        GROUP BY inviter_id
        ORDER BY cnt DESC
        LIMIT 10
    """).fetchall()
    conn.close()

    lines = ["<b>نفرات برتر رفرال</b>\n"]
    if not rows:
        lines.append("<blockquote><b>هنوز آماری ثبت نشده است.</b></blockquote>")
    else:
        for i, row in enumerate(rows, 1):
            lines.append(f"<b>{i}. کاربر {row['inviter_id']} — {row['cnt']} دعوت</b>")

    await q.edit_message_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 بازگشت", callback_data="more")]
        ]),
    )


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    text = (
        "<b>راهنمای کامل ربات</b>\n\n"
        "<b>╭───────────────╮</b>\n"
        "<b>خوش آمدید</b>\n"
        "<b>╰───────────────╯</b>\n\n"
        "<b>به ربات ما خوش اومدی!</b>\n\n"
        "<b>در این راهنما نحوه استفاده از بخش‌های مختلف ربات و همچنین مراحل ساخت "
        "و مدیریت قرعه‌کشی رو به صورت کامل توضیح دادیم.</b>\n\n"
        "<b>━━━━━━━━━━━━━━━━━━</b>\n"
        "<b>صفحه اصلی</b>\n"
        "<b>━━━━━━━━━━━━━━━━━━</b>\n\n"
        "<b>از صفحه اصلی می‌تونی به امکانات مختلف ربات دسترسی داشته باشی:</b>\n\n"
        "<b>قرعه‌کشی جدید</b>\n"
        "<b>ساخت یک قرعه‌کشی جدید و تعیین تنظیمات آن.</b>\n\n"
        "<b>قرعه‌کشی‌های فعال</b>\n"
        "<b>مشاهده قرعه‌کشی‌هایی که در حال حاضر فعال هستند.</b>\n\n"
        "<b>مدیریت قرعه‌کشی‌ها</b>\n"
        "<b>مشاهده و مدیریت قرعه‌کشی‌هایی که ایجاد کرده‌ای.</b>\n\n"
        "<b>پروفایل</b>\n"
        "<b>مشاهده اطلاعات و آمار حساب کاربری.</b>\n\n"
        "<b>برترین برندگان</b>\n"
        "<b>مشاهده آمار و رتبه‌بندی برندگان.</b>\n\n"
        "<b>درباره ربات</b>\n"
        "<b>مشاهده اطلاعات مربوط به ربات.</b>\n\n"
        "<b>پشتیبانی</b>\n"
        "<b>ارتباط با بخش پشتیبانی در صورت داشتن سؤال یا مشکل.</b>\n\n"
        "<b>━━━━━━━━━━━━━━━━━━</b>\n"
        "<b>آموزش ساخت قرعه‌کشی</b>\n"
        "<b>━━━━━━━━━━━━━━━━━━</b>\n\n"
        "<b>برای ساخت یک قرعه‌کشی جدید، از صفحه اصلی روی «قرعه‌کشی جدید» بزن "
        "و مراحل را به ترتیب انجام بده.</b>\n\n"
        "<b>━━━━━━━━━━━━━━━━━━</b>\n"
        "<b>انتخاب نام</b>\n"
        "<b>━━━━━━━━━━━━━━━━━━</b>\n\n"
        "<b>در این مرحله یک نام مناسب برای قرعه‌کشی وارد کن.</b>\n\n"
        "<b>مثال:</b>\n"
        "<b>قرعه‌کشی ویژه</b>\n"
        "<b>قرعه‌کشی استارز</b>\n"
        "<b>جشنواره ویژه</b>\n\n"
        "<b>━━━━━━━━━━━━━━━━━━</b>\n"
        "<b>تعیین جایزه</b>\n"
        "<b>━━━━━━━━━━━━━━━━━━</b>\n\n"
        "<b>جایزه یا عنوان جایزه را وارد کن.</b>\n"
        "<b>سعی کن اطلاعات جایزه واضح و دقیق نوشته شود تا شرکت‌کنندگان بدانند "
        "موضوع قرعه‌کشی چیست.</b>\n\n"
        "<b>━━━━━━━━━━━━━━━━━━</b>\n"
        "<b>تعیین مدت زمان</b>\n"
        "<b>━━━━━━━━━━━━━━━━━━</b>\n\n"
        "<b>مدت زمان فعال بودن قرعه‌کشی را مشخص کن.</b>\n"
        "<b>برای مثال: 30 دقیقه، 1 ساعت، 3 ساعت، 1 روز</b>\n"
        "<b>بعد از پایان زمان تعیین‌شده، قرعه‌کشی وارد مرحله پایان می‌شود.</b>\n\n"
        "<b>━━━━━━━━━━━━━━━━━━</b>\n"
        "<b>تعیین ظرفیت</b>\n"
        "<b>━━━━━━━━━━━━━━━━━━</b>\n\n"
        "<b>در این مرحله حداکثر تعداد شرکت‌کنندگان را مشخص کن.</b>\n"
        "<b>مثلاً: ظرفیت 100 نفر</b>\n"
        "<b>اگر ظرفیت تکمیل شود، امکان ثبت شرکت‌کننده جدید طبق تنظیمات قرعه‌کشی محدود می‌شود.</b>\n\n"
        "<b>━━━━━━━━━━━━━━━━━━</b>\n"
        "<b>تعیین تعداد برندگان</b>\n"
        "<b>━━━━━━━━━━━━━━━━━━</b>\n\n"
        "<b>تعداد برندگان موردنظر را مشخص کن.</b>\n"
        "<b>مثال: تعداد برندگان: 3 نفر</b>\n"
        "<b>تعداد برندگان باید با توجه به جایزه و شرایطی که تعیین کرده‌ای انتخاب شود.</b>\n\n"
        "<b>━━━━━━━━━━━━━━━━━━</b>"
    )

    await q.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )


# ============================================================
# ADMIN
# ============================================================

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await q.answer("دسترسی ندارید.", show_alert=True)
        return

    conn = db()
    users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    active = conn.execute(
        "SELECT COUNT(*) FROM giveaways WHERE status='active'"
    ).fetchone()[0]
    total = conn.execute(
        "SELECT COUNT(*) FROM giveaways"
    ).fetchone()[0]
    conn.close()

    text = (
        "<b>مدیریت ربات</b>\n\n"
        f"<b>تعداد کاربران:</b> {users}\n"
        f"<b>قرعه‌کشی‌های فعال:</b> {active}\n"
        f"<b>کل قرعه‌کشی‌ها:</b> {total}\n\n"
        "<blockquote><b>برای انتخاب برنده دستی، یک قرعه‌کشی را انتخاب کن.</b></blockquote>"
    )

    rows = get_active_giveaways()
    buttons = []
    for g in rows[:30]:
        buttons.append([
            InlineKeyboardButton(
                f"🎯 {g['title']}",
                callback_data=f"manual_{g['id']}"
            )
        ])
    buttons.append([InlineKeyboardButton("🔴 بازگشت", callback_data="account")])

    await q.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def manual_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await q.answer("دسترسی ندارید.", show_alert=True)
        return

    gid = int(q.data.rsplit("_", 1)[1])
    g = get_giveaway(gid)
    if not g:
        await q.answer("قرعه‌کشی پیدا نشد.", show_alert=True)
        return

    conn = db()
    rows = conn.execute("""
        SELECT p.user_id, u.username, u.first_name
        FROM participants p
        LEFT JOIN users u ON u.user_id=p.user_id
        WHERE p.giveaway_id=?
        ORDER BY p.joined_at ASC
    """, (gid,)).fetchall()
    conn.close()

    if not rows:
        await q.edit_message_text(
            "<b>شرکت‌کننده‌ای وجود ندارد.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard(),
        )
        return

    context.user_data["manual_gid"] = gid
    buttons = []
    for row in rows[:50]:
        name = row["username"] or row["first_name"] or str(row["user_id"])
        buttons.append([
            InlineKeyboardButton(
                f"👤 {name} ({row['user_id']})",
                callback_data=f"pickwinner_{gid}_{row['user_id']}"
            )
        ])

    buttons.append([InlineKeyboardButton("🔴 بازگشت", callback_data="admin")])

    await q.edit_message_text(
        f"<b>انتخاب برنده دستی</b>\n\n"
        f"<blockquote><b>{esc(g['title'])}\n"
        f"یکی از شرکت‌کنندگان را انتخاب کن.</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def pickwinner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        return

    _, gid_s, uid_s = q.data.split("_")
    gid = int(gid_s)
    uid = int(uid_s)

    g = get_giveaway(gid)
    if not g:
        return

    conn = db()
    conn.execute(
        "UPDATE giveaways SET manual_winners=? WHERE id=?",
        (str(uid), gid)
    )
    conn.commit()
    conn.close()

    await q.edit_message_text(
        "<b>برنده دستی ثبت شد.</b>\n\n"
        "<blockquote>"
        f"<b>قرعه‌کشی:</b> {esc(g['title'])}\n"
        f"<b>آیدی برنده:</b> <code>{uid}</code>\n\n"
        "<b>وقتی زمان قرعه تمام شود، همین کاربر به عنوان برنده اعلام خواهد شد.</b>"
        "</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 بازگشت", callback_data="admin")]
        ]),
    )


# ============================================================
# FINISH / WINNER
# ============================================================

async def finish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    gid = int(q.data.rsplit("_", 1)[1])
    g = get_giveaway(gid)
    if not g:
        return

    if g["owner_id"] != q.from_user.id and not is_admin(q.from_user.id):
        await q.answer("فقط سازنده یا مدیر می‌تواند پایان دهد.", show_alert=True)
        return

    await finish_giveaway(gid, context, force=True)
    g = get_giveaway(gid)

    await q.edit_message_text(
        "<b>قرعه‌کشی پایان یافت.</b>\n\n" + giveaway_card(g),
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )


async def finish_giveaway(gid, context, force=False):
    g = get_giveaway(gid)
    if not g or g["status"] != "active":
        return

    # context می‌تواند ContextTypes.DEFAULT_TYPE یا خود Bot باشد.
    bot = getattr(context, "bot", context)

    if not force and parse_dt(g["ends_at"]) > now():
        return

    count = participant_count(gid)
    if count < g["minimum"]:
        conn = db()
        conn.execute(
            "UPDATE giveaways SET status='cancelled' WHERE id=?",
            (gid,)
        )
        conn.commit()
        conn.close()

        await notify_owner(
            g,
            bot,
            "قرعه‌کشی به حداقل شرکت‌کننده نرسید و لغو شد."
        )
        return

    conn = db()
    rows = conn.execute("""
        SELECT user_id FROM participants
        WHERE giveaway_id=?
    """, (gid,)).fetchall()

    manual = []
    if g["manual_winners"]:
        try:
            manual = [int(x) for x in g["manual_winners"].split(",") if x.strip()]
        except Exception:
            manual = []

    ids = [r["user_id"] for r in rows]

    winners = []
    for uid in manual:
        if uid in ids and uid not in winners:
            winners.append(uid)

    remaining = [uid for uid in ids if uid not in winners]
    needed = max(0, g["winners_count"] - len(winners))

    if needed:
        if len(remaining) <= needed:
            winners.extend(remaining)
        else:
            winners.extend(random.sample(remaining, needed))

    conn.execute(
        "UPDATE giveaways SET status='finished' WHERE id=?",
        (gid,)
    )

    for pos, uid in enumerate(winners, 1):
        conn.execute("""
            INSERT OR REPLACE INTO winners(
                giveaway_id, user_id, position, announced_at
            )
            VALUES (?, ?, ?, ?)
        """, (gid, uid, pos, iso(now())))

    conn.commit()
    conn.close()

    await announce_winners(g, winners, bot)


async def announce_winners(g, winners, bot):
    bot_username = (await bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=ref_{g['code']}_{g['owner_id']}"

    if not winners:
        text = (
            f"<b>قرعه‌کشی «{esc(g['title'])}» پایان یافت.</b>\n\n"
            "<blockquote><b>برنده‌ای برای اعلام وجود ندارد.</b></blockquote>"
        )
    else:
        lines = []
        for i, uid in enumerate(winners, 1):
            lines.append(f"<b>{i}. <code>{uid}</code></b>")

        text = (
            f"<b>قرعه‌کشی «{esc(g['title'])}» به پایان رسید!</b>\n\n"
            f"<b>جایزه:</b> {esc(g['prize'])}\n"
            f"<b>برندگان:</b>\n"
            + "\n".join(lines)
            + "\n\n"
            f"<b>لینک قرعه‌کشی:</b>\n{esc(link)}"
        )

    await bot.send_message(
        g["owner_id"],
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    for uid in winners:
        try:
            await bot.send_message(
                uid,
                "<b>تبریک! شما برنده شدید.</b>\n\n" + text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass


async def notify_owner(g, bot, message):
    try:
        await bot.send_message(
            g["owner_id"],
            f"<b>{esc(message)}</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


async def expiration_worker(app):
    while True:
        try:
            rows = get_active_giveaways()
            for g in rows:
                if parse_dt(g["ends_at"]) <= now():
                    await finish_giveaway(g["id"], app.bot)
        except Exception:
            logger.exception("expiration worker error")
        await asyncio.sleep(10)


# ============================================================
# CALLBACK ROUTER
# ============================================================

async def generic_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data

    if data == "home":
        return await home_callback(update, context)
    if data == "new":
        return await new_callback(update, context)
    if data == "mine":
        return await mine_callback(update, context)
    if data == "active":
        return await active_callback(update, context)
    if data == "about":
        return await about_callback(update, context)
    if data == "account":
        return await account_callback(update, context)
    if data == "language":
        return await language_callback(update, context)
    if data.startswith("lang_"):
        return await lang_set_callback(update, context)
    if data == "support":
        return await support_callback(update, context)
    if data == "more":
        return await more_callback(update, context)
    if data == "top":
        return await top_callback(update, context)
    if data == "help":
        return await help_callback(update, context)
    if data == "admin":
        return await admin_callback(update, context)
    if data.startswith("manual_"):
        return await manual_callback(update, context)
    if data.startswith("pickwinner_"):
        return await pickwinner_callback(update, context)
    if data.startswith("manage_"):
        return await manage_callback(update, context)
    if data.startswith("showlink_"):
        return await showlink_callback(update, context)
    if data.startswith("finish_"):
        return await finish_callback(update, context)
    if data.startswith("back_g_"):
        return await back_giveaway(update, context)
    if data.startswith("join_") or data.startswith("ref_link_") or data.startswith("publish_"):
        return await giveaway_button(update, context)

    # ساخت قرعه
    if data.startswith("dur_"):
        return await duration_callback(update, context)
    if data.startswith("cap_"):
        return await capacity_callback(update, context)
    if data.startswith("win_"):
        return await winners_callback(update, context)
    if data.startswith("min_"):
        return await minimum_callback(update, context)
    if data.startswith("access_"):
        return await access_callback(update, context)
    if data.startswith("channels_"):
        return await channel_count_callback(update, context)
    if data in ("ref_yes", "ref_no"):
        return await referral_callback(update, context)
    if data.startswith("reflimit_"):
        return await referral_limit_callback(update, context)
    if data.startswith("prize_"):
        return await prize_callback(update, context)
    if data.startswith("security_"):
        return await security_callback(update, context)
    if data.startswith("method_"):
        return await winner_method_callback(update, context)

    if data == "cancel_create":
        await q.answer("ساخت قرعه‌کشی لغو شد.")
        context.user_data.clear()
        await send_home(q)
        return ConversationHandler.END

    if data == "prev":
        await q.answer()
        await q.edit_message_text(
            "<b>مرحله قبل</b>\n\n"
            "<blockquote><b>لطفاً مرحله قبلی را دوباره انتخاب کنید.</b></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔵 ادامه ساخت قرعه‌کشی", callback_data="new")],
                [InlineKeyboardButton("🔴 لغو", callback_data="cancel_create")]
            ])
        )
        return

    await q.answer()


# ============================================================
# ERROR
# ============================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled exception:", exc_info=context.error)


# ============================================================
# MAIN
# ============================================================

async def post_init(app: Application):
    init_db()
    app.create_task(expiration_worker(app))


def main():
    if BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        print("ERROR: BOT_TOKEN را داخل فایل bot.py قرار بده.")
        return

    init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # start
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_callback))

    # Conversation ساخت قرعه‌کشی
    create_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(new_callback, pattern=r"^new$")
        ],
        states={
            S_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_name)
            ],
            S_DURATION: [
                CallbackQueryHandler(duration_callback, pattern=r"^dur_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, duration_manual),
            ],
            S_CAPACITY: [
                CallbackQueryHandler(capacity_callback, pattern=r"^cap_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, capacity_manual),
            ],
            S_WINNERS: [
                CallbackQueryHandler(winners_callback, pattern=r"^win_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, winners_manual),
            ],
            S_MINIMUM: [
                CallbackQueryHandler(minimum_callback, pattern=r"^min_"),
            ],
            S_ACCESS: [
                CallbackQueryHandler(access_callback, pattern=r"^access_"),
            ],
            S_CHANNEL_COUNT: [
                CallbackQueryHandler(channel_count_callback, pattern=r"^channels_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, channel_count_manual),
            ],
            S_CHANNELS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, channel_input),
            ],
            S_REFERRAL: [
                CallbackQueryHandler(referral_callback, pattern=r"^ref_(yes|no)$"),
            ],
            S_REF_LIMIT: [
                CallbackQueryHandler(referral_limit_callback, pattern=r"^reflimit_"),
            ],
            S_PRIZE: [
                CallbackQueryHandler(prize_callback, pattern=r"^prize_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, prize_manual),
            ],
            S_SECURITY: [
                CallbackQueryHandler(security_callback, pattern=r"^security_"),
            ],
            S_WINNER_METHOD: [
                CallbackQueryHandler(winner_method_callback, pattern=r"^method_"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(
                lambda update, context: cancel_conversation(update, context),
                pattern=r"^cancel_create$"
            ),
        ],
        allow_reentry=True,
    )

    application.add_handler(create_conv)

    # callback عمومی
    application.add_handler(
        CallbackQueryHandler(generic_callback)
    )

    # پاسخ سوال امنیتی
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            math_answer
        )
    )

    application.add_error_handler(error_handler)

    print("ViLd Winz Bot is running...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


async def cancel_conversation(update, context):
    q = update.callback_query
    await q.answer("لغو شد.")
    context.user_data.clear()
    await send_home(q)
    return ConversationHandler.END


if __name__ == "__main__":
    main()
