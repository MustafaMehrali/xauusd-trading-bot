"""
XAUUSD Trading Bot v2 – fxverify.com
======================================
Matcher 100% med System Prompt v3
Alle 8 strategier · SMT · DXY · Nyhedsfilter

Kræver: pip install requests pandas numpy
"""

import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# ═══════════════════════════════════════════════
# KONFIGURATION
# ═══════════════════════════════════════════════
TELEGRAM_TOKEN   = "DIN_BOT_TOKEN_HER"
TELEGRAM_CHAT_ID = "DIT_CHAT_ID_HER"
SCAN_INTERVAL    = 60
SLIPPAGE         = 1.0
SPREAD           = 0.30

# Kendte nyheds-tidspunkter (UTC) – opdater månedligt
# Format: "DD-MM HH:MM"
NEWS_EVENTS = [
    # Tilføj FOMC, CPI, NFP datoer her – eksempel:
    # "07-05 18:00",  # FOMC
    # "14-05 12:30",  # CPI
    # "02-05 12:30",  # NFP
]
NEWS_WINDOW_MINS = 30  # minutter før og efter

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Referer":         "https://fxverify.com/chart?s=XAU.USD",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
    "Origin":          "https://fxverify.com"
}

session = requests.Session()
session.headers.update(HEADERS)
_session_ready = False


# ═══════════════════════════════════════════════
# SESSION INIT
# ═══════════════════════════════════════════════
def init_session():
    global _session_ready
    try:
        print("Initialiserer fxverify session...")
        r = session.get("https://fxverify.com/chart?s=XAU.USD", timeout=15)
        if r.status_code == 200:
            print(f"Session klar – cookies: {len(session.cookies)} stk")
            _session_ready = True
            return True
        print(f"Session fejl: {r.status_code}")
        return False
    except Exception as e:
        print(f"Session init fejl: {e}")
        return False


# ═══════════════════════════════════════════════
# DATA HENTNING FRA FXVERIFY
# ═══════════════════════════════════════════════
def fetch_fxverify(symbol, resolution, countback=200):
    """
    Hent OHLCV data fra fxverify.com
    symbol: XAUUSD eller XAGUSD
    resolution: 5, 15, 60
    """
    global _session_ready
    if not _session_ready:
        init_session()

    now = int(time.time())
    from_ts = now - 86400 * 7

    # URL til XAUUSD eller XAGUSD
    sym_encoded = f"IC%20Markets:{symbol}"
    url = (
        f"https://fxverify.com/api/live-chart/datafeed/bars"
        f"?symbol={sym_encoded}"
        f"&resolution={resolution}"
        f"&from={from_ts}"
        f"&to={now}"
        f"&countback={countback}"
    )

    try:
        r = session.get(url, timeout=15)
        if r.status_code == 200:
            bars = r.json()
            if not bars:
                return pd.DataFrame()
            df = pd.DataFrame(bars)
            df['time'] = pd.to_datetime(df['time'], unit='ms', utc=True)
            df = df.rename(columns={
                'time':   'Datetime',
                'open':   'Open',
                'high':   'High',
                'low':    'Low',
                'close':  'Close',
                'volume': 'Volume'
            })
            df = df.set_index('Datetime').sort_index()
            return df
        elif r.status_code == 403:
            print("Session udløbet – genoptager...")
            _session_ready = False
            init_session()
            return pd.DataFrame()
        else:
            print(f"fxverify fejl ({symbol} {resolution}m): {r.status_code}")
            return pd.DataFrame()
    except Exception as e:
        print(f"Data fejl ({symbol} {resolution}m): {e}")
        return pd.DataFrame()

def fetch_dxy():
    """Hent DXY fra fxverify"""
    try:
        now = int(time.time())
        url = (f"https://fxverify.com/api/live-chart/datafeed/bars"
               f"?symbol=IC%20Markets:USINDEX&resolution=60"
               f"&from={now-86400}&to={now}&countback=20")
        r = session.get(url, timeout=15)
        if r.status_code == 200:
            bars = r.json()
            if bars and len(bars) >= 2:
                latest = bars[-1]['close']
                prev   = bars[-2]['close']
                return {'price': latest, 'trend': 'falling' if latest < prev else 'rising'}
    except Exception as e:
        print(f"DXY fejl: {e}")
    return None


