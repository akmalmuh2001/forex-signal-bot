"""
===========================================
BOT SINYAL FOREX - XAU/USD M15
Indikator: MA, RSI, MACD, BB, SMC, Liquidity Sweep
===========================================
CARA PAKAI:
1. Install library: pip install python-telegram-bot requests pandas pandas-ta apscheduler
2. Isi YOUR_API_KEY, YOUR_BOT_TOKEN, YOUR_CHAT_ID di bawah
3. Jalankan: python forex_signal_bot.py
===========================================
"""

import requests
import pandas as pd
import pandas_ta as ta
import asyncio
from telegram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime

# ==========================================
# ⚙️ KONFIGURASI - ISI DI SINI
# ==========================================
TWELVE_DATA_API_KEY = "df0a98d8c807459895368b9c1653e603"       # Ganti dengan API key Twelve Data
TELEGRAM_BOT_TOKEN  = "8777382374:AAFg76BV85Mur8N09lCww7gckfoVyHDk38I"     # Ganti dengan token dari BotFather
TELEGRAM_CHAT_ID    = "6679472360"       # Ganti dengan Chat ID kamu

SYMBOL    = "XAU/USD"
INTERVAL  = "15min"
OUTPUTSIZE = 100   # jumlah candle yang diambil
# ==========================================


def get_price_data():
    """Ambil data harga dari Twelve Data API"""
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "outputsize": OUTPUTSIZE,
        "apikey": TWELVE_DATA_API_KEY,
        "format": "JSON"
    }
    response = requests.get(url, params=params, timeout=10)
    data = response.json()

    if "values" not in data:
        raise Exception(f"Error ambil data: {data.get('message', 'Unknown error')}")

    df = pd.DataFrame(data["values"])
    df = df.rename(columns={
        "open": "open", "high": "high",
        "low": "low", "close": "close", "volume": "volume"
    })
    df = df.astype({"open": float, "high": float, "low": float, "close": float})
    df = df.iloc[::-1].reset_index(drop=True)  # urut dari lama ke baru
    return df


def calculate_indicators(df):
    """Hitung semua indikator teknikal"""

    # --- Moving Average ---
    df["ma20"]  = ta.sma(df["close"], length=20)
    df["ma50"]  = ta.sma(df["close"], length=50)
    df["ema9"]  = ta.ema(df["close"], length=9)

    # --- RSI ---
    df["rsi"] = ta.rsi(df["close"], length=14)

    # --- MACD ---
    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    df["macd"]        = macd["MACD_12_26_9"]
    df["macd_signal"] = macd["MACDs_12_26_9"]
    df["macd_hist"]   = macd["MACDh_12_26_9"]

    # --- Bollinger Bands ---
    bb = ta.bbands(df["close"], length=20, std=2)
    # Cari nama kolom yang tersedia (berbeda tiap versi pandas-ta)
    bb_cols = bb.columns.tolist()
    upper_col = [c for c in bb_cols if c.startswith("BBU")][0]
    mid_col   = [c for c in bb_cols if c.startswith("BBM")][0]
    lower_col = [c for c in bb_cols if c.startswith("BBL")][0]
    df["bb_upper"] = bb[upper_col]
    df["bb_mid"]   = bb[mid_col]
    df["bb_lower"] = bb[lower_col]

    return df


