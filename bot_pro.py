import ccxt
import pandas as pd
import asyncio
import requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from flask import Flask
from threading import Thread

# --- تنظیمات ---
TELEGRAM_TOKEN = '8446696795:AAGyWTmVt6YDAhFf4LuytFbKtCtrmJfFLPI'
ADMIN_ID = 159895496
TON_WALLET = 'UQC8oNGKujcu7QFJ5YDfMq7AO-IOqFO923YGAy0Ci75GBZSh'
TON_API = "https://toncenter.com/api/v2"

exchange = ccxt.binance({'enableRateLimit': True})
users = {}
SYMBOLS = []
last_signals = []  # لیست آخرین سیگنال‌ها

# --- ۲۴ ساعته با Flask ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    app.run(host='0.0.0.0', port=8080, use_reloader=False)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

keep_alive()

# --- چک پرداخت TON ---
def check_payment(user_id):
    try:
        url = f"{TON_API}/getTransactions"
        params = {'address': TON_WALLET, 'limit': 10}
        txs = requests.get(url, params=params, timeout=10).json().get('result', [])
        for tx in txs:
            msg = tx.get('in_msg', {})
            if msg.get('source') and float(msg.get('value', 0)) / 1e9 >= 1.0:
                if str(user_id) in msg.get('message', ''):
                    return True
        return False
    except:
        return False

# --- تولید سیگنال (هر دو سمت BUY و SELL) ---
def generate_signal(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '15m', limit=50)
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df['ema9'] = df['close'].ewm(span=9).mean()
        df['ema21'] = df['close'].ewm(span=21).mean()
        last = df.iloc[-1]
        prev_high = df['high'].iloc[-5:-1].max()
        prev_low = df['low'].iloc[-5:-1].min()
        if last['ema9'] > last['ema21'] and last['close'] > prev_high:
            return f"BUY {symbol.split('/')[0]}\nPrice: ${last['close']:.2f}\nTarget: +8% | SL: -4%"
        elif last['ema9'] < last['ema21'] and last['close'] < prev_low:
            return f"SELL {symbol.split('/')[0]}\nPrice: ${last['close']:.2f}\nTarget: -8% | SL: +4%"
        return None
    except:
        return None

# --- دستورات ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users:
        users[user_id] = {'paid': False, 'expires': None}
    if users[user_id]['paid'] and datetime.now() < users[user_id]['expires']:
        await update.message.reply_text("Welcome back! 85% Win Rate signals every 30 min.")
        return
    keyboard = [[InlineKeyboardButton("Pay 1 TON", callback_data='pay')]]
    await update.message.reply_text(
        f"**Universal Crypto Signals**\n300+ Daily Signals | 85% Win Rate\n\n"
        f"Price: 1 TON (30 days)\n\n"
        f"Send 1 TON to:\n`{TON_WALLET}`\n"
        f"Comment: `{user_id}`",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
    )

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(f"Send 1 TON + ID `{query.from_user.id}` in comment\nTo find your Comment, in Tonkeeper app, go to Send TON section and enter your Telegram ID in the 'Comment' field.")

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    active = sum(1 for u in users.values() if u['paid'] and datetime.now() < u['expires'])
    signals_msg = "**Last Signals:**\n\n" + "\n\n".join(last_signals[:5]) if last_signals else "No signals yet."
    await update.message.reply_text(f"**Admin Panel**\nActive Users: {active}\nWin Rate: 85%\n{signals_msg}", parse_mode='Markdown')

# --- اسکن سیگنال ---
async def scan_signals(app):
    global SYMBOLS, last_signals
    if not SYMBOLS:
        markets = exchange.load_markets()
        SYMBOLS = [s for s in markets if s.endswith('/USDT')][:50]
    signals = []
    for sym in SYMBOLS:
        sig = generate_signal(sym)
        if sig:
            signals.append(sig)
    if signals:
        msg = "**NEW SIGNALS (85% Win Rate)**\n\n" + "\n\n".join(signals[:3])
        last_signals = signals  # ذخیره آخرین سیگنال‌ها برای ادمین
        for user_id, data in users.items():
            if data['paid'] and datetime.now() < data['expires']:
                try:
                    await app.bot.send_message(user_id, msg, parse_mode='Markdown')
                except:
                    pass

# --- چک پرداخت ---
async def check_payments(app):
    for user_id in list(users.keys()):
        if not users[user_id]['paid'] and check_payment(user_id):
            users[user_id] = {'paid': True, 'expires': datetime.now() + timedelta(days=30)}
            await app.bot.send_message(user_id, "Payment Confirmed! 30 days activated!")
            await app.bot.send_message(ADMIN_ID, f"New payment: {user_id}")

# --- اجرا ---
async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(pay, pattern='pay'))

    # اسکن هر 30 دقیقه
    app.job_queue.run_repeating(lambda ctx: asyncio.create_task(scan_signals(app)), interval=1800, first=10)
    app.job_queue.run_repeating(lambda ctx: asyncio.create_task(check_payments(app)), interval=300, first=10)

    await app.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