# ═══════════════════════════════════════════════
# NYHEDSFILTER
# ═══════════════════════════════════════════════
def is_news_time():
    """Returner True hvis vi er inden for NEWS_WINDOW_MINS af en nyhedsbegivenhed"""
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%d-%m")
    now_mins = now.hour * 60 + now.minute

    for event in NEWS_EVENTS:
        try:
            date_part, time_part = event.split(" ")
            if date_part == now_str:
                h, m = map(int, time_part.split(":"))
                event_mins = h * 60 + m
                if abs(now_mins - event_mins) <= NEWS_WINDOW_MINS:
                    return True, event
        except:
            pass
    return False, None


# ═══════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════
def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       message,
            "parse_mode": "HTML"
        }, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram fejl: {e}")
        return False


# ═══════════════════════════════════════════════
# TEKNISKE INDIKATORER
# ═══════════════════════════════════════════════
def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(com=period-1, adjust=False).mean()
    loss  = (-delta).clip(lower=0).ewm(com=period-1, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def find_swings(df, lb=3):
    """Bekræftede swing highs og lows – mindst lb bars på hver side"""
    highs, lows = [], []
    for i in range(lb, len(df) - lb):
        h = df['High'].iloc[i]
        l = df['Low'].iloc[i]
        if all(h > df['High'].iloc[i-j] for j in range(1, lb+1)) and \
           all(h > df['High'].iloc[i+j] for j in range(1, lb+1)):
            highs.append({'p': h, 'i': i})
        if all(l < df['Low'].iloc[i-j] for j in range(1, lb+1)) and \
           all(l < df['Low'].iloc[i+j] for j in range(1, lb+1)):
            lows.append({'p': l, 'i': i})
    return highs, lows

def detect_fvg(df, i):
    """Fair Value Gap detection"""
    if i < 2:
        return None
    bull = df['Low'].iloc[i]   - df['High'].iloc[i-2]
    bear = df['Low'].iloc[i-2] - df['High'].iloc[i]
    if bull > 0.40:
        return 'bull'
    if bear > 0.40:
        return 'bear'
    return None

def detect_smt(gold_df, silver_df, lookback=10):
    """
    SMT Divergence – sammenlign XAUUSD med XAGUSD
    Bullish SMT: Guld lavere low, Sølv IKKE lavere low
    Bearish SMT: Guld højere high, Sølv IKKE højere high
    """
    if gold_df.empty or silver_df.empty:
        return None
    if len(gold_df) < lookback + 1 or len(silver_df) < lookback + 1:
        return None

    try:
        # Align på tid
        gold_recent = gold_df.iloc[-lookback:]
        silver_recent = silver_df.reindex(gold_recent.index, method='nearest', tolerance='1H')
        silver_recent = silver_recent.dropna(how='all')

        if len(silver_recent) < lookback // 2:
            return None

        gold_low_now  = gold_df['Low'].iloc[-1]
        gold_low_prev = gold_recent['Low'].iloc[:-1].min()
        gold_high_now  = gold_df['High'].iloc[-1]
        gold_high_prev = gold_recent['High'].iloc[:-1].max()

        silver_low_now  = silver_df['Low'].iloc[-1]
        silver_low_prev = silver_recent['Low'].iloc[:-1].min() if len(silver_recent) > 1 else silver_low_now
        silver_high_now  = silver_df['High'].iloc[-1]
        silver_high_prev = silver_recent['High'].iloc[:-1].max() if len(silver_recent) > 1 else silver_high_now

        # Bullish SMT: guld laver lavere low, sølv gør ikke
        if gold_low_now < gold_low_prev and silver_low_now >= silver_low_prev * 0.998:
            return 'bull_smt'
        # Bearish SMT: guld laver højere high, sølv gør ikke
        if gold_high_now > gold_high_prev and silver_high_now <= silver_high_prev * 1.002:
            return 'bear_smt'
    except Exception as e:
        print(f"SMT fejl: {e}")

    return None

def bullish_trend(df, i, lb=20):
    if i < lb:
        return None
    return df['Close'].iloc[i] > df['Close'].iloc[i - lb]

def is_london(dt):
    h = dt.hour if hasattr(dt, 'hour') else pd.Timestamp(dt).hour
    return 8 <= h < 12

def is_ny(dt):
    ts = pd.Timestamp(dt)
    return (ts.hour == 14 and ts.minute >= 30) or (15 <= ts.hour < 17)

def signal_msg(num, name, direction, entry, sl, tp, units, note="", dxy=None):
    e = "🟢" if direction == "BUY" else "🔴"
    ptp = round((tp - entry if direction == "BUY" else entry - tp) * units)
    psl = round((sl - entry if direction == "BUY" else entry - sl) * units)
    dxy_str = ""
    if dxy:
        arrow = "↓" if dxy['trend'] == 'falling' else "↑"
        dxy_str = f"DXY: {dxy['price']:.2f} {arrow}\n"
    return (
        f"\n{e} <b>STRATEGI {num}: {name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Retning: <b>{direction}</b>\n"
        f"Entry:   <b>${entry:.2f}</b>\n"
        f"SL:      ${sl:.2f}\n"
        f"TP:      ${tp:.2f}\n"
        f"Units:   {units}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"P&amp;L ved TP: <b>+${ptp:,}</b>\n"
        f"P&amp;L ved SL: -${abs(psl):,}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{dxy_str}"
        f"{note}\n"
        f"Tid: {datetime.now().strftime('%d/%m %H:%M')} UTC\n"
    )


# ═══════════════════════════════════════════════
# ALLE 8 STRATEGIER
# ═══════════════════════════════════════════════
def scan(df5, df15, df1h, df_ag1h, dxy):
    signals = []
    now = datetime.now(timezone.utc)

    # Makro kontekst – DXY
    # Bullish guld = faldende DXY. +10 units hvis makro og teknisk peger samme vej
    def macro_bonus(direction):
        if dxy is None:
            return 0
        if direction == "BUY"  and dxy['trend'] == 'falling':
            return 10
        if direction == "SELL" and dxy['trend'] == 'rising':
            return 10
        return 0

    # ── S1: Pure Fib 61.8% · 5m · London ──
    try:
        df = df5
        if len(df) >= 25 and is_london(now):
            highs, lows = find_swings(df)
            if highs and lows:
                sh, sl_p = highs[-1]['p'], lows[-1]['p']
                rng = sh - sl_p
                if rng >= 15:
                    last  = df.iloc[-1]
                    trend = bullish_trend(df, len(df)-1)
                    if trend:
                        f = sh - rng * 0.618
                        if last['Close'] > last['Open'] and abs(last['Low'] - f) < 12:
                            u = 50 + macro_bonus("BUY")
                            signals.append(signal_msg(1, "Pure Fib 5m London", "BUY",
                                f+SLIPPAGE, sl_p-10, sh, u,
                                f"61.8% Fib: ${f:.1f} · Grøn 5m candle · Trend: bullish", dxy))
                    elif trend is False:
                        f = sl_p + rng * 0.618
                        if last['Close'] < last['Open'] and abs(last['High'] - f) < 12:
                            u = 50 + macro_bonus("SELL")
                            signals.append(signal_msg(1, "Pure Fib 5m London", "SELL",
                                f-SLIPPAGE, sh+10, sl_p, u,
                                f"61.8% Fib: ${f:.1f} · Rød 5m candle · Trend: bearish", dxy))
    except Exception as e:
        print(f"S1 fejl: {e}")

    # ── S2: Fib+EMA50+RSI · 15m · NY + SMT skalering ──
    try:
        df = df15
        if len(df) >= 60 and is_ny(now):
            ema50 = calc_ema(df['Close'], 50)
            rsi   = calc_rsi(df['Close'])
            highs, lows = find_swings(df)
            smt = detect_smt(df15, df_ag1h)
            if highs and lows:
                sh, sl_p = highs[-1]['p'], lows[-1]['p']
                rng = sh - sl_p
                if rng >= 15:
                    last  = df.iloc[-1]
                    trend = bullish_trend(df, len(df)-1)
                    if trend and last['Close'] > ema50.iloc[-1]:
                        f = sh - rng * 0.618
                        if last['Close'] > last['Open'] and abs(last['Low']-f) < 12 and rsi.iloc[-1] < 58:
                            u = 65 if smt == 'bull_smt' else 50
                            u += macro_bonus("BUY")
                            smt_str = " · SMT bullish ✅" if smt == 'bull_smt' else ""
                            signals.append(signal_msg(2, "Fib+EMA50+RSI 15m NY", "BUY",
                                f+SLIPPAGE, sl_p-10, sh, u,
                                f"Fib: ${f:.1f} · EMA50 ok · RSI: {rsi.iloc[-1]:.0f}{smt_str}", dxy))
                    elif trend is False and last['Close'] < ema50.iloc[-1]:
                        f = sl_p + rng * 0.618
                        if last['Close'] < last['Open'] and abs(last['High']-f) < 12 and rsi.iloc[-1] > 42:
                            u = 65 if smt == 'bear_smt' else 50
                            u += macro_bonus("SELL")
                            smt_str = " · SMT bearish ✅" if smt == 'bear_smt' else ""
                            signals.append(signal_msg(2, "Fib+EMA50+RSI 15m NY", "SELL",
                                f-SLIPPAGE, sh+10, sl_p, u,
                                f"Fib: ${f:.1f} · EMA50 ok · RSI: {rsi.iloc[-1]:.0f}{smt_str}", dxy))
    except Exception as e:
        print(f"S2 fejl: {e}")

    # ── S3: FVG+Fib · 5m · alle sessioner ──
    try:
        df = df5
        if len(df) >= 10:
            fvg = detect_fvg(df, len(df)-1)
            highs, lows = find_swings(df)
            if fvg and highs and lows:
                sh, sl_p = highs[-1]['p'], lows[-1]['p']
                rng = sh - sl_p
                if rng >= 15:
                    last  = df.iloc[-1]
                    trend = bullish_trend(df, len(df)-1)
                    if trend and fvg == 'bull':
                        f = sh - rng * 0.618
                        if last['Close'] > last['Open'] and abs(last['Low'] - f) < 12:
                            u = 65 + macro_bonus("BUY")
                            signals.append(signal_msg(3, "FVG+Fib 5m", "BUY",
                                f+SLIPPAGE, sl_p-10, sh, u,
                                "Bullish FVG dannet i Fibonacci zone", dxy))
                    elif trend is False and fvg == 'bear':
                        f = sl_p + rng * 0.618
                        if last['Close'] < last['Open'] and abs(last['High'] - f) < 12:
                            u = 65 + macro_bonus("SELL")
                            signals.append(signal_msg(3, "FVG+Fib 5m", "SELL",
                                f-SLIPPAGE, sh+10, sl_p, u,
                                "Bearish FVG dannet i Fibonacci zone", dxy))
    except Exception as e:
        print(f"S3 fejl: {e}")

    # ── S4: FVG+Fib · 1H · PRIORITET (100% WR) ──
    try:
        df = df1h
        if len(df) >= 10:
            fvg = detect_fvg(df, len(df)-1)
            highs, lows = find_swings(df)
            if fvg and highs and lows:
                sh, sl_p = highs[-1]['p'], lows[-1]['p']
                rng = sh - sl_p
                if rng >= 15:
                    last  = df.iloc[-1]
                    trend = bullish_trend(df, len(df)-1)
                    if trend and fvg == 'bull':
                        f = sh - rng * 0.618
                        if last['Close'] > last['Open'] and abs(last['Low'] - f) < 12:
                            u = 65 + macro_bonus("BUY")
                            signals.append(signal_msg(4, "FVG+Fib 1H ⭐ PRIORITET", "BUY",
                                f+SLIPPAGE, sl_p-10, sh, u,
                                "⭐ 100% WR strategi!\nBullish FVG + 61.8% Fib på 1H", dxy))
                    elif trend is False and fvg == 'bear':
                        f = sl_p + rng * 0.618
                        if last['Close'] < last['Open'] and abs(last['High'] - f) < 12:
                            u = 65 + macro_bonus("SELL")
                            signals.append(signal_msg(4, "FVG+Fib 1H ⭐ PRIORITET", "SELL",
                                f-SLIPPAGE, sh+10, sl_p, u,
                                "⭐ 100% WR strategi!\nBearish FVG + 61.8% Fib på 1H", dxy))
    except Exception as e:
        print(f"S4 fejl: {e}")

    # ── S5: Pure Fib · 1H · alle sessioner ──
    try:
        df = df1h
        if len(df) >= 25:
            highs, lows = find_swings(df)
            if highs and lows:
                sh, sl_p = highs[-1]['p'], lows[-1]['p']
                rng = sh - sl_p
                if rng >= 15:
                    last  = df.iloc[-1]
                    trend = bullish_trend(df, len(df)-1)
                    if trend:
                        f = sh - rng * 0.618
                        if last['Close'] > last['Open'] and abs(last['Low'] - f) < 12:
                            u = 50 + macro_bonus("BUY")
                            signals.append(signal_msg(5, "Pure Fib 1H", "BUY",
                                f+SLIPPAGE, sl_p-10, sh, u,
                                f"61.8% Fib: ${f:.1f} · Grøn 1H candle", dxy))
                    elif trend is False:
                        f = sl_p + rng * 0.618
                        if last['Close'] < last['Open'] and abs(last['High'] - f) < 12:
                            u = 50 + macro_bonus("SELL")
                            signals.append(signal_msg(5, "Pure Fib 1H", "SELL",
                                f-SLIPPAGE, sh+10, sl_p, u,
                                f"61.8% Fib: ${f:.1f} · Rød 1H candle", dxy))
    except Exception as e:
        print(f"S5 fejl: {e}")

    # ── S6: Fib+EMA50+RSI+SMT · 1H · alle sessioner ──
    try:
        df = df1h
        if len(df) >= 60:
            ema50 = calc_ema(df['Close'], 50)
            rsi   = calc_rsi(df['Close'])
            smt   = detect_smt(df1h, df_ag1h)
            highs, lows = find_swings(df)
            if highs and lows:
                sh, sl_p = highs[-1]['p'], lows[-1]['p']
                rng = sh - sl_p
                if rng >= 15:
                    last  = df.iloc[-1]
                    trend = bullish_trend(df, len(df)-1)
                    if trend and last['Close'] > ema50.iloc[-1] and smt == 'bull_smt':
                        f = sh - rng * 0.618
                        if last['Close'] > last['Open'] and abs(last['Low']-f) < 12 and rsi.iloc[-1] < 58:
                            u = 75 + macro_bonus("BUY")
                            signals.append(signal_msg(6, "Fib+EMA50+RSI+SMT 1H", "BUY",
                                f+SLIPPAGE, sl_p-10, sh, u,
                                f"Fib: ${f:.1f} · EMA50 ok · RSI: {rsi.iloc[-1]:.0f} · SMT bullish ✅", dxy))
                    elif trend is False and last['Close'] < ema50.iloc[-1] and smt == 'bear_smt':
                        f = sl_p + rng * 0.618
                        if last['Close'] < last['Open'] and abs(last['High']-f) < 12 and rsi.iloc[-1] > 42:
                            u = 75 + macro_bonus("SELL")
                            signals.append(signal_msg(6, "Fib+EMA50+RSI+SMT 1H", "SELL",
                                f-SLIPPAGE, sh+10, sl_p, u,
                                f"Fib: ${f:.1f} · EMA50 ok · RSI: {rsi.iloc[-1]:.0f} · SMT bearish ✅", dxy))
    except Exception as e:
        print(f"S6 fejl: {e}")

    # ── S7: Pure Fib · 15m · alle sessioner ──
    try:
        df = df15
        if len(df) >= 25:
            highs, lows = find_swings(df)
            if highs and lows:
                sh, sl_p = highs[-1]['p'], lows[-1]['p']
                rng = sh - sl_p
                if rng >= 15:
                    last  = df.iloc[-1]
                    trend = bullish_trend(df, len(df)-1)
                    if trend:
                        f = sh - rng * 0.618
                        if last['Close'] > last['Open'] and abs(last['Low'] - f) < 12:
                            u = 50 + macro_bonus("BUY")
                            signals.append(signal_msg(7, "Pure Fib 15m", "BUY",
                                f+SLIPPAGE, sl_p-10, sh, u,
                                f"61.8% Fib: ${f:.1f} · Grøn 15m candle", dxy))
                    elif trend is False:
                        f = sl_p + rng * 0.618
                        if last['Close'] < last['Open'] and abs(last['High'] - f) < 12:
                            u = 50 + macro_bonus("SELL")
                            signals.append(signal_msg(7, "Pure Fib 15m", "SELL",
                                f-SLIPPAGE, sh+10, sl_p, u,
                                f"61.8% Fib: ${f:.1f} · Rød 15m candle", dxy))
    except Exception as e:
        print(f"S7 fejl: {e}")

    # ── S8: FVG+Fib+EMA · 5m · supplement (bruges kun hvis ingen S1-7) ──
    try:
        if not signals:  # Kun hvis ingen andre strategier er opfyldt
            df = df5
            if len(df) >= 60:
                ema50 = calc_ema(df['Close'], 50)
                rsi   = calc_rsi(df['Close'])
                fvg   = detect_fvg(df, len(df)-1)
                highs, lows = find_swings(df)
                if fvg and highs and lows:
                    sh, sl_p = highs[-1]['p'], lows[-1]['p']
                    rng = sh - sl_p
                    if rng >= 15:
                        last  = df.iloc[-1]
                        trend = bullish_trend(df, len(df)-1)
                        mid   = sh - rng * 0.5  # 50% niveau
                        if trend and fvg == 'bull' and last['Close'] < mid:
                            f = sh - rng * 0.618
                            if (last['Close'] > last['Open'] and
                                last['Close'] > ema50.iloc[-1] and
                                rsi.iloc[-1] < 62 and
                                abs(last['Low'] - f) < 8):
                                entry = last['Close'] + SLIPPAGE
                                signals.append(signal_msg(8, "FVG+Fib+EMA 5m (supplement)", "BUY",
                                    entry, entry-13, sh, 50,
                                    f"Discount zone · FVG · EMA50 ok · RSI: {rsi.iloc[-1]:.0f}", dxy))
                        elif trend is False and fvg == 'bear' and last['Close'] > mid:
                            f = sl_p + rng * 0.618
                            if (last['Close'] < last['Open'] and
                                last['Close'] < ema50.iloc[-1] and
                                rsi.iloc[-1] > 38 and
                                abs(last['High'] - f) < 8):
                                entry = last['Close'] - SLIPPAGE
                                signals.append(signal_msg(8, "FVG+Fib+EMA 5m (supplement)", "SELL",
                                    entry, entry+13, sl_p, 50,
                                    f"Premium zone · FVG · EMA50 ok · RSI: {rsi.iloc[-1]:.0f}", dxy))
    except Exception as e:
        print(f"S8 fejl: {e}")

    return signals


# ═══════════════════════════════════════════════
# HOVED LOOP
# ═══════════════════════════════════════════════
def main():
    print("=" * 50)
    print("XAUUSD Trading Bot v2 – fxverify.com")
    print("Alle 8 strategier · SMT · DXY · Nyhedsfilter")
    print(f"Scanner hvert {SCAN_INTERVAL} sekund")
    print("=" * 50)

    if not init_session():
        print("ADVARSEL: Session fejlede – prøver alligevel")

    send_telegram(
        "🤖 <b>XAUUSD Trading Bot v2 startet</b>\n"
        "Alle 8 strategier aktive\n"
        "SMT (XAGUSD) · DXY · Nyhedsfilter\n"
        "Scanner hvert minut..."
    )

    seen = set()

    while True:
        try:
            now = datetime.now(timezone.utc)
            print(f"\n[{now.strftime('%H:%M:%S')}] Scanner...")

            # Tjek nyhedsfilter
            news_active, news_event = is_news_time()
            if news_active:
                print(f"NYHEDSFILTER aktiv: {news_event} – ingen trading")
                time.sleep(SCAN_INTERVAL)
                continue

            # Hent XAUUSD data
            df5   = fetch_fxverify("XAUUSD", 5,  200)
            df15  = fetch_fxverify("XAUUSD", 15, 200)
            df1h  = fetch_fxverify("XAUUSD", 60, 200)

            # Hent XAGUSD (sølv) til SMT
            df_ag1h = fetch_fxverify("XAGUSD", 60, 200)

            # Hent DXY til makro kontekst
            dxy = fetch_dxy()

            if df5.empty and df15.empty and df1h.empty:
                print("Ingen data – prøver igen...")
                time.sleep(SCAN_INTERVAL)
                continue

            print(f"Data: XAUUSD 5m={len(df5)} 15m={len(df15)} 1H={len(df1h)} · XAGUSD 1H={len(df_ag1h)} · DXY={'ok' if dxy else 'fejl'}")

            # Scan alle 8 strategier
            signals = scan(df5, df15, df1h, df_ag1h, dxy)

            if signals:
                for s in signals:
                    key = s[:80] + str(now.hour) + str(now.minute // 5)
                    if key not in seen:
                        send_telegram(s)
                        seen.add(key)
                        print(f"Signal sendt!")
                if len(seen) > 100:
                    seen = set(list(seen)[-30:])
            else:
                print("Ingen setups endnu")

            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            print("\nBot stoppet")
            send_telegram("🛑 Bot stoppet")
            break
        except Exception as e:
            print(f"Fejl: {e}")
            time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
