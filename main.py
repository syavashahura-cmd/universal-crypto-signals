import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
import json

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    PreCheckoutQuery
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    PreCheckoutQueryHandler
)
from telegram.constants import ParseMode
import aiomysql
from ton import ToncenterClient

# ====================== CONFIGURATION ======================
BOT_TOKEN = "7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # از @BotFather
TON_MASTER_WALLET = "UQC8oNGKujcu7QFJ5YDfMq7AO-IOqFO923YGAy0Ci75GBZSh"
TON_API_KEY = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"  # از toncenter.com
TON_TESTNET = False
ADMIN_ID = 159895496
VIP_CHANNEL_LINK = "https://t.me/+your_private_vip_channel_here"
SUPPORT_USERNAME = "@hormuz1991_70"

# دیتابیس (محلی یا سرور)
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',           # تغییر دهید
    'password': '',           # رمز دیتابیس
    'db': 'crypto_signal_bot',
    'autocommit': True
}

# پلن‌ها
PLANS = {
    "1": {"months": 1, "ton": Decimal("1.0"), "label": "1 Month - 1 TON"},
    "3": {"months": 3, "ton": Decimal("2.0"), "label": "3 Months - 2 TON"},
    "6": {"months": 6, "ton": Decimal("3.5"), "label": "6 Months - 3.5 TON"},
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# TON Client
ton_client = ToncenterClient(api_key=TON_API_KEY, testnet=TON_TESTNET)
# ==========================================================

# === DATABASE HELPERS ===
async def get_db():
    return await aiomysql.connect(**DB_CONFIG)

async def ensure_user(user_id, username=None, first_name=None):
    conn = await get_db()
    async with conn.cursor() as cur:
        await cur.execute("""
            INSERT INTO users (user_id, username, first_name) 
            VALUES (%s, %s, %s) 
            ON DUPLICATE KEY UPDATE username=%s, first_name=%s
        """, (user_id, username, first_name, username, first_name))
    conn.close()

async def get_user(user_id):
    conn = await get_db()
    async with conn.cursor(dictionary=True) as cur:
        await cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        user = await cur.fetchone()
    conn.close()
    return user

async def update_user(user_id, **kwargs):
    conn = await get_db()
    set_clause = ", ".join([f"{k}=%s" for k in kwargs])
    values = list(kwargs.values()) + [user_id]
    async with conn.cursor() as cur:
        await cur.execute(f"UPDATE users SET {set_clause} WHERE user_id = %s", values)
    conn.close()

# === TON PAYMENT CHECKER ===
async def check_ton_payment(expected_amount: Decimal, user_id: int):
    try:
        transactions = await ton_client.get_transactions(TON_MASTER_WALLET, limit=10)
        for tx in transactions:
            if 'in_msg' not in tx or 'value' not in tx['in_msg']:
                continue
            value = Decimal(tx['in_msg']['value']) / Decimal(1_000_000_000)
            if value >= expected_amount and tx['in_msg'].get('destination') == TON_MASTER_WALLET:
                # ثبت پرداخت
                conn = await get_db()
                async with conn.cursor() as cur:
                    await cur.execute("""
                        INSERT INTO payments (user_id, tx_hash, amount, plan_months, status)
                        VALUES (%s, %s, %s, %s, 'confirmed')
                        ON DUPLICATE KEY UPDATE status='confirmed'
                    """, (user_id, tx['hash'], float(value), 1))
                conn.close()
                return True
        return False
    except Exception as e:
        logger.error(f"TON check error: {e}")
        return False

# === KEYBOARDS ===
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("My Account & Subscriptions", callback_data="account")],
        [InlineKeyboardButton("Signal Settings", callback_data="settings")],
        [InlineKeyboardButton("Help & Support", callback_data="help")]
    ])

def account_menu(user):
    buttons = [
        [InlineKeyboardButton("My Subscription Status", callback_data="status")],
        [InlineKeyboardButton("Buy/Renew VIP Access", callback_data="buy")]
    ]
    if user['membership'] == 'vip' and user['vip_expiry']:
        expiry = datetime.fromisoformat(user['vip_expiry'].replace('Z', '+00:00'))
        if expiry > datetime.utcnow():
            buttons.append([InlineKeyboardButton("VIP Channel Link", callback_data="vip_link")])
    buttons.append([InlineKeyboardButton("Back", callback_data="back")])
    return InlineKeyboardMarkup(buttons)

def buy_menu():
    buttons = [[InlineKeyboardButton(p["label"], callback_data=f"pay_{k}")] for k, p in PLANS.items()]
    buttons.append([InlineKeyboardButton("Back", callback_data="account")])
    return InlineKeyboardMarkup(buttons)

# === HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await ensure_user(user.id, user.username, user.full_name)
    text = (
        "*Welcome to Crypto Signal Bot*!\n\n"
        "We support *300+ reliable cryptocurrencies*.\n"
        "Success comes from *Discipline in Execution*.\n\n"
        "You get *5 Free Trial Signals* to start!\n"
        "Use the menu below to explore."
    )
    await update.message.reply_text(text, reply_markup=main_menu(), parse_mode=ParseMode.MARKDOWN)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    user = await get_user(user_id)

    if data == "back":
        await query.edit_message_text("Main Menu:", reply_markup=main_menu())
    elif data == "account":
        await query.edit_message_text("*My Account*", reply_markup=account_menu(user), parse_mode=ParseMode.MARKDOWN)
    elif data == "status":
        expiry = user['vip_expiry']
        if user['membership'] == 'vip' and expiry:
            days_left = (datetime.fromisoformat(expiry.replace('Z', '+00:00')) - datetime.utcnow()).days
            status = f"VIP Active • Expires in {days_left} days"
        else:
            status = "Free / Trial"
        text = (
            f"*Subscription Status*\n\n"
            f"Level: `{user['membership'].upper()}`\n"
            f"Trial Signals Used: `{user['trial_signals_used']}/5`\n"
            f"Status: {status}"
        )
        await query.edit_message_text(text, reply_markup=account_menu(user), parse_mode=ParseMode.MARKDOWN)
    elif data == "buy":
        await query.edit_message_text("*Choose VIP Plan*", reply_markup=buy_menu(), parse_mode=ParseMode.MARKDOWN)
    elif data.startswith("pay_"):
        plan_key = data.split("_")[1]
        plan = PLANS[plan_key]
        invoice_text = (
            f"*VIP Subscription*\n"
            f"Plan: {plan['label']}\n"
            f"Amount: `{plan['ton']}` TON\n\n"
            f"Send exactly `{plan['ton']}` TON to:\n"
            f"`{TON_MASTER_WALLET}`\n\n"
            f"_We will auto-detect and activate your access in <60 seconds._"
        )
        await query.edit_message_text(invoice_text, parse_mode=ParseMode.MARKDOWN)
        context.user_data['pending_plan'] = plan_key
        context.user_data['pending_time'] = datetime.utcnow()
    elif data == "vip_link":
        await query.edit_message_text(f"VIP Channel:\n{VIP_CHANNEL_LINK}", parse_mode=ParseMode.MARKDOWN)
    elif data == "help":
        text = (
            "*Help & Support*\n\n"
            "*Signal Execution Guide*\n"
            "1. *No Emotion* – Follow SL/TP exactly.\n"
            "2. *One Entry Only* – Never average down.\n"
            "3. *Risk 1%* – Protect your capital.\n\n"
            "*FAQ*\n"
            "• How do I get signals? → After VIP activation.\n"
            "• Where is the VIP channel? → Use 'VIP Channel Link'\n\n"
            f"*Contact Support:* {SUPPORT_USERNAME}"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))

# === ADMIN PANEL ===
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Access denied.")
        return
    await update.message.reply_text(
        "*Admin Panel*",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Signal Management", callback_data="admin_signal")],
            [InlineKeyboardButton("User Management", callback_data="admin_user")],
            [InlineKeyboardButton("Analytics", callback_data="admin_stats")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

# === PAYMENT WATCHER ===
async def payment_watcher(application: Application):
    while True:
        conn = await get_db()
        async with conn.cursor(dictionary=True) as cur:
            await cur.execute("""
                SELECT DISTINCT user_id FROM payments 
                WHERE status = 'pending' AND created_at > NOW() - INTERVAL 10 MINUTE
            """)
            pending_users = await cur.fetchall()
        conn.close()

        for row in pending_users:
            user_id = row['user_id']
            user = await get_user(user_id)
            if user['membership'] == 'vip':
                continue
            # فرض: آخرین پلن در دیتابیس
            conn = await get_db()
            async with conn.cursor(dictionary=True) as cur:
                await cur.execute("SELECT amount, plan_months FROM payments WHERE user_id=%s ORDER BY id DESC LIMIT 1", (user_id,))
                pay = await cur.fetchone()
            conn.close()
            if not pay:
                continue
            confirmed = await check_ton_payment(Decimal(pay['amount']), user_id)
            if confirmed:
                months = pay['plan_months']
                expiry = datetime.utcnow() + timedelta(days=30 * months)
                await update_user(user_id, membership='vip', vip_expiry=expiry.isoformat())
                try:
                    await application.bot.send_message(
                        user_id,
                        f"*VIP Activated!*\nPlan: {months} month(s)\nExpires: {expiry.strftime('%Y-%m-%d')}\n\n{VIP_CHANNEL_LINK}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except:
                    pass
        await asyncio.sleep(30)

# === MAIN ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(PreCheckoutQueryHandler(lambda u, c: True))

    app.job_queue.run_repeating(payment_watcher, interval=30, first=10)

    print("Crypto Signal Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
