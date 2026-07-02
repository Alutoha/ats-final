import streamlit as st
import streamlit.components.v1 as components
import sqlite3
import hashlib
import os
import random
import string
from datetime import datetime, timedelta
import pytz
import yfinance as yf
import pandas as pd
import numpy as np

# ==================== AUTHENTICATION ====================
def hash_password(password):
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return salt + key

def check_password(password, hashed):
    salt = hashed[:32]
    key = hashed[32:]
    new_key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return new_key == key

def init_db():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nama TEXT, email TEXT,
        username TEXT UNIQUE, password_hash BLOB,
        expired_date TEXT, status TEXT DEFAULT 'aktif',
        is_trial INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE, password_hash BLOB)''')
    c.execute("SELECT * FROM admins WHERE username='admin'")
    if not c.fetchone():
        hashed = hash_password("admin123")
        c.execute("INSERT INTO admins (username, password_hash) VALUES (?,?)", ("admin", hashed))
    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect("users.db")

def verify_admin(u, p):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT password_hash FROM admins WHERE username=?", (u,))
    row = c.fetchone()
    conn.close()
    return row and check_password(p, row[0])

def change_admin_password(old_pw, new_pw):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT password_hash FROM admins WHERE username='admin'")
    row = c.fetchone()
    if row and check_password(old_pw, row[0]):
        hashed = hash_password(new_pw)
        c.execute("UPDATE admins SET password_hash=? WHERE username='admin'", (hashed,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def verify_user(u, p):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT password_hash, expired_date, status, nama FROM users WHERE username=?", (u,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None, "Username tidak ditemukan"
    if row[2] != 'aktif':
        return None, "Akun dinonaktifkan"
    if not check_password(p, row[0]):
        return None, "Password salah"
    expired = datetime.strptime(row[1], "%Y-%m-%d")
    if expired < datetime.now():
        conn = get_conn()
        c = conn.cursor()
        c.execute("UPDATE users SET status='expired' WHERE username=?", (u,))
        conn.commit()
        conn.close()
        return None, "Akun expired"
    return row[3], None

def generate_user(nama, email, days, is_trial=0):
    angka = ''.join(random.choices(string.digits, k=4))
    username = f"USER-{nama.upper()}{angka}"
    pw = ''.join(random.choices(string.ascii_letters + string.digits + "#@!", k=10))
    hashed = hash_password(pw)
    exp = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (nama,email,username,password_hash,expired_date,is_trial) VALUES (?,?,?,?,?,?)",
                  (nama, email, username, hashed, exp, is_trial))
        conn.commit()
        conn.close()
        return username, pw, exp
    except sqlite3.IntegrityError:
        conn.close()
        return generate_user(nama, email, days, is_trial)

def get_users():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id,nama,email,username,expired_date,status,is_trial FROM users ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def delete_user(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()

def extend_user(uid, days):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT expired_date FROM users WHERE id=?", (uid,))
    row = c.fetchone()
    if row:
        old = datetime.strptime(row[0], "%Y-%m-%d")
        new = (old + timedelta(days=days)).strftime("%Y-%m-%d")
        c.execute("UPDATE users SET expired_date=?, status='aktif' WHERE id=?", (new, uid))
        conn.commit()
    conn.close()

# ==================== SYMBOL & DATA ====================
SYMBOL_MAP = {"XAUUSD": "GC=F"}
TV_SYMBOL = {"XAUUSD": "OANDA:XAUUSD"}

@st.cache_data(ttl=300)
def fetch_data(symbol, interval, period="7d"):
    ticker = SYMBOL_MAP.get(symbol, "GC=F")
    try:
        df = yf.download(ticker, period=period, interval=interval)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df.dropna()
    except:
        return None

@st.cache_data(ttl=300)
def fetch_all_timeframes(symbol):
    result = {}
    df = fetch_data(symbol, "1d", "3mo")
    if df is not None and not df.empty:
        result["1d"] = df
    df = fetch_data(symbol, "1h", "1mo")
    if df is not None and not df.empty:
        df_h4 = df.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
        if not df_h4.empty:
            result["4h"] = df_h4
        result["1h"] = df
    df = fetch_data(symbol, "15m", "60d")
    if df is not None and not df.empty:
        result["15m"] = df
    df = fetch_data(symbol, "5m", "60d")
    if df is not None and not df.empty:
        result["5m"] = df
    df = fetch_data(symbol, "1m", "7d")
    if df is not None and not df.empty:
        result["1m"] = df
    return result

# ==================== TEKNIKAL ====================
def find_swings(df, strength=2):
    highs = df["High"].values
    lows = df["Low"].values
    sh, sl = [], []
    for i in range(strength, len(df)-strength):
        if highs[i] == max(highs[i-strength:i+strength+1]):
            sh.append(i)
        if lows[i] == min(lows[i-strength:i+strength+1]):
            sl.append(i)
    return sh, sl

def get_swing_levels(df, n=3, strength=2):
    sh_idx, sl_idx = find_swings(df, strength)
    swing_highs = [float(df["High"].iloc[i]) for i in sh_idx[::-1]]
    swing_lows = [float(df["Low"].iloc[i]) for i in sl_idx[::-1]]
    return swing_highs[:n], swing_lows[:n]

def detect_bos(df, sh, sl):
    bull, bear = False, False
    if len(sh) >= 2 and df["High"].iloc[-1] > df["High"].iloc[sh[-2]]:
        bull = True
    if len(sl) >= 2 and df["Low"].iloc[-1] < df["Low"].iloc[sl[-2]]:
        bear = True
    return bull, bear

def find_ob(df, direction, idx):
    for i in range(idx-1, max(idx-10, 0), -1):
        if direction == "bull" and df["Close"].iloc[i] < df["Open"].iloc[i]:
            return {"high": df["High"].iloc[i], "low": df["Low"].iloc[i]}
        if direction == "bear" and df["Close"].iloc[i] > df["Open"].iloc[i]:
            return {"high": df["High"].iloc[i], "low": df["Low"].iloc[i]}
    return None

def find_fvg(df):
    if len(df) < 3:
        return None
    last, prev, prev2 = df.iloc[-1], df.iloc[-2], df.iloc[-3]
    if prev2["High"] < last["Low"]:
        return {"top": last["Low"], "bottom": prev2["High"], "type": "bullish"}
    if prev2["Low"] > last["High"]:
        return {"top": prev2["Low"], "bottom": last["High"], "type": "bearish"}
    return None

def detect_cisd(df):
    if len(df) < 5:
        return None
    sh, sl = find_swings(df.iloc[-10:], strength=2)
    if len(sh) >= 2 and len(sl) >= 2:
        last_sh_idx = sh[-1]; prev_sh_idx = sh[-2]
        last_sl_idx = sl[-1]; prev_sl_idx = sl[-2]
        if (df["Low"].iloc[last_sl_idx] < df["Low"].iloc[prev_sl_idx] and 
            df["Close"].iloc[-1] > df["High"].iloc[prev_sh_idx]):
            return "BULLISH_CISD"
        if (df["High"].iloc[last_sh_idx] > df["High"].iloc[prev_sh_idx] and 
            df["Close"].iloc[-1] < df["Low"].iloc[prev_sl_idx]):
            return "BEARISH_CISD"
    return None

# ==================== VOLUME, ADX, POC ====================
def check_volume_strength(df, lookback=20, multiplier=1.5):
    if "Volume" not in df.columns or df["Volume"].sum() == 0:
        return "N/A", "N/A"
    if len(df) < lookback:
        avg_vol = df["Volume"].mean()
    else:
        avg_vol = df["Volume"].iloc[-lookback:-1].mean()
    last_vol = df["Volume"].iloc[-1]
    if avg_vol == 0:
        return "N/A", "N/A"
    ratio = last_vol / avg_vol
    if ratio >= multiplier:
        return "STRONG", f"{ratio:.1f}x avg"
    elif ratio >= 1.0:
        return "MODERATE", f"{ratio:.1f}x avg"
    else:
        return "WEAK", f"{ratio:.1f}x avg"

def calculate_adx(df, period=14):
    if len(df) < period + 1:
        return 0, "N/A"
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0
    minus_dm = abs(minus_dm)
    tr = pd.concat([high - low, abs(high - close.shift()), abs(low - close.shift())], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(period).mean().iloc[-1]
    if pd.isna(adx):
        return 0, "N/A"
    status = "TREN KUAT" if adx > 25 else ("RANGING" if adx < 20 else "TREN MODERAT")
    return round(adx, 2), status

def find_poc(df, lookback=50):
    if "Volume" not in df.columns or len(df) < lookback:
        return None, None
    df_slice = df.iloc[-lookback:]
    max_vol_idx = df_slice["Volume"].idxmax()
    if max_vol_idx in df_slice.index:
        poc_price = df_slice.loc[max_vol_idx, "Close"]
        return round(poc_price, 2), f"PoC di {poc_price:.2f}"
    return None, None

# ==================== FILTER LANJUTAN ====================
def detect_inducement(df, zone_high, zone_low, direction):
    if len(df) < 10:
        return False, "Data tidak cukup"
    recent = df.iloc[-10:]
    if direction == "BUY":
        lows = recent["Low"].values
        for i in range(1, len(lows)):
            if lows[i] < lows[i-1]:
                return True, f"⚠️ Inducement (Sell trap di {lows[i]:.2f})"
    else:
        highs = recent["High"].values
        for i in range(1, len(highs)):
            if highs[i] > highs[i-1]:
                return True, f"⚠️ Inducement (Buy trap di {highs[i]:.2f})"
    return False, "Tidak ada inducement"

def detect_breaker_block(df, zone_high, zone_low, direction):
    if len(df) < 20:
        return False, "Data tidak cukup"
    for i in range(len(df)-20, len(df)):
        if df["High"].iloc[i] > zone_high and df["Low"].iloc[i] < zone_low:
            return True, "⚠️ Breaker Block (zona sudah ditembus)"
    return False, "Zona masih Fresh"

def detect_choch(df):
    if len(df) < 10:
        return None, "Data tidak cukup"
    sh, sl = find_swings(df.iloc[-15:], strength=2)
    if len(sh) >= 3 and len(sl) >= 3:
        if (df["High"].iloc[sh[-1]] > df["High"].iloc[sh[-2]] and 
            df["Low"].iloc[sl[-1]] > df["Low"].iloc[sl[-2]]):
            return "BULLISH_CHOCH", "🔥 CHoCH Bullish"
        if (df["High"].iloc[sh[-1]] < df["High"].iloc[sh[-2]] and 
            df["Low"].iloc[sl[-1]] < df["Low"].iloc[sl[-2]]):
            return "BEARISH_CHOCH", "🔥 CHoCH Bearish"
    return None, "Belum ada CHoCH"

def detect_bos_bpr(df):
    if len(df) < 15:
        return False, "Data tidak cukup"
    sh, sl = find_swings(df.iloc[-15:], strength=2)
    last_close = df["Close"].iloc[-1]
    if len(sh) >= 1 and last_close > df["High"].iloc[sh[-1]]:
        return True, "✅ BOS Bullish"
    if len(sl) >= 1 and last_close < df["Low"].iloc[sl[-1]]:
        return True, "✅ BOS Bearish"
    range_high = df["High"].iloc[-5:].max()
    range_low = df["Low"].iloc[-5:].min()
    if last_close > range_high:
        return True, "✅ BPR Bullish"
    if last_close < range_low:
        return True, "✅ BPR Bearish"
    return False, "Belum ada BOS/BPR"

# ==================== PIVOT, EQH/EQL, PREMIUM, PATTERN, QM ====================
def calculate_pivots(daily_df):
    if daily_df is None or daily_df.empty:
        return None, None, None, None, None, None, None
    last = daily_df.iloc[-1]
    high, low, close = float(last["High"]), float(last["Low"]), float(last["Close"])
    pivot = (high + low + close) / 3
    return (round(pivot, 2), round(2*pivot-low, 2), round(pivot + high - low, 2), round(high + 2*(pivot-low), 2),
            round(2*pivot-high, 2), round(pivot - (high-low), 2), round(low - 2*(high-pivot), 2))

def detect_eqh_eql(df, strength=2, tolerance=0.5):
    sh_idx, sl_idx = find_swings(df, strength)
    swing_highs = [float(df["High"].iloc[i]) for i in sh_idx]
    swing_lows = [float(df["Low"].iloc[i]) for i in sl_idx]
    eqh, eql = [], []
    for i in range(len(swing_highs)):
        for j in range(i+1, len(swing_highs)):
            if abs(swing_highs[i] - swing_highs[j]) <= tolerance:
                eqh.append(round((swing_highs[i]+swing_highs[j])/2, 2))
    for i in range(len(swing_lows)):
        for j in range(i+1, len(swing_lows)):
            if abs(swing_lows[i] - swing_lows[j]) <= tolerance:
                eql.append(round((swing_lows[i]+swing_lows[j])/2, 2))
    return list(set(eqh))[:3], list(set(eql))[:3]

def calculate_premium_discount(price, range_high, range_low):
    if range_high == range_low:
        return 0, "NEUTRAL", 0
    mid = (range_high + range_low) / 2
    diff_pct = ((price - mid) / (range_high - range_low)) * 100
    if diff_pct > 10: status = "PREMIUM (Overbought)"
    elif diff_pct < -10: status = "DISCOUNT (Oversold)"
    else: status = "EQUILIBRIUM (Fair Value)"
    return round(diff_pct, 1), status, round(mid, 2)

def detect_chart_patterns(df, strength=2):
    if len(df) < 10:
        return ["Data terlalu sedikit"]
    sh_idx, sl_idx = find_swings(df.iloc[-30:], strength=2)
    patterns = []
    if len(sh_idx) >= 3:
        highs = [float(df["High"].iloc[i]) for i in sh_idx[-5:]]
        if len(highs) >= 2 and abs(highs[-1] - highs[-2]) < 1.5:
            patterns.append("🔺 Double Top")
        if len(highs) >= 3 and highs[-2] > highs[-1] and highs[-2] > highs[-3]:
            patterns.append("🔺 H&S")
    if len(sl_idx) >= 3:
        lows = [float(df["Low"].iloc[i]) for i in sl_idx[-5:]]
        if len(lows) >= 2 and abs(lows[-1] - lows[-2]) < 1.5:
            patterns.append("🔻 Double Bottom")
        if len(lows) >= 3 and lows[-2] < lows[-1] and lows[-2] < lows[-3]:
            patterns.append("🔻 Inverse H&S")
    if len(df) >= 10:
        range_20 = (df["High"].iloc[-10:] - df["Low"].iloc[-10:]).mean()
        range_50 = (df["High"].iloc[-50:] - df["Low"].iloc[-50:]).mean() if len(df) >= 50 else range_20 * 1.5
        if range_20 < range_50 * 0.6:
            patterns.append("🏁 Flag" if df["Close"].iloc[-1] > df["Close"].iloc[-5] else "🏁 Flag (bearish)")
    return patterns if patterns else ["📊 Tidak ada pola"]

def calculate_qm_levels(df, atr_mult=2.0):
    if df is None or df.empty or len(df) < 20:
        return []
    price = float(df["Close"].iloc[-1])
    atr = float((df["High"] - df["Low"]).rolling(14).mean().iloc[-1])
    if pd.isna(atr) or atr <= 0:
        atr = price * 0.001
    vwap = (df["Close"] * df["Volume"]).sum() / df["Volume"].sum() if "Volume" in df.columns else price
    return [
        {"level": round(price + atr*0.5, 2), "type": "QM R1"},
        {"level": round(price - atr*0.5, 2), "type": "QM S1"},
        {"level": round(price + atr*1.0, 2), "type": "QM R2"},
        {"level": round(price - atr*1.0, 2), "type": "QM S2"},
        {"level": round(price + atr*1.5, 2), "type": "QM R3"},
        {"level": round(price - atr*1.5, 2), "type": "QM S3"},
        {"level": round(vwap, 2), "type": "QM VWAP"}
    ]

def get_daily_bias_description(df, price, bsl, ssl, eqh, eql, pivot_data, premium_status, patterns, qm_levels):
    if df is None or df.empty:
        return "Data harian tidak tersedia."
    sh, sl = find_swings(df, 2)
    bull, bear = detect_bos(df, sh, sl)
    bias = "BULLISH" if bull else ("BEARISH" if bear else "NEUTRAL")
    ema20 = df["Close"].rolling(20).mean().iloc[-1]
    above_ema = price > ema20
    cisd = detect_cisd(df)
    desc = f"**Kondisi Harian ({bias}):** "
    if bias == "BULLISH":
        desc += "Uptrend. Harga " + ("di atas" if above_ema else "di bawah") + " EMA 20. "
    elif bias == "BEARISH":
        desc += "Downtrend. Harga " + ("di atas" if above_ema else "di bawah") + " EMA 20. "
    else:
        desc += "Konsolidasi (range). "
    if cisd == "BULLISH_CISD": desc += "**CISD Bullish**. "
    elif cisd == "BEARISH_CISD": desc += "**CISD Bearish**. "
    if pivot_data:
        pivot, r1, r2, r3, s1, s2, s3 = pivot_data
        desc += f"Pivot: {pivot:.2f} | R1:{r1:.2f} R2:{r2:.2f} R3:{r3:.2f} | S1:{s1:.2f} S2:{s2:.2f} S3:{s3:.2f}. "
    if eqh: desc += f"EQH: {', '.join([str(e) for e in eqh[:3]])}. "
    if eql: desc += f"EQL: {', '.join([str(e) for e in eql[:3]])}. "
    desc += f"Status: {premium_status}. "
    if patterns: desc += f"Pattern: {', '.join(patterns[:2])}. "
    if qm_levels:
        nearest_qm = min(qm_levels, key=lambda x: abs(x["level"] - price))
        desc += f"QM terdekat: {nearest_qm['type']} @ {nearest_qm['level']:.2f}. "
    desc += f"ATR: {round((df['High'] - df['Low']).rolling(14).mean().iloc[-1], 2)}."
    return desc

# ==================== SIGNAL GENERATOR ====================
def generate_all_signals(symbol="XAUUSD", mode="M5", exec_mode="Konservatif"):
    dfs = fetch_all_timeframes(symbol)
    if not dfs:
        return None, None, None, None, None, None, None, None, None, None, None, None, None, None, "Data tidak lengkap."

    daily_df = dfs.get("1d")
    if daily_df is None or daily_df.empty or len(daily_df) < 10:
        return None, None, None, None, None, None, None, None, None, None, None, None, None, None, "Data daily tidak cukup."

    sh_d, sl_d = find_swings(daily_df, 2)
    bull_bias, bear_bias = detect_bos(daily_df, sh_d, sl_d)
    bias = "BUY" if bull_bias else ("SELL" if bear_bias else "NEUTRAL")

    htf_df = dfs.get("4h")
    if htf_df is None or htf_df.empty:
        htf_df = daily_df
    sh_htf, sl_htf = find_swings(htf_df, 2)
    bsl = float(htf_df["High"].iloc[sh_htf[-1]]) if len(sh_htf) >= 1 else None
    ssl = float(htf_df["Low"].iloc[sl_htf[-1]]) if len(sl_htf) >= 1 else None

    pivot_data = calculate_pivots(daily_df)
    eqh, eql = detect_eqh_eql(htf_df if len(htf_df) > 20 else daily_df, strength=2, tolerance=1.0)
    range_high = float(daily_df["High"].iloc[-5:].max())
    range_low = float(daily_df["Low"].iloc[-5:].min())

    # ========== Tentukan Timeframe ==========
    if mode == "M3":
        df_1m = dfs.get("1m")
        if df_1m is not None and not df_1m.empty:
            try:
                df_3m = df_1m.resample('3T').agg({
                    'Open': 'first',
                    'High': 'max',
                    'Low': 'min',
                    'Close': 'last',
                    'Volume': 'sum'
                }).dropna()
                if not df_3m.empty:
                    dfs["3m"] = df_3m
                    zone_tf = "3m"
                    entry_tf = "1m"
                    base_sl_mult = 0.5
                    max_dist = 3.0
                else:
                    st.warning("⚠️ Gagal membuat data 3m (kosong), fallback ke M5")
                    mode = "M5"
                    zone_tf = "5m"
                    entry_tf = "5m"
                    base_sl_mult = 0.6
                    max_dist = 3.0
            except Exception as e:
                st.warning(f"⚠️ Error resample 3m: {e}, fallback ke M5")
                mode = "M5"
                zone_tf = "5m"
                entry_tf = "5m"
                base_sl_mult = 0.6
                max_dist = 3.0
        else:
            st.warning("⚠️ Data 1m tidak tersedia, fallback ke M5")
            mode = "M5"
            zone_tf = "5m"
            entry_tf = "5m"
            base_sl_mult = 0.6
            max_dist = 3.0
    elif mode == "M5":
        zone_tf = "5m"
        entry_tf = "5m"
        base_sl_mult = 0.6
        max_dist = 3.0
    else:  # Intraday
        zone_tf = "1h"
        entry_tf = "15m"
        base_sl_mult = 1.5
        max_dist = 5.0

    zone_df = dfs.get(zone_tf)
    if zone_df is None or zone_df.empty:
        zone_df = dfs.get("1h")
    if zone_df is None or zone_df.empty or len(zone_df) < 10:
        return None, None, None, None, None, None, None, None, None, None, None, None, None, None, f"Data zona ({zone_tf}) tidak cukup."

    entry_df = dfs.get(entry_tf)
    if entry_df is None or entry_df.empty:
        entry_df = zone_df
    price = float(entry_df["Close"].iloc[-1])
    atr = float((entry_df["High"] - entry_df["Low"]).rolling(14).mean().iloc[-1])
    if pd.isna(atr) or atr <= 0:
        atr = price * 0.001

    # ========== Volatilitas ==========
    if atr < 8:
        vol_label = "RENDAH"
    elif atr < 15:
        vol_label = "SEDANG"
    elif atr < 25:
        vol_label = "TINGGI"
    else:
        vol_label = "SANGAT TINGGI"

    # ========== Batas SL untuk Scalping ==========
    if mode in ["M3", "M5"]:
        if mode == "M3":
            max_sl_points = 12.0 if vol_label == "SANGAT TINGGI" else (8.0 if vol_label == "TINGGI" else 6.0)
        else:  # M5
            max_sl_points = 15.0 if vol_label == "SANGAT TINGGI" else (10.0 if vol_label == "TINGGI" else 8.0)
        sl_calc = atr * base_sl_mult
        sl_mult = max_sl_points / atr if sl_calc > max_sl_points else base_sl_mult
    else:
        sl_mult = base_sl_mult

    cisd = detect_cisd(entry_df)
    premium_pct, premium_status, equilibrium = calculate_premium_discount(price, range_high, range_low)
    patterns = detect_chart_patterns(zone_df if len(zone_df) > 20 else entry_df, strength=2)
    qm_levels = calculate_qm_levels(entry_df if len(entry_df) > 20 else zone_df, atr_mult=1.5)

    nearest_highs, nearest_lows = get_swing_levels(entry_df if entry_tf in dfs else zone_df, n=3)
    if len(nearest_highs) < 2:
        nearest_highs = nearest_highs + [bsl] if bsl else nearest_highs
    if len(nearest_lows) < 2:
        nearest_lows = nearest_lows + [ssl] if ssl else nearest_lows

    sh_z, sl_z = find_swings(zone_df, 2)
    supply_zones, demand_zones = [], []
    for idx in sh_z[-8:]:
        ob = find_ob(zone_df, "bear", idx)
        if ob:
            supply_zones.append(ob)
    for idx in sl_z[-8:]:
        ob = find_ob(zone_df, "bull", idx)
        if ob:
            demand_zones.append(ob)
    fvg = find_fvg(zone_df)
    if fvg:
        if fvg["type"] == "bearish":
            supply_zones.append({"high": fvg["top"], "low": fvg["bottom"]})
        elif fvg["type"] == "bullish":
            demand_zones.append({"high": fvg["top"], "low": fvg["bottom"]})

    best_supply, best_demand = None, None
    for z in supply_zones:
        if z["high"] > price and (z["high"] - price) < max_dist * atr:
            if best_supply is None or z["high"] < best_supply["high"]:
                best_supply = z
    for z in demand_zones:
        if z["low"] < price and (price - z["low"]) < max_dist * atr:
            if best_demand is None or z["low"] > best_demand["low"]:
                best_demand = z

    # ========== VOLUME, ADX, POC ==========
    vol_status, vol_detail = check_volume_strength(entry_df)
    adx_val, adx_status = calculate_adx(entry_df)
    poc_price, poc_detail = find_poc(entry_df)
    poc_confluence = False
    if poc_price:
        if (best_supply and best_supply["low"] <= poc_price <= best_supply["high"]) or \
           (best_demand and best_demand["low"] <= poc_price <= best_demand["high"]):
            poc_confluence = True

    # ========== FILTER FUNCTIONS ==========
    def check_rejection_candle(df, zone_high, zone_low, direction):
        if len(df) < 2:
            return False, "Data candle tidak cukup"
        last = df.iloc[-1]
        body = abs(last["Close"] - last["Open"])
        if body == 0:
            return False, "Doji, tunggu konfirmasi"
        if direction == "BUY":
            lower_wick = min(last["Open"], last["Close"]) - last["Low"]
            if last["Low"] <= zone_high and last["Low"] >= zone_low:
                return lower_wick > body * 1.5, "✅ Rejection" if lower_wick > body * 1.5 else "❌ Wick kecil"
            return False, "Belum sentuh zona"
        else:
            upper_wick = last["High"] - max(last["Open"], last["Close"])
            if last["High"] >= zone_low and last["High"] <= zone_high:
                return upper_wick > body * 1.5, "✅ Rejection" if upper_wick > body * 1.5 else "❌ Wick kecil"
            return False, "Belum sentuh zona"

    def check_approach_speed(df):
        if len(df) < 6:
            return True, "Data tidak cukup"
        avg_range = (df["High"].iloc[-6:-1] - df["Low"].iloc[-6:-1]).mean()
        last_range = df["High"].iloc[-1] - df["Low"].iloc[-1]
        return (last_range <= 1.5 * avg_range), "✅ Slowdown" if last_range <= 1.5 * avg_range else "🔥 Momentum tinggi"

    def check_bias_confluence(direction, daily_bias, cisd):
        if daily_bias == "NEUTRAL":
            return True, "Bias netral"
        if direction == daily_bias:
            return True, f"✅ Searah {daily_bias}"
        if direction == "BUY" and daily_bias == "SELL" and cisd == "BULLISH_CISD":
            return True, "⚠️ Berlawanan tapi ada CISD Bullish"
        if direction == "SELL" and daily_bias == "BUY" and cisd == "BEARISH_CISD":
            return True, "⚠️ Berlawanan tapi ada CISD Bearish"
        return False, f"❌ Melawan {daily_bias}"

    def mitigate_entry(zone, direction):
        zone_width = zone["high"] - zone["low"]
        if direction == "BUY":
            return round(zone["low"] + (zone_width * 0.382), 2)
        else:
            return round(zone["high"] - (zone_width * 0.382), 2)

    def run_all_filters(zone, direction):
        wick_ok, wick_msg = check_rejection_candle(entry_df, zone["high"], zone["low"], direction)
        speed_ok, speed_msg = check_approach_speed(entry_df)
        bias_ok, bias_msg = check_bias_confluence(direction, bias, cisd)
        induce_ok, induce_msg = detect_inducement(entry_df, zone["high"], zone["low"], direction)
        breaker_ok, breaker_msg = detect_breaker_block(entry_df, zone["high"], zone["low"], direction)
        choch_type, choch_msg = detect_choch(entry_df)
        bos_ok, bos_msg = detect_bos_bpr(entry_df)

        all_passed = all([wick_ok, speed_ok, bias_ok, not induce_ok, not breaker_ok])
        if all_passed:
            status = "✅ ZONE VALID"
            risk = "SAFE"
        elif induce_ok: status = "⚠️ INDUCEMENT DETECTED"; risk = "HIGH RISK"
        elif breaker_ok: status = "⚠️ BREAKER BLOCK"; risk = "HIGH RISK"
        elif not wick_ok and "Belum sentuh zona" in wick_msg: status = "⏳ NEEDS WICK"; risk = "NEED CONFIRMATION"
        elif not wick_ok: status = "⚠️ FAKE ZONE"; risk = "HIGH RISK"
        elif not speed_ok: status = "🔥 TOO FAST"; risk = "HIGH RISK"
        elif not bias_ok: status = "🚫 BIAS CONFLICT"; risk = "HIGH RISK"
        else: status = "⚠️ UNKNOWN"; risk = "HIGH RISK"

        if choch_type: status += f" | {choch_msg}"
        if bos_ok: status += f" | {bos_msg}"

        extra_msgs = [
            f"📊 VOL: {vol_status} ({vol_detail})",
            f"📈 ADX: {adx_val} ({adx_status})",
            f"⚡ Volatilitas: {vol_label} (ATR={atr:.2f})",
        ]
        if mode in ["M3", "M5"]:
            extra_msgs.append(f"🛡️ SL ~ {atr*sl_mult:.2f} poin (max {max_sl_points})")
        if poc_price: extra_msgs.append(f"🎯 PoC: {poc_price}")
        if poc_confluence: extra_msgs.append("🔥 PoC CONFLUENCE!")

        return status, risk, [wick_msg, speed_msg, bias_msg, induce_msg, breaker_msg] + extra_msgs

    def build_order(order_type, direction, entry, sl, tp1, tp2, tp3, reason, zone_info="", validation_status="", risk_label="SAFE", filter_msgs=None):
        return {
            "type": order_type, "direction": direction,
            "entry": round(entry, 2), "sl": round(sl, 2),
            "tp1": round(tp1, 2), "tp2": round(tp2, 2), "tp3": round(tp3, 2),
            "reason": reason, "zone_info": zone_info,
            "validation_status": validation_status,
            "risk_label": risk_label,
            "filter_msgs": filter_msgs if filter_msgs else []
        }

    def calc_tp_rr(entry, sl, direction):
        risk = abs(entry - sl)
        if risk < 0.01: risk = 1.0
        if direction == "BUY":
            return round(entry + risk*1.2, 2), round(entry + risk*2.0, 2), round(entry + risk*4.0, 2)
        else:
            return round(entry - risk*1.2, 2), round(entry - risk*2.0, 2), round(entry - risk*4.0, 2)

    orders = {"sell": None, "buy": None}
    best_direction = None

    # === KONSERVATIF (LIMIT) ===
    if exec_mode == "Konservatif":
        if best_supply:
            entry = mitigate_entry(best_supply, "SELL")
            sl = best_supply["high"] + (atr * sl_mult)
            tp1, tp2, tp3 = calc_tp_rr(entry, sl, "SELL")
            val_status, risk_label, filter_msgs = run_all_filters(best_supply, "SELL")
            orders["sell"] = build_order("LIMIT", "SELL", entry, sl, tp1, tp2, tp3,
                f"Sell Limit di Supply OB {best_supply['low']:.2f}-{best_supply['high']:.2f}",
                f"OB: {best_supply['low']:.2f}-{best_supply['high']:.2f}",
                val_status, risk_label, filter_msgs)
        if best_demand:
            entry = mitigate_entry(best_demand, "BUY")
            sl = best_demand["low"] - (atr * sl_mult)
            tp1, tp2, tp3 = calc_tp_rr(entry, sl, "BUY")
            val_status, risk_label, filter_msgs = run_all_filters(best_demand, "BUY")
            orders["buy"] = build_order("LIMIT", "BUY", entry, sl, tp1, tp2, tp3,
                f"Buy Limit di Demand OB {best_demand['low']:.2f}-{best_demand['high']:.2f}",
                f"OB: {best_demand['low']:.2f}-{best_demand['high']:.2f}",
                val_status, risk_label, filter_msgs)

    # === AGRESIF (MARKET NOW) ===
    else:
        sell_score, buy_score = 50, 50
        if bias == "SELL": sell_score += 20
        elif bias == "BUY": buy_score += 20
        if cisd == "BEARISH_CISD": sell_score += 15
        elif cisd == "BULLISH_CISD": buy_score += 15
        if best_supply: sell_score += 15
        if best_demand: buy_score += 15
        if nearest_lows and (price - nearest_lows[0]) < atr * 2: sell_score += 10
        if nearest_highs and (nearest_highs[0] - price) < atr * 2: buy_score += 10

        total = sell_score + buy_score
        if total == 0:
            sell_pct, buy_pct = 50, 50
        else:
            sell_pct = round((sell_score / total) * 100)
            buy_pct = 100 - sell_pct

        if sell_pct >= 60:
            best_direction = "SELL"
        elif buy_pct >= 60:
            best_direction = "BUY"
        else:
            best_direction = None

        if best_direction == "SELL":
            entry = price
            sl = price + (atr * 0.6)
            tp1, tp2, tp3 = calc_tp_rr(entry, sl, "SELL")
            val_status = "🚀 AGRESIF (Market SELL)"
            risk_label = "HIGH RISK"
            filter_msgs = [
                f"📊 VOL: {vol_status} ({vol_detail})",
                f"📈 ADX: {adx_val} ({adx_status})",
                f"⚡ Volatilitas: {vol_label}",
                f"📉 Konfidence SELL: {sell_pct}%",
                f"🎯 Entry di harga spot: {price}"
            ]
            orders["sell"] = build_order("MARKET", "SELL", entry, sl, tp1, tp2, tp3,
                f"Sell Now (Market) di {price}",
                f"Spot: {price}", val_status, risk_label, filter_msgs)

        elif best_direction == "BUY":
            entry = price
            sl = price - (atr * 0.6)
            tp1, tp2, tp3 = calc_tp_rr(entry, sl, "BUY")
            val_status = "🚀 AGRESIF (Market BUY)"
            risk_label = "HIGH RISK"
            filter_msgs = [
                f"📊 VOL: {vol_status} ({vol_detail})",
                f"📈 ADX: {adx_val} ({adx_status})",
                f"⚡ Volatilitas: {vol_label}",
                f"📈 Konfidence BUY: {buy_pct}%",
                f"🎯 Entry di harga spot: {price}"
            ]
            orders["buy"] = build_order("MARKET", "BUY", entry, sl, tp1, tp2, tp3,
                f"Buy Now (Market) di {price}",
                f"Spot: {price}", val_status, risk_label, filter_msgs)

    # === Confidence & Confluence ===
    sell_score, buy_score = 50, 50
    if bias == "SELL": sell_score += 20
    elif bias == "BUY": buy_score += 20
    if cisd == "BEARISH_CISD": sell_score += 15
    elif cisd == "BULLISH_CISD": buy_score += 15
    if best_supply is not None: sell_score += 15
    if best_demand is not None: buy_score += 15
    if nearest_lows and (price - nearest_lows[0]) < atr * 2: sell_score += 10
    if nearest_highs and (nearest_highs[0] - price) < atr * 2: buy_score += 10

    total = sell_score + buy_score
    if total == 0: sell_pct, buy_pct = 50, 50
    else: sell_pct = round((sell_score / total) * 100); buy_pct = 100 - sell_pct

    if sell_pct >= 65: rec_direction = "SELL"; rec_label = "RECOMMENDED" if sell_pct >= 75 else "HIGH RISK"
    elif buy_pct >= 65: rec_direction = "BUY"; rec_label = "RECOMMENDED" if buy_pct >= 75 else "HIGH RISK"
    else: rec_direction = "NEUTRAL"; rec_label = "WAIT & SEE"
    confidence = {"sell": sell_pct, "buy": buy_pct, "direction": rec_direction, "label": rec_label}

    # === Buat Confluence Description ===
    diff = abs(sell_pct - buy_pct)
    if diff > 20:
        if sell_pct > buy_pct:
            confluence_desc = "SELLER STRONG, BUYER WEAK"
        else:
            confluence_desc = "BUYER STRONG, SELLER WEAK"
    else:
        confluence_desc = "SIDEWAYS / NEUTRAL (gunakan momentum)"
    confluence = {"sell": sell_pct, "buy": buy_pct, "desc": confluence_desc}

    return (
        orders, bsl, ssl, bias, nearest_highs, nearest_lows, confidence,
        pivot_data, eqh, eql, premium_status, patterns, qm_levels,
        equilibrium, premium_pct, confluence
    )

# ==================== SESSION STATE ====================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None
    st.session_state.nama = None
    st.session_state.mode = "M5"
    st.session_state.exec_mode = "Konservatif"
    st.session_state.triggered_orders = []
    st.session_state.trigger_counter = 0
    st.session_state.saved_user = ""
    st.session_state.saved_pass = ""
    st.session_state.refresh_agresif = 0

st.set_page_config(page_title="XAUUSD - Alu System", page_icon="🥇", layout="wide")
init_db()

# ==================== CSS ====================
st.markdown("""
<style>
    .stApp { background: #0E1117; }
    .sell-card { background: linear-gradient(145deg, #2a0f0f, #1a0808); border: 2px solid #ff4444; border-radius: 20px; padding: 18px; margin: 10px 0; color: #fff; box-shadow: 0 4px 15px rgba(255,68,68,0.2); }
    .buy-card { background: linear-gradient(145deg, #0f2a1a, #08180d); border: 2px solid #00ff88; border-radius: 20px; padding: 18px; margin: 10px 0; color: #fff; box-shadow: 0 4px 15px rgba(0,255,136,0.2); }
    .conf-card { background: #1a1a2e; border: 2px solid #ffaa00; border-radius: 20px; padding: 15px 20px; margin: 10px 0; color: #fff; }
    .desc-box { background: #1a1a2e; border-radius: 16px; padding: 15px; margin: 10px 0; border-left: 4px solid #FFD700; color: #ccc; font-size: 0.95rem; line-height: 1.6; }
    .signal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
    .signal-title { font-size: 1.2rem; font-weight: bold; margin: 0; }
    .signal-price { font-size: 1.4rem; font-weight: bold; background: rgba(0,0,0,0.4); padding: 2px 16px; border-radius: 30px; font-family: monospace; }
    .chip-container { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
    .chip { background: rgba(20, 25, 40, 0.8); padding: 4px 14px; border-radius: 30px; font-size: 0.85rem; border: 1px solid #2a3240; white-space: nowrap; }
    .chip-sl { color: #ff6666; border-color: #ff4444; }
    .chip-tp { color: #66ff88; border-color: #00ff8855; }
    .chip-tp1 { color: #ffaa00; border-color: #ffaa00; }
    .risk-safe { background: #00ff8822; border: 1px solid #00ff88; color: #00ff88; padding: 2px 12px; border-radius: 30px; font-size: 0.75rem; }
    .risk-high { background: #ff444422; border: 1px solid #ff4444; color: #ff4444; padding: 2px 12px; border-radius: 30px; font-size: 0.75rem; }
    .risk-wait { background: #ffaa0022; border: 1px solid #ffaa00; color: #ffaa00; padding: 2px 12px; border-radius: 30px; font-size: 0.75rem; }
    .zone-footer { font-size: 0.75rem; color: #aaa; margin-top: 8px; padding-top: 8px; border-top: 1px solid #2a3240; }
    .liquidity-badge { background: #ffaa0022; border: 1px solid #ffaa00; border-radius: 12px; padding: 4px 12px; font-size: 0.8rem; color: #ffaa00; }
    .bias-badge { display: inline-block; padding: 5px 15px; border-radius: 20px; font-weight: bold; background: #2a3240; color: #ccc; }
    .bias-buy { background: #00ff8822; border: 1px solid #00ff88; color: #00ff88; }
    .bias-sell { background: #ff444422; border: 1px solid #ff4444; color: #ff4444; }
    .bias-neutral { background: #ffaa0022; border: 1px solid #ffaa00; color: #ffaa00; }
    .header-title { font-size: 2.5rem; font-weight: bold; color: #FFD700; margin-bottom: 0; }
    .ohlc-box { background: #1a1a2e; border-radius: 12px; padding: 8px 14px; display: inline-block; margin-right: 8px; border: 1px solid #2a3240; }
    .ohlc-label { color: #888; font-size: 0.6rem; text-transform: uppercase; }
    .ohlc-value { font-weight: bold; font-family: monospace; font-size: 1rem; }
    .order-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .footer { text-align: center; color: #555; padding: 20px 0; font-size: 0.8rem; border-top: 1px solid #1a1a2a; margin-top: 30px; }
    .tech-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin: 10px 0; }
    .tech-item { background: #1a1a2e; border-radius: 12px; padding: 10px 14px; border: 1px solid #2a3240; text-align: center; }
    .tech-item .label { color: #888; font-size: 0.7rem; text-transform: uppercase; }
    .tech-item .value { font-weight: bold; font-size: 1rem; }
    .badge-valid { background: #00ff8822; border: 1px solid #00ff88; color: #00ff88; padding: 2px 12px; border-radius: 30px; font-size: 0.65rem; }
    .badge-fake { background: #ff444422; border: 1px solid #ff4444; color: #ff4444; padding: 2px 12px; border-radius: 30px; font-size: 0.65rem; }
    .badge-wait { background: #ffaa0022; border: 1px solid #ffaa00; color: #ffaa00; padding: 2px 12px; border-radius: 30px; font-size: 0.65rem; }
    .badge-toofast { background: #ff660022; border: 1px solid #ff6600; color: #ff6600; padding: 2px 12px; border-radius: 30px; font-size: 0.65rem; }
    .badge-induce { background: #ff880022; border: 1px solid #ff8800; color: #ff8800; padding: 2px 12px; border-radius: 30px; font-size: 0.65rem; }
    .badge-breaker { background: #8800ff22; border: 1px solid #8800ff; color: #8800ff; padding: 2px 12px; border-radius: 30px; font-size: 0.65rem; }
    .badge-poc { background: #00ffcc22; border: 1px solid #00ffcc; color: #00ffcc; padding: 2px 12px; border-radius: 30px; font-size: 0.65rem; }
    .confluence-badge { background: #222; border-radius: 30px; padding: 4px 16px; font-weight: bold; display: inline-block; }
    .confluence-strong-sell { background: #ff444422; border: 1px solid #ff4444; color: #ff4444; }
    .confluence-strong-buy { background: #00ff8822; border: 1px solid #00ff88; color: #00ff88; }
    .confluence-neutral { background: #ffaa0022; border: 1px solid #ffaa00; color: #ffaa00; }
</style>
""", unsafe_allow_html=True)

# ==================== LOGIN ====================
if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("<br><br><h1 style='text-align:center;color:#FFD700;'>🥇 XAUUSD SYSTEM</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align:center;color:#888;'>Konservatif (Limit) atau Agresif (Market)</p><br>", unsafe_allow_html=True)
        role = st.radio("Login sebagai:", ["User", "Admin"], horizontal=True)
        u = st.text_input("Username", value=st.session_state.saved_user)
        p = st.text_input("Password", type="password", value=st.session_state.saved_pass)
        remember = st.checkbox("🔐 Ingat saya", value=bool(st.session_state.saved_user))
        if st.button("🔓 MASUK", use_container_width=True):
            success = False
            if role == "Admin":
                if verify_admin(u, p):
                    st.session_state.logged_in = True
                    st.session_state.role = "admin"
                    success = True
                else:
                    st.error("❌ Admin salah")
            else:
                nama, err = verify_user(u, p)
                if nama:
                    st.session_state.logged_in = True
                    st.session_state.role = "user"
                    st.session_state.nama = nama
                    success = True
                else:
                    st.error(f"❌ {err}")
            if success:
                if remember:
                    st.session_state.saved_user = u
                    st.session_state.saved_pass = p
                else:
                    st.session_state.saved_user = ""
                    st.session_state.saved_pass = ""
                st.rerun()

# ==================== ADMIN ====================
elif st.session_state.role == "admin":
    st.sidebar.markdown("<h2 style='color:#00ff88;'>👑 ADMIN</h2>", unsafe_allow_html=True)
    if st.sidebar.button("🚪 LOGOUT"):
        st.session_state.logged_in = False
        st.rerun()
    st.title("Admin Panel")
    tabs = st.tabs(["➕ Generate", "🎁 Trial", "📋 Users", "⚙️ Password"])
    with tabs[0]:
        c1, c2 = st.columns(2)
        nama = c1.text_input("Nama"); email = c2.text_input("Email")
        masa = st.selectbox("Masa", [2,7,30,90,180,365], format_func=lambda x: f"{x} Hari")
        if st.button("🔑 GENERATE"):
            if nama and email:
                user, pw, exp = generate_user(nama, email, masa)
                st.code(f"Username: {user}\nPassword: {pw}\nExpired: {exp}")
    with tabs[1]:
        c1, c2 = st.columns(2)
        nama = c1.text_input("Nama", key="tn"); email = c2.text_input("Email", key="te")
        if st.button("🎁 TRIAL"):
            if nama and email:
                user, pw, exp = generate_user(nama, email, 2, is_trial=1)
                st.code(f"Username: {user}\nPassword: {pw}\nExpired: {exp}")
    with tabs[2]:
        for u in get_users():
            uid, nama, email, uname, exp, status, trial = u
            with st.expander(f"{nama} - {uname}"):
                st.write(f"Email: {email}\nExpired: {exp}")
                c1, c2 = st.columns(2)
                d = c1.number_input("Hari",1,365,30,key=f"ex{uid}")
                if c1.button("Perpanjang", key=f"eb{uid}"): extend_user(uid, d); st.rerun()
                if c2.button("Hapus", key=f"db{uid}"): delete_user(uid); st.rerun()
    with tabs[3]:
        old = st.text_input("Password Lama", type="password")
        new = st.text_input("Password Baru", type="password")
        if st.button("💾 Ganti"):
            if change_admin_password(old, new):
                st.success("✅ Berhasil diubah!")
            else:
                st.error("❌ Password lama salah")

# ==================== USER DASHBOARD ====================
else:
    # --- SIDEBAR ---
    with st.sidebar:
        st.markdown(f"<h3 style='color:#FFD700;'>👤 {st.session_state.nama}</h3>", unsafe_allow_html=True)
        components.html("""
        <div id="live-clock" style="color:#cccccc; font-size:15px; margin:5px 0 15px 0;"></div>
        <script>
        function updateClock() {
            var now = new Date();
            var options = { timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
            var timeString = now.toLocaleTimeString('en-US', options);
            var session = "";
            var hour = now.getHours();
            if (hour >= 7 && hour < 15) session = "Asia (Tokyo)";
            else if (hour >= 15 && hour < 20) session = "London";
            else if (hour >= 20 && hour < 23) session = "New York (Early)";
            else session = "New York (Late)";
            document.getElementById('live-clock').innerHTML = "🕒 " + timeString + " WIB<br>🇯🇵 " + session;
        }
        updateClock(); setInterval(updateClock, 1000);
        </script>
        """, height=65)
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT expired_date, is_trial FROM users WHERE nama=?", (st.session_state.nama,))
        row = c.fetchone()
        conn.close()
        if row:
            exp = datetime.strptime(row[0], "%Y-%m-%d")
            sisa = (exp - datetime.now()).days
            st.info(f"🎁 Trial {sisa} hari" if row[1] else f"⏳ {sisa} hari")
        st.markdown("---")
        if st.button("🔄 Refresh Signal", use_container_width=True, key="refresh_sidebar"):
            st.rerun()
        if st.button("🚪 LOGOUT", use_container_width=True):
            st.session_state.logged_in = False
            st.rerun()
        if st.button("🗑️ Clear Orders", use_container_width=True):
            st.session_state.triggered_orders = []
            st.rerun()

    # --- FETCH DATA ---
    daily_df = fetch_data("XAUUSD", "1d", "5d")
    if daily_df is not None and not daily_df.empty:
        last = daily_df.iloc[-1]
        ohlc = {"Open": round(last["Open"], 2), "High": round(last["High"], 2), 
                "Low": round(last["Low"], 2), "Close": round(last["Close"], 2)}
        sh_d, sl_d = find_swings(daily_df, 2)
        bull, bear = detect_bos(daily_df, sh_d, sl_d)
        bias = "BUY" if bull else ("SELL" if bear else "NEUTRAL")
        bias_color = "bias-buy" if bias == "BUY" else ("bias-sell" if bias == "SELL" else "bias-neutral")
    else:
        ohlc = {"Open": 0, "High": 0, "Low": 0, "Close": 0}; bias = "NEUTRAL"; bias_color = "bias-neutral"

    # --- MODE & EKSEKUSI ---
    col_mode1, col_mode2, col_mode3, col_mode4 = st.columns([1,1,1,1])
    with col_mode1:
        if st.button("⚡ M5", use_container_width=True, type="primary" if st.session_state.mode == "M5" else "secondary"):
            st.session_state.mode = "M5"; st.session_state.triggered_orders = []; st.rerun()
    with col_mode2:
        if st.button("⚡ M3", use_container_width=True, type="primary" if st.session_state.mode == "M3" else "secondary"):
            st.session_state.mode = "M3"; st.session_state.triggered_orders = []; st.rerun()
    with col_mode3:
        if st.button("📈 INTRADAY", use_container_width=True, type="primary" if st.session_state.mode == "Intraday" else "secondary"):
            st.session_state.mode = "Intraday"; st.session_state.triggered_orders = []; st.rerun()
    with col_mode4:
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()

    st.markdown("---")
    # Mode Eksekusi (hanya untuk scalping M5/M3, untuk intraday otomatis Konservatif)
    if st.session_state.mode in ["M5", "M3"]:
        exec_opts = ["🎯 Konservatif (Limit di Zona)", "🚀 Agresif (Market Now)"]
        idx = 0 if st.session_state.exec_mode == "Konservatif" else 1
        selected = st.radio("Mode Eksekusi", exec_opts, index=idx, horizontal=True)
        if selected.startswith("🎯"):
            st.session_state.exec_mode = "Konservatif"
        else:
            st.session_state.exec_mode = "Agresif"
    else:
        st.session_state.exec_mode = "Konservatif"
        st.info("📊 Intraday menggunakan Konservatif (Limit Order)")

    st.markdown("---")

    # --- GENERATE SIGNAL ---
    (
        orders, bsl, ssl, bias, near_highs, near_lows, conf,
        pivot_data, eqh, eql, premium_status, patterns, qm_levels,
        equilibrium, premium_pct, confluence
    ) = generate_all_signals("XAUUSD", mode=st.session_state.mode, exec_mode=st.session_state.exec_mode)

    # Harga spot
    try:
        df_spot = yf.download("GC=F", period="1d", interval="1m")
        spot = float(df_spot["Close"].iloc[-1]) if not df_spot.empty else ohlc["Close"]
    except:
        spot = ohlc["Close"]

    # --- HEADER ---
    col_h1, col_h2 = st.columns([2, 1])
    with col_h1:
        st.markdown("<h1 class='header-title'>🥇 XAUUSD</h1>", unsafe_allow_html=True)
        st.markdown(f"<span>Daily Bias: <span class='bias-badge {bias_color}'>{bias}</span></span>", unsafe_allow_html=True)
        if st.session_state.exec_mode == "Agresif" and st.session_state.mode in ["M5", "M3"]:
            st.caption(f"🔄 Sinyal Agresif terakhir di-refresh: {datetime.now().strftime('%H:%M:%S')}")
    with col_h2:
        st.markdown(f"""
        <div style='display:flex; flex-wrap:wrap; gap:5px; justify-content:flex-end;'>
            <div class='ohlc-box'><span class='ohlc-label'>Open</span><br><span class='ohlc-value'>{ohlc['Open']}</span></div>
            <div class='ohlc-box'><span class='ohlc-label'>High</span><br><span class='ohlc-value' style='color:#00ff88;'>{ohlc['High']}</span></div>
            <div class='ohlc-box'><span class='ohlc-label'>Low</span><br><span class='ohlc-value' style='color:#ff4444;'>{ohlc['Low']}</span></div>
            <div class='ohlc-box'><span class='ohlc-label'>Close</span><br><span class='ohlc-value'>{ohlc['Close']}</span></div>
        </div>""", unsafe_allow_html=True)

    # --- CONFLUENCE SIGNAL ---
    if confluence:
        sell_pct = confluence['sell']
        buy_pct = confluence['buy']
        desc = confluence['desc']
        if "SELLER STRONG" in desc:
            badge_class = "confluence-strong-sell"
            icon = "🔴"
        elif "BUYER STRONG" in desc:
            badge_class = "confluence-strong-buy"
            icon = "🟢"
        else:
            badge_class = "confluence-neutral"
            icon = "⏳"
        st.markdown(f"""
        <div style='display:flex; justify-content:center; gap:20px; margin:10px 0; flex-wrap:wrap;'>
            <span style='color:#ff4444;'>SELL {sell_pct}%</span>
            <span style='color:#888;'>|</span>
            <span style='color:#00ff88;'>BUY {buy_pct}%</span>
            <span class='confluence-badge {badge_class}'>{icon} {desc}</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # --- TEKNIKAL GRID ---
    pivot, r1, r2, r3, s1, s2, s3 = pivot_data if pivot_data else (0,0,0,0,0,0,0)
    eqh_str = ", ".join([str(e) for e in eqh[:3]]) if eqh else "-"
    eql_str = ", ".join([str(e) for e in eql[:3]]) if eql else "-"
    pattern_str = patterns[0] if patterns else "-"
    qm_str = min(qm_levels, key=lambda x: abs(x["level"] - spot)) if qm_levels else None
    qm_display = f"{qm_str['type']} @ {qm_str['level']}" if qm_str else "-"

    st.markdown(f"""
    <div class='tech-grid'>
        <div class='tech-item'><span class='label'>Pivot</span><br><span class='value'>{pivot}</span></div>
        <div class='tech-item'><span class='label'>R1/R2/R3</span><br><span class='value'>{r1}/{r2}/{r3}</span></div>
        <div class='tech-item'><span class='label'>S1/S2/S3</span><br><span class='value'>{s1}/{s2}/{s3}</span></div>
        <div class='tech-item'><span class='label'>EQH / EQL</span><br><span class='value'>{eqh_str}<br>{eql_str}</span></div>
        <div class='tech-item'><span class='label'>Premium/Discount</span><br><span class='value' style='color:#ffaa00;'>{premium_status} ({premium_pct}%)</span></div>
        <div class='tech-item'><span class='label'>Equilibrium</span><br><span class='value'>{equilibrium}</span></div>
        <div class='tech-item'><span class='label'>Chart Pattern</span><br><span class='value' style='color:#00ff88;'>{pattern_str}</span></div>
        <div class='tech-item'><span class='label'>QM Level</span><br><span class='value' style='color:#66ccff;'>{qm_display}</span></div>
    </div>
    """, unsafe_allow_html=True)

    # --- DESKRIPSI ---
    daily_desc = get_daily_bias_description(daily_df, spot, bsl, ssl, eqh, eql, pivot_data, premium_status, patterns, qm_levels)
    st.markdown(f"""
    <div class='desc-box'>
        <b>📝 Analisa Harian:</b> {daily_desc}
    </div>
    """, unsafe_allow_html=True)

    # --- KEY LEVEL + CONFIDENCE ---
    col_k1, col_k2, col_k3 = st.columns([1, 1, 1])
    with col_k1:
        st.markdown(f"<span class='liquidity-badge'>🎯 BSL (ERL): {bsl if bsl else '-'}</span>", unsafe_allow_html=True)
    with col_k2:
        st.markdown(f"<span class='liquidity-badge'>🎯 SSL (ERL): {ssl if ssl else '-'}</span>", unsafe_allow_html=True)
    with col_k3:
        rec_color = "🟢" if conf["direction"] == "BUY" else ("🔴" if conf["direction"] == "SELL" else "⏳")
        st.markdown(f"""
        <div class='conf-card' style='text-align:center;'>
            <b>{rec_color} {conf['direction']} | {conf['label']}</b><br>
            <span style='color:#ff4444;'>SELL {conf['sell']}%</span> 
            <span style='color:#888;'>|</span> 
            <span style='color:#00ff88;'>BUY {conf['buy']}%</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # --- CHART ---
    tv_interval = "5" if st.session_state.mode in ["M5","M3"] else "15"
    tv_html = f"""
    <div class="tradingview-widget-container" style="height:500px; margin-top:10px; border-radius:15px; overflow:hidden; border:1px solid #2a3240;">
        <div id="tv_chart"></div>
        <script src="https://s3.tradingview.com/tv.js"></script>
        <script>new TradingView.widget({{"width":"100%","height":500,"symbol":"OANDA:XAUUSD","interval":"{tv_interval}","timezone":"Asia/Jakarta","theme":"dark","style":"1","locale":"id","toolbar_bg":"#0E1117","enable_publishing":false,"hide_side_toolbar":false,"allow_symbol_change":false,"container_id":"tv_chart"}});</script>
    </div>"""
    components.html(tv_html, height=520)

    st.markdown("---")
    st.markdown("### 📊 Sinyal Eksekusi")

    # --- TRIGGER LOGIK (hanya untuk Konservatif / Limit) ---
    live_price = None
    try:
        df_live = yf.download("GC=F", period="1d", interval="1m")
        if not df_live.empty:
            live_price = float(df_live["Close"].iloc[-1])
    except: pass

    # Untuk Limit (Konservatif) kita jalankan trigger seperti biasa
    if st.session_state.exec_mode == "Konservatif" and live_price is not None:
        to_remove = []
        for o in st.session_state.triggered_orders:
            if o["status"] != "running": continue
            if o["direction"] == "BUY" and (live_price <= o["sl"] or live_price >= o["tp3"]):
                to_remove.append(o["id"])
            if o["direction"] == "SELL" and (live_price >= o["sl"] or live_price <= o["tp3"]):
                to_remove.append(o["id"])
        st.session_state.triggered_orders = [o for o in st.session_state.triggered_orders if o["id"] not in to_remove]

        # Trigger Limit
        if orders.get("sell") and orders["sell"]["type"] == "LIMIT":
            if live_price >= orders["sell"]["entry"]:
                if not any(o["entry"] == orders["sell"]["entry"] and o["status"] == "running" for o in st.session_state.triggered_orders):
                    st.session_state.triggered_orders.append({**orders["sell"], "status": "running", "id": f"SELL_{st.session_state.trigger_counter}"})
                    st.session_state.trigger_counter += 1
        if orders.get("buy") and orders["buy"]["type"] == "LIMIT":
            if live_price <= orders["buy"]["entry"]:
                if not any(o["entry"] == orders["buy"]["entry"] and o["status"] == "running" for o in st.session_state.triggered_orders):
                    st.session_state.triggered_orders.append({**orders["buy"], "status": "running", "id": f"BUY_{st.session_state.trigger_counter}"})
                    st.session_state.trigger_counter += 1

    # --- RENDER ORDER CARD ---
    def render_order_card(order, key):
        if order is None: return ""
        dir_emoji = "🔴" if order["direction"] == "SELL" else "🟢"
        card_class = "sell-card" if order["direction"] == "SELL" else "buy-card"
        status = "Pending"
        if any(o["entry"] == order["entry"] and o["status"] == "running" for o in st.session_state.triggered_orders):
            status = "✅ RUNNING"
        
        val_status = order.get("validation_status", "")
        badge_class = "badge-valid"
        if "INDUCEMENT" in val_status: badge_class = "badge-induce"
        elif "BREAKER" in val_status: badge_class = "badge-breaker"
        elif "FAKE" in val_status or "FAKE" in order.get("risk_label", ""): badge_class = "badge-fake"
        elif "TOO FAST" in val_status: badge_class = "badge-toofast"
        elif "NEEDS" in val_status or "NEED" in val_status: badge_class = "badge-wait"
        
        risk_badge = ""
        if "SAFE" in order.get("risk_label", ""): risk_badge = "<span class='risk-safe'>✅ SAFE</span>"
        elif "HIGH RISK" in order.get("risk_label", ""): risk_badge = "<span class='risk-high'>⚠️ HIGH RISK</span>"
        else: risk_badge = "<span class='risk-wait'>⏳ Need Confirmation</span>"
        
        filter_msgs = order.get("filter_msgs", [])
        filter_html = "<br>".join([f"<span style='font-size:0.7rem;color:#aaa;'>• {msg}</span>" for msg in filter_msgs[:6]])
        
        return f"""
        <div class='{card_class}'>
            <div class='signal-header'>
                <span class='signal-title'>{dir_emoji} {order['direction']} {order['type']}</span>
                <div style='display:flex; gap:5px; align-items:center; flex-wrap:wrap;'>
                    <span class='{badge_class}'>{val_status}</span>
                    {risk_badge} {status}
                </div>
            </div>
            <div style='display:flex; justify-content:space-between;'>
                <span><b>Entry</b> <span style='font-family:monospace;'>{order['entry']}</span></span>
                <span><b>SL</b> <span style='color:#ff6666;'>{order['sl']}</span></span>
            </div>
            <div class='chip-container'>
                <span class='chip chip-tp1'>🏆 TP1 (1:1.2) {order['tp1']}</span>
                <span class='chip chip-tp'>🏆 TP2 (1:2) {order['tp2']}</span>
                <span class='chip chip-tp'>🏆 TP3 (1:4) {order['tp3']}</span>
            </div>
            <div class='zone-footer'>
                <small>{order['reason']}</small><br>
                {filter_html}
            </div>
        </div>
        """

    # --- TAMPILAN 2 KOLOM (SELL / BUY) ---
    col_sell, col_buy = st.columns(2)
    with col_sell:
        st.markdown("#### 🔻 SELL Order")
        if st.session_state.exec_mode == "Agresif" and st.session_state.mode in ["M5","M3"]:
            if orders.get("sell"):
                st.markdown(render_order_card(orders["sell"], "sell"), unsafe_allow_html=True)
            elif orders.get("buy") is None:
                st.info("📭 Tidak ada sinyal agresif yang valid (arah netral)")
        else:
            if orders.get("sell"):
                st.markdown(render_order_card(orders["sell"], "sell"), unsafe_allow_html=True)
            else:
                st.info("📭 Tidak ada Supply Zone valid")
    with col_buy:
        st.markdown("#### 🔺 BUY Order")
        if st.session_state.exec_mode == "Agresif" and st.session_state.mode in ["M5","M3"]:
            if orders.get("buy"):
                st.markdown(render_order_card(orders["buy"], "buy"), unsafe_allow_html=True)
            elif orders.get("sell") is None:
                st.info("📭 Tidak ada sinyal agresif yang valid (arah netral)")
        else:
            if orders.get("buy"):
                st.markdown(render_order_card(orders["buy"], "buy"), unsafe_allow_html=True)
            else:
                st.info("📭 Tidak ada Demand Zone valid")

    # --- RUNNING ORDERS (hanya untuk Limit / Konservatif) ---
    if st.session_state.exec_mode == "Konservatif":
        running = [o for o in st.session_state.triggered_orders if o["status"] == "running"]
        if running:
            st.markdown("---")
            st.markdown("### ⚡ Running Orders (Aktif)")
            for o in running:
                emoji = "🔴" if o["direction"] == "SELL" else "🟢"
                border = "#ff4444" if o["direction"] == "SELL" else "#00ff88"
                val_status = o.get("validation_status", "")
                badge_class = "badge-valid"
                if "INDUCEMENT" in val_status: badge_class = "badge-induce"
                elif "BREAKER" in val_status: badge_class = "badge-breaker"
                elif "FAKE" in val_status or "FAKE" in o.get("risk_label", ""): badge_class = "badge-fake"
                elif "TOO FAST" in val_status: badge_class = "badge-toofast"
                elif "NEEDS" in val_status or "NEED" in val_status: badge_class = "badge-wait"
                risk_badge = ""
                if "SAFE" in o.get("risk_label", ""): risk_badge = "<span class='risk-safe'>✅ SAFE</span>"
                elif "HIGH RISK" in o.get("risk_label", ""): risk_badge = "<span class='risk-high'>⚠️ HIGH RISK</span>"
                else: risk_badge = "<span class='risk-wait'>⏳ Need Confirmation</span>"
                filter_msgs = o.get("filter_msgs", [])
                filter_html = "<br>".join([f"<span style='font-size:0.7rem;color:#aaa;'>• {msg}</span>" for msg in filter_msgs[:6]])
                st.markdown(f"""
                <div style='background:#1a1a2e; border:2px solid {border}; border-radius:20px; padding:15px; margin:10px 0;'>
                    <div style='display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;'>
                        <h3>{emoji} {o['direction']} {o['type']} RUNNING</h3>
                        <div style='display:flex; gap:5px; align-items:center; flex-wrap:wrap;'>
                            <span class='{badge_class}'>{val_status}</span>
                            {risk_badge}
                        </div>
                    </div>
                    <div class='order-grid'>
                        <div><span class='label'>Entry</span><br><b>{o['entry']}</b></div>
                        <div><span class='label'>SL</span><br><b style='color:#ff4444;'>{o['sl']}</b></div>
                        <div><span class='label'>TP1 (1:1.2)</span><br><b>{o['tp1']}</b></div>
                        <div><span class='label'>TP2 (1:2)</span><br><b>{o['tp2']}</b></div>
                        <div><span class='label'>TP3 (1:4)</span><br><b>{o['tp3']}</b></div>
                    </div>
                    <div class='zone-footer'>
                        <small>{o['reason']}</small><br>
                        {filter_html}
                    </div>
                </div>
                """, unsafe_allow_html=True)

    st.markdown("""
    <div class='footer'>
        <small>© 2026 Alu System — XAUUSD. Konservatif: Limit di Zona | Agresif: Market Now.</small><br>
        <small>⚠️ Sinyal bukan rekomendasi investasi. Gunakan manajemen risiko.</small>
    </div>
    """, unsafe_allow_html=True)
