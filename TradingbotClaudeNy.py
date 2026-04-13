"""
XAUUSD Trading Bot v4 – fxverify.com
======================================
100% identisk med backtesten + 4 livefixes:

MATEMATISK BEVIS for R:R:
  reward = range * 0.618 - slippage
  risk   = range * 0.382 + 10 + slippage
  For R:R >= 1.0: range >= 50.8
  MIN_SWING_RANGE = 55 giver R:R >= 1.03 altid

Fix 1: Min swing range $55 (op fra $15) → R:R >= 1.0 garanteret
Fix 2: Min R:R = 1.0 (eksplicit filter)
Fix 3: Duplikering 60 min vindue (ikke 5 min)
Fix 4: Afvis signal hvis pris > $10 fra Fib zone

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
TELEGRAM_TOKEN   = "8651971467:AAHm7ZyS8VbuMdSPbMQcPPodkDX2NVlUH8s"
TELEGRAM_CHAT_ID = "5773639455"
SCAN_INTERVAL    = 60
SLIPPAGE         = 1.0
SPREAD           = 0.30
MIN_SWING_RANGE  = 55.0   # Fix 1: matematisk sikrer R:R >= 1.03
MIN_RR           = 1.0    # Fix 2: eksplicit 1:1 minimum
MAX_PRICE_DIST   = 10.0   # Fix 4: max $10 fra Fib zone

NEWS_EVENTS = []  # Format: "DD-MM HH:MM" – tilføj FOMC/CPI/NFP
NEWS_WINDOW_MINS = 30

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":         "https://fxverify.com/chart?s=XAU.USD",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
    "Origin":          "https://fxverify.com"
}

session = requests.Session()
session.headers.update(HEADERS)
_session_ready = False


def init_session():
    global _session_ready
    try:
        r = session.get("https://fxverify.com/chart?s=XAU.USD", timeout=15)
        if r.status_code == 200:
            print(f"Session klar – cookies: {len(session.cookies)}")
            _session_ready = True
            return True
        return False
    except Exception as e:
        print(f"Session fejl: {e}")
        return False


def fetch_fxverify(symbol, resolution, countback=200):
    global _session_ready
    if not _session_ready:
        init_session()
    now = int(time.time())
    url = (f"https://fxverify.com/api/live-chart/datafeed/bars"
           f"?symbol=IC%20Markets:{symbol}&resolution={resolution}"
           f"&from={now-86400*7}&to={now}&countback={countback}")
    try:
        r = session.get(url, timeout=15)
        if r.status_code == 200:
            bars = r.json()
            if not bars:
                return pd.DataFrame()
            df = pd.DataFrame(bars)
            df['time'] = pd.to_datetime(df['time'], unit='ms', utc=True)
            df = df.rename(columns={'time':'Datetime','open':'Open','high':'High',
                                    'low':'Low','close':'Close','volume':'Volume'})
            return df.set_index('Datetime').sort_index()
        elif r.status_code == 403:
            _session_ready = False
            init_session()
            return pd.DataFrame()
    except Exception as e:
        print(f"Data fejl ({symbol} {resolution}m): {e}")
    return pd.DataFrame()


def fetch_dxy():
    try:
        now = int(time.time())
        r = session.get(f"https://fxverify.com/api/live-chart/datafeed/bars"
                        f"?symbol=IC%20Markets:USINDEX&resolution=60"
                        f"&from={now-86400}&to={now}&countback=5", timeout=15)
        if r.status_code == 200:
            bars = r.json()
            if bars and len(bars) >= 2:
                return {'price': bars[-1]['close'],
                        'trend': 'falling' if bars[-1]['close'] < bars[-2]['close'] else 'rising'}
    except:
        pass
    return None


def is_news_time():
    now = datetime.now(timezone.utc)
    now_mins = now.hour * 60 + now.minute
    for event in NEWS_EVENTS:
        try:
            dp, tp = event.split(" ")
            if dp == now.strftime("%d-%m"):
                h, m = map(int, tp.split(":"))
                if abs(now_mins - (h*60+m)) <= NEWS_WINDOW_MINS:
                    return True, event
        except:
            pass
    return False, None


def send_telegram(msg):
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                         json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
                         timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram fejl: {e}")
        return False


# ═══════════════════════════════════════════════
# INDIKATORER – identisk med backtest
# ═══════════════════════════════════════════════
def calc_ema(series, p):
    return series.ewm(span=p, adjust=False).mean()

def calc_rsi(series, p=14):
    d = series.diff()
    g = d.clip(lower=0).ewm(com=p-1, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(com=p-1, adjust=False).mean()
    return 100 - (100 / (1 + g / l.replace(0, np.nan)))

def find_swings(df, lb=3):
    """Identisk med backtest: lb=3 bars bekræftelse på hver side"""
    highs, lows = [], []
    for i in range(lb, len(df) - lb):
        h, l = df['High'].iloc[i], df['Low'].iloc[i]
        if all(h > df['High'].iloc[i-j] for j in range(1,lb+1)) and \
           all(h > df['High'].iloc[i+j] for j in range(1,lb+1)):
            highs.append({'p': h, 'i': i})
        if all(l < df['Low'].iloc[i-j] for j in range(1,lb+1)) and \
           all(l < df['Low'].iloc[i+j] for j in range(1,lb+1)):
            lows.append({'p': l, 'i': i})
    return highs, lows

def detect_fvg(df, i):
    """Identisk med backtest: gap > $0.40"""
    if i < 2: return None
    if df['Low'].iloc[i] - df['High'].iloc[i-2] > 0.40: return 'bull'
    if df['Low'].iloc[i-2] - df['High'].iloc[i] > 0.40: return 'bear'
    return None

def detect_smt(gold_df, silver_df, lb=10):
    """
    Identisk med backtest:
    - lb bars FØR nuværende (ekskl. nuværende)
    - Kræver candle-retning (grøn for bull, rød for bear)
    - Ingen tolerance
    """
    if gold_df.empty or silver_df.empty or len(gold_df)<lb+1 or len(silver_df)<lb+1:
        return None
    try:
        gc = {'lo': gold_df['Low'].iloc[-1],   'hi': gold_df['High'].iloc[-1],
              'cl': gold_df['Close'].iloc[-1],  'op': gold_df['Open'].iloc[-1]}
        sc = {'lo': silver_df['Low'].iloc[-1],  'hi': silver_df['High'].iloc[-1]}
        gw_hi = gold_df['High'].iloc[-lb-1:-1].max()
        gw_lo = gold_df['Low'].iloc[-lb-1:-1].min()
        sw_hi = silver_df['High'].iloc[-lb-1:-1].max()
        sw_lo = silver_df['Low'].iloc[-lb-1:-1].min()
        if gc['lo'] < gw_lo and sc['lo'] > sw_lo and gc['cl'] > gc['op']: return 'bull_smt'
        if gc['hi'] > gw_hi and sc['hi'] < sw_hi and gc['cl'] < gc['op']: return 'bear_smt'
    except:
        pass
    return None

def trend(df, i, lb=20):
    if i < lb: return None
    return df['Close'].iloc[i] > df['Close'].iloc[i-lb]

def is_london(dt):
    h = dt.hour if hasattr(dt,'hour') else pd.Timestamp(dt).hour
    return 8 <= h < 12

def is_ny(dt):
    ts = pd.Timestamp(dt)
    return (ts.hour==14 and ts.minute>=30) or (15<=ts.hour<17)

def macro_bonus(direction, dxy):
    if not dxy: return 0
    if direction=="BUY"  and dxy['trend']=='falling': return 10
    if direction=="SELL" and dxy['trend']=='rising':  return 10
    return 0


# ═══════════════════════════════════════════════
# VALIDERING – alle 4 fixes
# ═══════════════════════════════════════════════
def validate(entry, sl, tp, fib, cur_price):
    """
    Fix 2: R:R >= 1.0
    Fix 4: pris max $10 fra Fib zone
    Returnerer (ok, rr, årsag)
    """
    risk   = abs(entry - sl)
    reward = abs(tp - entry)
    if risk == 0: return False, 0, "risiko=0"
    rr = reward / risk
    if rr < MIN_RR:
        return False, rr, f"R:R={rr:.2f} < {MIN_RR}"
    if cur_price is not None and abs(cur_price - fib) > MAX_PRICE_DIST:
        return False, rr, f"Pris ${cur_price:.2f} er ${abs(cur_price-fib):.1f} fra zone"
    return True, rr, "ok"


def fmt(num, name, dir_, entry, sl, tp, units, note, dxy, rr):
    e   = "🟢" if dir_=="BUY" else "🔴"
    ptp = round((tp-entry if dir_=="BUY" else entry-tp)*units)
    psl = round((sl-entry if dir_=="BUY" else entry-sl)*units)
    dxy_s = f"DXY: {dxy['price']:.2f} {'↓' if dxy['trend']=='falling' else '↑'}\n" if dxy else ""
    return (f"\n{e} <b>STRATEGI {num}: {name}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Retning: <b>{dir_}</b>\n"
            f"Entry:   <b>${entry:.2f}</b>\n"
            f"SL:      ${sl:.2f}\n"
            f"TP:      ${tp:.2f}\n"
            f"Units:   {units}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"P&amp;L ved TP: <b>+${ptp:,}</b>\n"
            f"P&amp;L ved SL: -${abs(psl):,}\n"
            f"R:R: <b>{rr:.2f}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{dxy_s}{note}\n"
            f"Tid: {datetime.now().strftime('%d/%m %H:%M')} UTC\n")


# ═══════════════════════════════════════════════
# ALLE 8 STRATEGIER – 100% IDENTISK MED BACKTEST
# ═══════════════════════════════════════════════
def scan(df5, df15, df1h, df_ag1h, dxy):
    sigs = []
    now  = datetime.now(timezone.utc)
    cp   = df5['Close'].iloc[-1] if not df5.empty else None

    def add(num, name, dir_, entry, sl, tp, units, fib, note):
        ok, rr, reason = validate(entry, sl, tp, fib, cp)
        if not ok:
            print(f"  S{num} afvist: {reason}")
            return
        sigs.append(fmt(num, name, dir_, entry, sl, tp, units, note, dxy, rr))
        print(f"  ✅ S{num} {dir_} @ ${entry:.2f} R:R={rr:.2f}")

    # S1: Pure Fib 61.8% · 5m · London
    try:
        if len(df5)>=25 and is_london(now):
            H,L = find_swings(df5)
            if H and L:
                sh,sl_=H[-1],L[-1]; rng=sh['p']-sl_['p']
                if rng>=MIN_SWING_RANGE:
                    c=df5.iloc[-1]; tr=trend(df5,len(df5)-1)
                    if tr and sh['i']>sl_['i']:
                        f=sh['p']-rng*.618
                        if c['Close']>c['Open'] and abs(c['Low']-f)<12:
                            add(1,"Pure Fib 5m London","BUY",f+SLIPPAGE,sl_['p']-10,sh['p'],50+macro_bonus("BUY",dxy),f,f"61.8%: ${f:.1f} · Grøn 5m candle")
                    elif tr is False and sl_['i']>sh['i']:
                        f=sl_['p']+rng*.618
                        if c['Close']<c['Open'] and abs(c['High']-f)<12:
                            add(1,"Pure Fib 5m London","SELL",f-SLIPPAGE,sh['p']+10,sl_['p'],50+macro_bonus("SELL",dxy),f,f"61.8%: ${f:.1f} · Rød 5m candle")
    except Exception as e: print(f"S1 fejl: {e}")

    # S2: Fib+EMA50+RSI · 15m · NY
    try:
        if len(df15)>=60 and is_ny(now):
            ema50=calc_ema(df15['Close'],50); rsi=calc_rsi(df15['Close'])
            H,L=find_swings(df15)
            if H and L:
                sh,sl_=H[-1],L[-1]; rng=sh['p']-sl_['p']
                if rng>=MIN_SWING_RANGE:
                    c=df15.iloc[-1]; tr=trend(df15,len(df15)-1); eu=c['Close']>ema50.iloc[-1]
                    if tr and sh['i']>sl_['i'] and eu:
                        f=sh['p']-rng*.618
                        if c['Close']>c['Open'] and abs(c['Low']-f)<12 and rsi.iloc[-1]<58:
                            add(2,"Fib+EMA50+RSI 15m NY","BUY",f+SLIPPAGE,sl_['p']-10,sh['p'],50+macro_bonus("BUY",dxy),f,f"Fib: ${f:.1f} · EMA50 ok · RSI:{rsi.iloc[-1]:.0f}")
                    elif tr is False and sl_['i']>sh['i'] and not eu:
                        f=sl_['p']+rng*.618
                        if c['Close']<c['Open'] and abs(c['High']-f)<12 and rsi.iloc[-1]>42:
                            add(2,"Fib+EMA50+RSI 15m NY","SELL",f-SLIPPAGE,sh['p']+10,sl_['p'],50+macro_bonus("SELL",dxy),f,f"Fib: ${f:.1f} · EMA50 ok · RSI:{rsi.iloc[-1]:.0f}")
    except Exception as e: print(f"S2 fejl: {e}")

    # S3: FVG+Fib · 5m · alle sessioner
    try:
        if len(df5)>=10:
            fvg=detect_fvg(df5,len(df5)-1); H,L=find_swings(df5)
            if fvg and H and L:
                sh,sl_=H[-1],L[-1]; rng=sh['p']-sl_['p']
                if rng>=MIN_SWING_RANGE:
                    c=df5.iloc[-1]; tr=trend(df5,len(df5)-1)
                    if tr and sh['i']>sl_['i'] and fvg=='bull':
                        f=sh['p']-rng*.618
                        if c['Close']>c['Open'] and abs(c['Low']-f)<12:
                            add(3,"FVG+Fib 5m","BUY",f+SLIPPAGE,sl_['p']-10,sh['p'],65+macro_bonus("BUY",dxy),f,"Bullish FVG i Fibonacci zone")
                    elif tr is False and sl_['i']>sh['i'] and fvg=='bear':
                        f=sl_['p']+rng*.618
                        if c['Close']<c['Open'] and abs(c['High']-f)<12:
                            add(3,"FVG+Fib 5m","SELL",f-SLIPPAGE,sh['p']+10,sl_['p'],65+macro_bonus("SELL",dxy),f,"Bearish FVG i Fibonacci zone")
    except Exception as e: print(f"S3 fejl: {e}")

    # S4: FVG+Fib · 1H · PRIORITET
    try:
        if len(df1h)>=10:
            fvg=detect_fvg(df1h,len(df1h)-1); H,L=find_swings(df1h)
            if fvg and H and L:
                sh,sl_=H[-1],L[-1]; rng=sh['p']-sl_['p']
                if rng>=MIN_SWING_RANGE:
                    c=df1h.iloc[-1]; tr=trend(df1h,len(df1h)-1)
                    if tr and sh['i']>sl_['i'] and fvg=='bull':
                        f=sh['p']-rng*.618
                        if c['Close']>c['Open'] and abs(c['Low']-f)<12:
                            add(4,"FVG+Fib 1H ⭐ PRIORITET","BUY",f+SLIPPAGE,sl_['p']-10,sh['p'],65+macro_bonus("BUY",dxy),f,"⭐ Bullish FVG + 61.8% Fib på 1H")
                    elif tr is False and sl_['i']>sh['i'] and fvg=='bear':
                        f=sl_['p']+rng*.618
                        if c['Close']<c['Open'] and abs(c['High']-f)<12:
                            add(4,"FVG+Fib 1H ⭐ PRIORITET","SELL",f-SLIPPAGE,sh['p']+10,sl_['p'],65+macro_bonus("SELL",dxy),f,"⭐ Bearish FVG + 61.8% Fib på 1H")
    except Exception as e: print(f"S4 fejl: {e}")

    # S5: Pure Fib · 1H · alle sessioner
    try:
        if len(df1h)>=25:
            H,L=find_swings(df1h)
            if H and L:
                sh,sl_=H[-1],L[-1]; rng=sh['p']-sl_['p']
                if rng>=MIN_SWING_RANGE:
                    c=df1h.iloc[-1]; tr=trend(df1h,len(df1h)-1)
                    if tr and sh['i']>sl_['i']:
                        f=sh['p']-rng*.618
                        if c['Close']>c['Open'] and abs(c['Low']-f)<12:
                            add(5,"Pure Fib 1H","BUY",f+SLIPPAGE,sl_['p']-10,sh['p'],50+macro_bonus("BUY",dxy),f,f"61.8%: ${f:.1f} · Grøn 1H candle")
                    elif tr is False and sl_['i']>sh['i']:
                        f=sl_['p']+rng*.618
                        if c['Close']<c['Open'] and abs(c['High']-f)<12:
                            add(5,"Pure Fib 1H","SELL",f-SLIPPAGE,sh['p']+10,sl_['p'],50+macro_bonus("SELL",dxy),f,f"61.8%: ${f:.1f} · Rød 1H candle")
    except Exception as e: print(f"S5 fejl: {e}")

    # S6: Fib+EMA50+RSI+SMT · 1H · 75 units
    try:
        if len(df1h)>=60:
            ema50=calc_ema(df1h['Close'],50); rsi=calc_rsi(df1h['Close'])
            smt=detect_smt(df1h,df_ag1h); H,L=find_swings(df1h)
            if H and L:
                sh,sl_=H[-1],L[-1]; rng=sh['p']-sl_['p']
                if rng>=MIN_SWING_RANGE:
                    c=df1h.iloc[-1]; tr=trend(df1h,len(df1h)-1); eu=c['Close']>ema50.iloc[-1]
                    if tr and sh['i']>sl_['i'] and eu and smt=='bull_smt':
                        f=sh['p']-rng*.618
                        if c['Close']>c['Open'] and abs(c['Low']-f)<12 and rsi.iloc[-1]<58:
                            add(6,"Fib+EMA50+RSI+SMT 1H","BUY",f+SLIPPAGE,sl_['p']-10,sh['p'],75+macro_bonus("BUY",dxy),f,f"Fib: ${f:.1f} · EMA50 ok · RSI:{rsi.iloc[-1]:.0f} · SMT bullish ✅")
                    elif tr is False and sl_['i']>sh['i'] and not eu and smt=='bear_smt':
                        f=sl_['p']+rng*.618
                        if c['Close']<c['Open'] and abs(c['High']-f)<12 and rsi.iloc[-1]>42:
                            add(6,"Fib+EMA50+RSI+SMT 1H","SELL",f-SLIPPAGE,sh['p']+10,sl_['p'],75+macro_bonus("SELL",dxy),f,f"Fib: ${f:.1f} · EMA50 ok · RSI:{rsi.iloc[-1]:.0f} · SMT bearish ✅")
    except Exception as e: print(f"S6 fejl: {e}")

    # S7: Pure Fib · 15m · alle sessioner
    try:
        if len(df15)>=25:
            H,L=find_swings(df15)
            if H and L:
                sh,sl_=H[-1],L[-1]; rng=sh['p']-sl_['p']
                if rng>=MIN_SWING_RANGE:
                    c=df15.iloc[-1]; tr=trend(df15,len(df15)-1)
                    if tr and sh['i']>sl_['i']:
                        f=sh['p']-rng*.618
                        if c['Close']>c['Open'] and abs(c['Low']-f)<12:
                            add(7,"Pure Fib 15m","BUY",f+SLIPPAGE,sl_['p']-10,sh['p'],50+macro_bonus("BUY",dxy),f,f"61.8%: ${f:.1f} · Grøn 15m candle")
                    elif tr is False and sl_['i']>sh['i']:
                        f=sl_['p']+rng*.618
                        if c['Close']<c['Open'] and abs(c['High']-f)<12:
                            add(7,"Pure Fib 15m","SELL",f-SLIPPAGE,sh['p']+10,sl_['p'],50+macro_bonus("SELL",dxy),f,f"61.8%: ${f:.1f} · Rød 15m candle")
    except Exception as e: print(f"S7 fejl: {e}")

    # S8: FVG+Fib+EMA · 5m · supplement – KUN hvis ingen S1-7
    try:
        if not sigs and len(df5)>=60:
            ema50=calc_ema(df5['Close'],50); rsi=calc_rsi(df5['Close'])
            fvg=detect_fvg(df5,len(df5)-1); H,L=find_swings(df5)
            if fvg and H and L:
                sh,sl_=H[-1],L[-1]; rng=sh['p']-sl_['p']
                mid=sh['p']-rng*.5
                if rng>=MIN_SWING_RANGE:
                    c=df5.iloc[-1]; tr=trend(df5,len(df5)-1)
                    if tr and sh['i']>sl_['i'] and c['Close']<mid and fvg=='bull':
                        f=sh['p']-rng*.618
                        if c['Close']>c['Open'] and c['Close']>ema50.iloc[-1] and rsi.iloc[-1]<62 and abs(c['Low']-f)<8:
                            e=c['Close']+SLIPPAGE
                            add(8,"FVG+Fib+EMA 5m (supplement)","BUY",e,e-13,sh['p'],50+macro_bonus("BUY",dxy),f,f"Discount zone · RSI:{rsi.iloc[-1]:.0f}")
                    elif tr is False and sl_['i']>sh['i'] and c['Close']>mid and fvg=='bear':
                        f=sl_['p']+rng*.618
                        if c['Close']<c['Open'] and c['Close']<ema50.iloc[-1] and rsi.iloc[-1]>38 and abs(c['High']-f)<8:
                            e=c['Close']-SLIPPAGE
                            add(8,"FVG+Fib+EMA 5m (supplement)","SELL",e,e+13,sl_['p'],50+macro_bonus("SELL",dxy),f,f"Premium zone · RSI:{rsi.iloc[-1]:.0f}")
    except Exception as e: print(f"S8 fejl: {e}")

    return sigs


# ═══════════════════════════════════════════════
# HOVED LOOP
# ═══════════════════════════════════════════════
def main():
    print("="*60)
    print("XAUUSD Trading Bot v4 – Stabile og sikre trades")
    print(f"Min range: ${MIN_SWING_RANGE} | Min R:R: {MIN_RR}:1 | Max dist: ${MAX_PRICE_DIST}")
    print("="*60)

    if not init_session():
        print("ADVARSEL: Session fejlede")

    send_telegram(
        "🤖 <b>XAUUSD Trading Bot v4</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Min swing $55 → R:R >= 1.0 garanteret\n"
        "✅ Min R:R 1.0 · Duplik 60 min · Zone $10\n"
        "✅ Alle 8 strategier · SMT · DXY\n"
        "Færre men bedre og sikre trades..."
    )

    seen = set()

    while True:
        try:
            now = datetime.now(timezone.utc)
            print(f"\n[{now.strftime('%H:%M:%S')}] Scanner...")

            news_ok, news_ev = is_news_time()
            if news_ok:
                print(f"NYHEDSFILTER: {news_ev}")
                time.sleep(SCAN_INTERVAL)
                continue

            df5     = fetch_fxverify("XAUUSD", 5,  200)
            df15    = fetch_fxverify("XAUUSD", 15, 200)
            df1h    = fetch_fxverify("XAUUSD", 60, 200)
            df_ag1h = fetch_fxverify("XAGUSD", 60, 200)
            dxy     = fetch_dxy()

            if df5.empty and df15.empty and df1h.empty:
                print("Ingen data – prøver igen...")
                time.sleep(SCAN_INTERVAL)
                continue

            cp = df5['Close'].iloc[-1] if not df5.empty else 0
            print(f"Pris: ${cp:.2f} | 5m={len(df5)} 15m={len(df15)} 1H={len(df1h)} | XAGUSD={len(df_ag1h)} | DXY={'ok' if dxy else '?'}")

            signals = scan(df5, df15, df1h, df_ag1h, dxy)

            if signals:
                for s in signals:
                    # FIX 3: unikt per time (ikke per 5 min)
                    key = s[:80] + str(now.date()) + str(now.hour)
                    if key not in seen:
                        send_telegram(s)
                        seen.add(key)
                        print("✅ Signal sendt!")
                    else:
                        print("⏭ Duplikat (60 min vindue)")
                if len(seen) > 200:
                    seen = set(list(seen)[-50:])
            else:
                print("Ingen godkendte setups endnu")

            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            send_telegram("🛑 Bot stoppet")
            break
        except Exception as e:
            print(f"Fejl: {e}")
            time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