def detect_smc(df):
    """
    Deteksi Smart Money Concept (SMC):
    - Break of Structure (BOS)
    - Change of Character (CHoCH)
    - Order Block (OB)
    """
    signals = []
    last  = df.iloc[-1]
    prev  = df.iloc[-2]
    prev2 = df.iloc[-3]

    # Break of Structure BULLISH
    # Harga baru break high sebelumnya
    if last["close"] > prev2["high"] and prev["close"] < prev2["high"]:
        signals.append("📈 BOS Bullish - Break of Structure ke atas")

    # Break of Structure BEARISH
    if last["close"] < prev2["low"] and prev["close"] > prev2["low"]:
        signals.append("📉 BOS Bearish - Break of Structure ke bawah")

    # CHoCH - Change of Character
    # Setelah downtrend, muncul higher high
    if (prev2["close"] < prev2["open"] and   # candle merah
        prev["close"]  < prev["open"]  and   # candle merah
        last["close"]  > last["open"]  and   # candle hijau
        last["close"]  > prev["high"]):      # break high
        signals.append("🔄 CHoCH Bullish - Potensi pembalikan naik")

    # CHoCH bearish
    if (prev2["close"] > prev2["open"] and
        prev["close"]  > prev["open"]  and
        last["close"]  < last["open"]  and
        last["close"]  < prev["low"]):
        signals.append("🔄 CHoCH Bearish - Potensi pembalikan turun")

    # Order Block Bullish: candle merah besar diikuti naik kuat
    if (prev["close"] < prev["open"] and
        (prev["open"] - prev["close"]) > (prev["high"] - prev["low"]) * 0.6 and
        last["close"] > prev["open"]):
        signals.append("🟢 Order Block Bullish teridentifikasi")

    # Order Block Bearish: candle hijau besar diikuti turun kuat
    if (prev["close"] > prev["open"] and
        (prev["close"] - prev["open"]) > (prev["high"] - prev["low"]) * 0.6 and
        last["close"] < prev["open"]):
        signals.append("🔴 Order Block Bearish teridentifikasi")

    return signals


def detect_liquidity_sweep(df):
    """
    Deteksi Liquidity Sweep:
    - Harga spike menembus level high/low sebelumnya lalu kembali (manipulasi)
    """
    signals = []
    last  = df.iloc[-1]
    prev  = df.iloc[-2]

    # Ambil high/low 20 candle terakhir (kecuali 2 terakhir)
    recent = df.iloc[-22:-2]
    swing_high = recent["high"].max()
    swing_low  = recent["low"].min()

    # Liquidity Sweep ke atas (bull trap): spike ke atas lalu tutup di bawah
    if prev["high"] > swing_high and prev["close"] < swing_high:
        signals.append("⚡ Liquidity Sweep HIGH - Harga spike atas lalu balik → Potensi SELL")

    # Liquidity Sweep ke bawah (bear trap): spike ke bawah lalu tutup di atas
    if prev["low"] < swing_low and prev["close"] > swing_low:
        signals.append("⚡ Liquidity Sweep LOW - Harga spike bawah lalu balik → Potensi BUY")

    return signals


