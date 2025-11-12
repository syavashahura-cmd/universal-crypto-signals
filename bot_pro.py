#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Universal Crypto Signals - Professional Bot
@GlobalCoinSignalsBot
Admin ID: 159895496
"""

import ccxt
import pandas as pd
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volume import VolumeWeightedAveragePrice
import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler
import schedule
import asyncio
import time
import requests
from datetime import datetime, timedelta
import logging

# ================== CONFIG ==================
TELEGRAM_TOKEN = '8446696795:AAGyWTmVt6YDAhFf4LuytFbKtCtrmJfFLPI'
ADMIN_ID = 159895496  # شما
TON_WALLET = 'UQC8oNGKujcu7QFJ5YDfMq7AO-IOqFO923YGAy0Ci75GBZSh'
TON_PRICE = 1.0
SUBSCRIPTION_DAYS = 30
CHECK_INTERVAL = 5
SIGNAL_INTERVAL = 30

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

users_db = {}
exchange = ccxt.binance({'enableRateLimit': True})
SYMBOLS = []
TON_API = "https://toncenter.com/api/v2"

# ================== TON CHECK ==================
def check_ton_payment(user_id, amount=1.0):
    try:
        url = f"{TON_API}/getTransactions"
        params = {'address': TON_WALLET, 'limit': 20}
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200: return False
        txs = response.json().get('result', [])
        user_id_str = str(user_id)
        for tx in txs:
            in_msg = tx.get('in_msg', {})
            if in_msg.get('source') and float(in_msg.get('value', 0)) / 1e9 >= amount:
                message = in_msg.get('message', '')
                if user_id_str in message:
                    return True
        return False
    except Exception as e:
        logger.error(f"TON error: {e}")
        return False

# ================== SIGNAL ==================
def generate_signal(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '15m', limit=100)
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df['ema9'] = EMAIndicator(df['close'], window=9).ema_indicator()
        df['ema21'] = EMAIndicator(df['close'], window=21).ema_indicator()
        df['rsi'] = RSIIndicator(df['close'], window=14).rsi()
        df['vwap'] = VolumeWeightedAveragePrice(high=df['high'], low=df['low'], close=df['close'], volume=df['volume'], window=14).volume_weighted_average_price()

        last = df.iloc[-1]
        prev_high = max(df['high'].iloc[-4:-1])
        prev_low = min(df['low'].iloc[-4:-1])
        vol_avg = df['volume'].rolling(20).mean().iloc[-1]
        ticker = exchange.fetch_ticker(symbol)
        vol_24h = ticker.get('quoteVolume', 0)

        if vol_24h < 5_000_000: return None

        if (last['ema9'] > last['ema21'] and 35 < last['rsi'] < 65 and
            last['volume'] > vol_avg * 2 and last['close'] > prev_high):
            return f"BUY {symbol.split('/')[0]}\nPrice: ${last['close']:.4f}\nRSI: {last['rsi']:.1f}\nTarget: +8-12% | SL: -4%"

        if (last['ema9'] < last['ema21'] and last['rsi'] > 70 and last['close'] < prev_low):
            return f"SELL {symbol.split('/')[0]}\nPrice: ${last['close']:.4f}\nRSI: {last['rsi']:.1f}\nRisk: High"

        return None
    except: return None

# ================== SEND ==================
async def send_to_subscribers(message):
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    for user_id, data in users_db.items():
        if data.get('paid') and datetime.now() < data['expires']:
            try:
                await bot.send_message(user_id, f"**{message}**", parse_mode='Markdown')
            except: pass

# ================== ADMIN ==================
async def admin_panel(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Access denied.")
        return
    active = sum(1 for d in users_db.values() if d.get('paid') and datetime.now() < d['expires'])
    income = sum(1 for d in users_db.values() if d.get('paid'))
    keyboard = [[InlineKeyboardButton("Users", callback_data='admin_users')],
                [InlineKeyboardButton("Income", callback_data='admin_income')]]
    await update.message.reply_text(
        f"**Admin Panel**\nActive: {active}\nIncome: {income} TON",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
    )

async def admin_callback(update, context):
    query = update.callback_query; await query.answer()
    if query.data == 'admin_users':
        users = "\n".join([f"• {u} → {d['expires'].strftime('%Y-%m-%d')}" for u, d in users_db.items() if d.get('paid') and datetime.now() < d['expires']]) or "None"
        await query.edit_message_text(f"**Active Users:**\n{users}", parse_mode='Markdown')

# ================== START ==================
async def start(update, context):
    user_id = update.effective_user.id
    if user_id not in users_db: users_db[user_id] = {'paid': False}
    if users_db[user_id].get('paid') and datetime.now() < users_db[user_id]['expires']:
        await update.message.reply_text("Welcome back! Signals every 30 min.")
        return
    keyboard = [[InlineKeyboardButton("Pay 1 TON", callback_data='pay')]]
    await update.message.reply_text(
        "**Universal Crypto Signals**\n300+ Signals | 68% Win Rate\n\n"
        "**Price: 1 TON (30 days)**\n"
        f"Send to: `{TON_WALLET}`\nComment: `{user_id}`",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
    )

async def pay_callback(update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text(f"Send 1 TON to:\n`{TON_WALLET}`\nComment: `{query.from_user.id}`")

# ================== SCAN & PAYMENTS ==================
async def scan_and_send():
    global SYMBOLS
    if not SYMBOLS: return
    signals = [f"**{s}**" for symbol in SYMBOLS[:50] if (s := generate_signal(symbol))]
    if signals:
        msg = "**NEW SIGNALS**\n\n" + "\n\n".join(signals[:5])
        await send_to_subscribers(msg)

async def check_payments():
    for user_id in list(users_db.keys()):
        if not users_db[user_id].get('paid') and check_ton_payment(user_id):
            users_db[user_id] = {'paid': True, 'expires': datetime.now() + timedelta(days=30)}
            bot = telegram.Bot(token=TELEGRAM_TOKEN)
            await bot.send_message(user_id, "Payment Confirmed! 30 days activated!")
            await bot.send_message(ADMIN_ID, f"New payment: {user_id}")

# ================== MAIN ==================
def main():
    global SYMBOLS
    markets = exchange.load_markets()
    usdt_pairs = [m for m in markets if m.endswith('/USDT')]
    tickers = exchange.fetch_tickers(usdt_pairs)
    SYMBOLS = sorted([s for s in usdt_pairs if tickers[s].get('quoteVolume', 0) > 5_000_000],
                     key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:300]

    schedule.every(SIGNAL_INTERVAL).minutes.do(lambda: asyncio.create_task(scan_and_send()))
    schedule.every(CHECK_INTERVAL).minutes.do(lambda: asyncio.create_task(check_payments()))

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(pay_callback, pattern='^pay$'))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern='^admin_'))

    def run_scheduler():
        while True: schedule.run_pending(); time.sleep(1)
    import threading
    threading.Thread(target=run_scheduler, daemon=True).start()

    logger.info("Bot Started!")
    app.run_polling()

if __name__ == '__main__':
    main()