def generate_signal(df):
    """Generate sinyal BUY/SELL/WAIT berdasarkan semua indikator"""
    last = df.iloc[-1]

    buy_score  = 0
    sell_score = 0
    reasons    = []

    # --- MA ---
    if last["close"] > last["ma20"] > last["ma50"]:
        buy_score += 2
        reasons.append("✅ MA: Harga di atas MA20 & MA50 (Bullish)")
    elif last["close"] < last["ma20"] < last["ma50"]:
        sell_score += 2
        reasons.append("❌ MA: Harga di bawah MA20 & MA50 (Bearish)")

    # --- EMA Cross ---
    if last["ema9"] > last["ma20"]:
        buy_score += 1
        reasons.append("✅ EMA9 di atas MA20 (Bullish)")
    else:
        sell_score += 1
        reasons.append("❌ EMA9 di bawah MA20 (Bearish)")

    # --- RSI ---
    if last["rsi"] < 30:
        buy_score += 2
        reasons.append(f"✅ RSI: {last['rsi']:.1f} - Oversold (Sinyal BUY)")
    elif last["rsi"] > 70:
        sell_score += 2
        reasons.append(f"❌ RSI: {last['rsi']:.1f} - Overbought (Sinyal SELL)")
    elif 40 < last["rsi"] < 60:
        reasons.append(f"⚠️ RSI: {last['rsi']:.1f} - Netral")
    else:
        reasons.append(f"ℹ️ RSI: {last['rsi']:.1f}")

    # --- MACD ---
    if last["macd"] > last["macd_signal"] and last["macd_hist"] > 0:
        buy_score += 2
        reasons.append("✅ MACD: Bullish crossover")
    elif last["macd"] < last["macd_signal"] and last["macd_hist"] < 0:
        sell_score += 2
        reasons.append("❌ MACD: Bearish crossover")

    # --- Bollinger Bands ---
    if last["close"] < last["bb_lower"]:
        buy_score += 2
        reasons.append(f"✅ BB: Harga di bawah Lower Band → Potensi reversal naik")
    elif last["close"] > last["bb_upper"]:
        sell_score += 2
        reasons.append(f"❌ BB: Harga di atas Upper Band → Potensi reversal turun")
    else:
        bb_pos = (last["close"] - last["bb_lower"]) / (last["bb_upper"] - last["bb_lower"]) * 100
        reasons.append(f"ℹ️ BB: Harga di posisi {bb_pos:.0f}% dalam band")

    # --- SMC ---
    smc_signals = detect_smc(df)
    for s in smc_signals:
        if "Bullish" in s:
            buy_score += 2
        elif "Bearish" in s:
            sell_score += 2
        reasons.append(s)

    # --- Liquidity Sweep ---
    liq_signals = detect_liquidity_sweep(df)
    for s in liq_signals:
        if "BUY" in s:
            buy_score += 3
        elif "SELL" in s:
            sell_score += 3
        reasons.append(s)

    # --- Tentukan sinyal akhir ---
    total = buy_score + sell_score
    if total == 0:
        signal    = "⏸️ WAIT"
        strength  = 0
        emoji     = "⏸️"
    elif buy_score > sell_score:
        signal   = "🟢 BUY"
        strength = round((buy_score / total) * 100)
        emoji    = "🟢"
    elif sell_score > buy_score:
        signal   = "🔴 SELL"
        strength = round((sell_score / total) * 100)
        emoji    = "🔴"
    else:
        signal   = "⏸️ WAIT"
        strength = 50
        emoji    = "⏸️"

    # Hitung SL & TP sederhana
    atr_val = df["high"].iloc[-14:].max() - df["low"].iloc[-14:].min()
    atr     = atr_val / 14

    if "BUY" in signal:
        sl = round(last["close"] - atr * 1.5, 2)
        tp = round(last["close"] + atr * 2.5, 2)
    elif "SELL" in signal:
        sl = round(last["close"] + atr * 1.5, 2)
        tp = round(last["close"] - atr * 2.5, 2)
    else:
        sl = tp = None

    return {
        "signal":   signal,
        "strength": strength,
        "reasons":  reasons,
        "price":    last["close"],
        "sl":       sl,
        "tp":       tp,
        "rsi":      last["rsi"],
        "emoji":    emoji
    }


def format_message(result):
    """Format pesan sinyal untuk Telegram"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    sl_tp = ""
    if result["sl"] and result["tp"]:
        sl_tp = f"""
💰 *Entry:* `{result['price']:.2f}`
🛑 *Stop Loss:* `{result['sl']:.2f}`
🎯 *Take Profit:* `{result['tp']:.2f}`"""

    reasons_text = "\n".join([f"  {r}" for r in result["reasons"]])

    msg = f"""
╔══════════════════════════╗
   📊 *SINYAL FOREX - XAU/USD*
   ⏰ M15 | {now} WIB
╚══════════════════════════╝

{result['signal']} | Kekuatan: *{result['strength']}%*
💵 Harga saat ini: `{result['price']:.2f}`
{sl_tp}

📋 *Analisis Indikator:*
{reasons_text}

⚠️ _Gunakan manajemen risiko yang baik!_
_Bot ini hanya alat bantu, bukan saran finansial._
"""
    return msg


async def send_signal():
    """Fungsi utama: ambil data, analisis, kirim ke Telegram"""
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Mengambil data {SYMBOL}...")
        df     = get_price_data()
        df     = calculate_indicators(df)
        result = generate_signal(df)
        msg    = format_message(result)

        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=msg,
            parse_mode="Markdown"
        )
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Sinyal terkirim: {result['signal']}")

    except Exception as e:
        err_msg = f"⚠️ Error bot sinyal: {str(e)}"
        print(err_msg)
        try:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=err_msg)
        except:
            pass


async def main():
    """Jalankan bot dengan scheduler setiap 15 menit"""
    print("🚀 Bot Sinyal Forex XAU/USD M15 aktif!")
    print(f"📡 Sinyal akan dikirim setiap 15 menit")
    print("=" * 45)

    # Kirim sinyal pertama langsung saat bot nyala
    await send_signal()

    # Jadwalkan setiap 15 menit
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_signal, "interval", minutes=15)
    scheduler.start()

    # Jaga bot tetap berjalan
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        print("\n⛔ Bot dihentikan.")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
