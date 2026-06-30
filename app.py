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

# ==================== PASSWORD HASHING ====================
def hash_password(password):
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return salt + key

def check_password(password, hashed):
    salt = hashed[:32]
    key = hashed[32:]
    new_key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return new_key == key

# ==================== DATABASE SETUP ====================
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

# ==================== SYMBOL MAPPING ====================
SYMBOL_MAP = {
    "XAUUSD": "GC=F", "XAGUSD": "SI=F", "USOIL": "CL=F",
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X", "NZDUSD": "NZDUSD=X", "USDCAD": "USDCAD=X",
    "USDCHF": "USDCHF=X", "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
    "XRPUSD": "XRP-USD", "ADAUSD": "ADA-USD", "SOLUSD": "SOL-USD"
}

TV_SYMBOL = {
    "XAUUSD": "OANDA:XAUUSD", "XAGUSD": "OANDA:XAGUSD", "USOIL": "OANDA:USOIL",
    "EURUSD": "OANDA:EURUSD", "GBPUSD": "OANDA:GBPUSD", "USDJPY": "OANDA:USDJPY",
    "AUDUSD": "OANDA:AUDUSD", "NZDUSD": "OANDA:NZDUSD", "USDCAD": "OANDA:USDCAD",
    "USDCHF": "OANDA:USDCHF", "BTCUSD": "BINANCE:BTCUSDT", "ETHUSD": "BINANCE:ETHUSDT",
    "XRPUSD": "BINANCE:XRPUSDT", "ADAUSD": "BINANCE:ADAUSDT", "SOLUSD": "BINANCE:SOLUSDT"
}

# ==================== DATA FETCHING ====================
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
    # Daily
    df = fetch_data(symbol, "1d", "3mo")
    if df is not None and not df.empty:
        result["1d"] = df
    # H4 & H1
    df = fetch_data(symbol, "1h", "1mo")
    if df is not None and not df.empty:
        df_h4 = df.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
        if not df_h4.empty:
            result["4h"] = df_h4
        result["1h"] = df
    # M15 & M5
    df = fetch_data(symbol, "15m", "60d")
    if df is not None and not df.empty:
        result["15m"] = df
    df = fetch_data(symbol, "5m", "60d")
    if df is not None and not df.empty:
        result["5m"] = df
    return result

# ==================== TECHNICAL FUNCTIONS ====================
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

def find_liquidity_sweep(df, sh, sl):
    if len(sh) < 1 or len(sl) < 1:
        return None
    last_sl = sl[-1]
    if len(df) >= 5:
        sweep_low = df['Low'].iloc[-5:].min()
        if sweep_low < df['Low'].iloc[last_sl] and df['Close'].iloc[-1] > df['Low'].iloc[last_sl]:
            return ('buy', last_sl)
    last_sh = sh[-1]
    if len(df) >= 5:
        sweep_high = df['High'].iloc[-5:].max()
        if sweep_high > df['High'].iloc[last_sh] and df['Close'].iloc[-1] < df['High'].iloc[last_sh]:
            return ('sell', last_sh)
    return None

def price_action_signal(df):
    if len(df) < 3:
        return None, None
    last = df.iloc[-1]
    prev = df.iloc[-2]
    if (prev["Close"] < prev["Open"] and last["Close"] > last["Open"] and
        last["Open"] <= prev["Close"] and last["Close"] >= prev["Open"]):
        return "BUY", "Bullish Engulfing"
    if (prev["Close"] > prev["Open"] and last["Close"] < last["Open"] and
        last["Open"] >= prev["Close"] and last["Close"] <= prev["Open"]):
        return "SELL", "Bearish Engulfing"
    body = abs(last["Close"] - last["Open"])
    lower_wick = min(last["Close"], last["Open"]) - last["Low"]
    upper_wick = last["High"] - max(last["Close"], last["Open"])
    if lower_wick > body * 2 and upper_wick < body * 0.5:
        return "BUY", "Hammer"
    if upper_wick > body * 2 and lower_wick < body * 0.5:
        return "SELL", "Shooting Star"
    if last["High"] <= prev["High"] and last["Low"] >= prev["Low"]:
        if prev["Close"] > prev["Open"]:
            return "BUY", "Inside Bar (Bullish Cont.)"
        else:
            return "SELL", "Inside Bar (Bearish Cont.)"
    return None, None

# ==================== ANALISIS GABUNGAN ====================
def full_ict_analysis(symbol):
    dfs = fetch_all_timeframes(symbol)
    if not dfs:
        return None, "Gagal mengambil data. Periksa koneksi atau coba pair lain."
    
    # Bias
    bias_df = dfs.get("1d")
    if bias_df is None or (isinstance(bias_df, pd.DataFrame) and bias_df.empty):
        bias_df = dfs.get("4h")
    if bias_df is None or (isinstance(bias_df, pd.DataFrame) and bias_df.empty):
        return None, "Data timeframe tinggi tidak tersedia."
    if len(bias_df) < 10:
        return None, "Data timeframe tinggi tidak cukup."
    
    sh_b, sl_b = find_swings(bias_df, 2)
    bull, bear = detect_bos(bias_df, sh_b, sl_b)
    if bull and not bear:
        bias = "BUY"
    elif bear and not bull:
        bias = "SELL"
    else:
        if len(bias_df) >= 20:
            sma20 = bias_df["Close"].rolling(20).mean().iloc[-1]
            bias = "BUY" if bias_df["Close"].iloc[-1] > sma20 else "SELL"
        else:
            bias = "BUY" if bias_df["Close"].iloc[-1] > bias_df["Close"].iloc[0] else "SELL"
    
    # Zona
    zone_df = dfs.get("4h")
    if zone_df is None or (isinstance(zone_df, pd.DataFrame) and zone_df.empty):
        zone_df = dfs.get("1h")
    if zone_df is None or (isinstance(zone_df, pd.DataFrame) and zone_df.empty):
        zone_df = bias_df
    
    sh_z, sl_z = find_swings(zone_df, 2)
    zones = []
    if sl_z:
        ob = find_ob(zone_df, "bull", sl_z[-1])
        if ob:
            zones.append({"type": "demand", "high": ob["high"], "low": ob["low"]})
    if sh_z:
        ob = find_ob(zone_df, "bear", sh_z[-1])
        if ob:
            zones.append({"type": "supply", "high": ob["high"], "low": ob["low"]})
    fvg_z = find_fvg(zone_df)
    if fvg_z:
        if fvg_z["type"] == "bullish":
            zones.append({"type": "demand_fvg", "high": fvg_z["top"], "low": fvg_z["bottom"]})
        else:
            zones.append({"type": "supply_fvg", "high": fvg_z["top"], "low": fvg_z["bottom"]})
    
    # Entry
    entry_df = dfs.get("15m")
    if entry_df is None or (isinstance(entry_df, pd.DataFrame) and entry_df.empty):
        entry_df = dfs.get("5m")
    if entry_df is None or (isinstance(entry_df, pd.DataFrame) and entry_df.empty):
        entry_df = dfs.get("1h")
    if entry_df is None or (isinstance(entry_df, pd.DataFrame) and entry_df.empty):
        return None, "Data timeframe rendah tidak tersedia."
    
    sh_e, sl_e = find_swings(entry_df, 1)
    sweep = find_liquidity_sweep(entry_df, sh_e, sl_e)
    pa_sig, pa_desc = price_action_signal(entry_df)
    
    price = entry_df["Close"].iloc[-1]
    signal = None
    reasons = []
    entry_price = sl_price = None
    is_pending = False
    
    def near_zone(price, zone, threshold=0.015):
        return abs(price - zone["low"]) / price < threshold or abs(price - zone["high"]) / price < threshold
    
    valid_zones = [z for z in zones if (bias == "BUY" and "demand" in z["type"]) or (bias == "SELL" and "supply" in z["type"])]
    
    if bias == "BUY":
        if sweep and sweep[0] == 'buy':
            entry_price = price
            sl_price = entry_df["Low"].iloc[sweep[1]] - 0.01
            reasons = ["✅ Bias Higher TF: Bullish", "✅ Liquidity Sweep buy"]
            signal = "BUY"
        elif valid_zones and pa_sig == "BUY":
            for zone in valid_zones:
                if near_zone(price, zone):
                    entry_price = zone["high"] + 0.01
                    sl_price = zone["low"] - 0.01
                    reasons = [f"✅ Bias Bullish", f"✅ {pa_desc} di Demand Zone"]
                    signal = "BUY"
                    break
        if not signal and valid_zones:
            for zone in valid_zones:
                if zone["type"] == "demand" and price > zone["low"]:
                    entry_price = zone["high"] + 0.01
                    sl_price = zone["low"] - 0.01
                    reasons = [f"📌 Bias Bullish", "📌 PULLBACK ke Demand Zone", "📌 Pending Buy Limit"]
                    signal = "BUY"
                    is_pending = True
                    break
                elif zone["type"] == "demand_fvg" and price > zone["low"]:
                    entry_price = zone["high"]
                    sl_price = zone["bottom"]
                    reasons = [f"📌 Bias Bullish", "📌 PULLBACK ke Demand FVG", "📌 Pending Buy Limit"]
                    signal = "BUY"
                    is_pending = True
                    break
        if not signal:
            entry_price = price
            sl_price = min(entry_df["Low"].iloc[-5:]) - 0.5
            reasons = ["⚠️ Bias Bullish", "⚠️ Entry agresif (no setup)", "⚠️ Pantau terus"]
            signal = "BUY"
    else:
        if sweep and sweep[0] == 'sell':
            entry_price = price
            sl_price = entry_df["High"].iloc[sweep[1]] + 0.01
            reasons = ["✅ Bias Higher TF: Bearish", "✅ Liquidity Sweep sell"]
            signal = "SELL"
        elif valid_zones and pa_sig == "SELL":
            for zone in valid_zones:
                if near_zone(price, zone):
                    entry_price = zone["low"] - 0.01
                    sl_price = zone["high"] + 0.01
                    reasons = [f"✅ Bias Bearish", f"✅ {pa_desc} di Supply Zone"]
                    signal = "SELL"
                    break
        if not signal and valid_zones:
            for zone in valid_zones:
                if zone["type"] == "supply" and price < zone["high"]:
                    entry_price = zone["low"] - 0.01
                    sl_price = zone["high"] + 0.01
                    reasons = [f"📌 Bias Bearish", "📌 PULLBACK ke Supply Zone", "📌 Pending Sell Limit"]
                    signal = "SELL"
                    is_pending = True
                    break
                elif zone["type"] == "supply_fvg" and price < zone["top"]:
                    entry_price = zone["low"]
                    sl_price = zone["top"]
                    reasons = [f"📌 Bias Bearish", "📌 PULLBACK ke Supply FVG", "📌 Pending Sell Limit"]
                    signal = "SELL"
                    is_pending = True
                    break
        if not signal:
            entry_price = price
            sl_price = max(entry_df["High"].iloc[-5:]) + 0.5
            reasons = ["⚠️ Bias Bearish", "⚠️ Entry agresif (no setup)", "⚠️ Pantau terus"]
            signal = "SELL"
    
    if not signal:
        return None, "Tidak ada setup valid."
    
    risk = abs(entry_price - sl_price)
    tp1 = entry_price + risk * 1.5 if signal == "BUY" else entry_price - risk * 1.5
    tp2 = entry_price + risk * 3   if signal == "BUY" else entry_price - risk * 3
    tp3 = entry_price + risk * 5   if signal == "BUY" else entry_price - risk * 5
    
    return {
        "signal": signal,
        "entry": entry_price,
        "sl": sl_price,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "reasons": reasons,
        "price": price,
        "is_pending": is_pending
    }, None

# ==================== SESSION STATE ====================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None
    st.session_state.nama = None
    st.session_state.page = "analisa"
    st.session_state.result = None

st.set_page_config(page_title="ATS", page_icon="📊", layout="wide")
init_db()

st.markdown("""
<style>
.stApp {background:#0E1117}
.signal-buy {background:linear-gradient(135deg,#1a472a,#0d2818);border:2px solid #00ff88;border-radius:20px;padding:30px;text-align:center;margin:20px 0}
.signal-sell {background:linear-gradient(135deg,#4a1a1a,#28110d);border:2px solid #ff4444}
.pending {border:2px dashed #ffaa00 !important}
.signal-buy h1 {color:#00ff88;font-size:48px}
.signal-sell h1 {color:#ff4444}
.details {background:#1a1a2e;border-radius:15px;padding:20px;margin:15px 0;text-align:left}
.details p {font-size:18px;color:#e0e0e0}
.stButton>button {border-radius:12px;font-weight:bold;padding:12px 24px}
</style>
""", unsafe_allow_html=True)

# ==================== LOGIN PAGE ====================
if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("<br><br><h1 style='text-align:center;color:#00ff88;'>📊 ALU TRADING SYSTEM</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align:center;color:#888;'>SMC/ICT Multi-Timeframe</p><br>", unsafe_allow_html=True)
        role = st.radio("Login sebagai:", ["User", "Admin"], horizontal=True)
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("🔓 MASUK", use_container_width=True):
            if role == "Admin":
                if verify_admin(u, p):
                    st.session_state.logged_in = True
                    st.session_state.role = "admin"
                    st.rerun()
                else:
                    st.error("❌ Username/password admin salah")
            else:
                nama, err = verify_user(u, p)
                if nama:
                    st.session_state.logged_in = True
                    st.session_state.role = "user"
                    st.session_state.nama = nama
                    st.rerun()
                else:
                    st.error(f"❌ {err}")

# ==================== ADMIN PANEL ====================
elif st.session_state.role == "admin":
    st.sidebar.markdown("<h2 style='color:#00ff88;'>👑 ADMIN</h2>", unsafe_allow_html=True)
    if st.sidebar.button("🚪 LOGOUT"):
        st.session_state.logged_in = False
        st.rerun()
    st.title("👑 Admin Panel - Alu Trading System")
    tabs = st.tabs(["➕ Generate Kode", "🎁 Trial 2 Hari", "📋 Daftar User", "⚙️ Ganti Password"])
    
    with tabs[0]:
        st.subheader("Generate Kode Berbayar")
        c1, c2 = st.columns(2)
        nama = c1.text_input("Nama")
        email = c2.text_input("Email")
        masa = st.selectbox("Masa Aktif", [2,7,30,90,180,365], format_func=lambda x: f"{x} Hari")
        if st.button("🔑 GENERATE", use_container_width=True):
            if nama and email:
                user, pw, exp = generate_user(nama, email, masa)
                st.success("✅ Berhasil!")
                st.code(f"Username: {user}\nPassword: {pw}\nExpired: {exp}")
            else:
                st.error("Isi nama & email")
    
    with tabs[1]:
        st.subheader("Trial 2 Hari")
        c1, c2 = st.columns(2)
        nama = c1.text_input("Nama", key="tn")
        email = c2.text_input("Email", key="te")
        if st.button("🎁 GENERATE TRIAL", use_container_width=True):
            if nama and email:
                user, pw, exp = generate_user(nama, email, 2, is_trial=1)
                st.success("✅ Trial dibuat!")
                st.code(f"Username: {user}\nPassword: {pw}\nExpired: {exp}")
            else:
                st.error("Isi nama & email")
    
    with tabs[2]:
        st.subheader("Daftar User")
        for u in get_users():
            uid, nama, email, uname, exp, status, trial = u
            label = "🎁 TRIAL" if trial else "💰 BAYAR"
            emoji = "🟢" if status=="aktif" else "🔴"
            with st.expander(f"{emoji} [{label}] {nama} - {uname}"):
                st.write(f"Email: {email}\nExpired: {exp}")
                c1, c2 = st.columns(2)
                d = c1.number_input("Hari",1,365,30,key=f"ex{uid}")
                if c1.button("Perpanjang", key=f"eb{uid}"):
                    extend_user(uid, d)
                    st.rerun()
                if c2.button("Hapus", key=f"db{uid}"):
                    delete_user(uid)
                    st.rerun()
    
    with tabs[3]:
        st.subheader("Ganti Password Admin")
        old_pw = st.text_input("Password Lama", type="password")
        new_pw = st.text_input("Password Baru", type="password")
        if st.button("💾 Simpan Password Baru"):
            if change_admin_password(old_pw, new_pw):
                st.success("✅ Password admin berhasil diubah!")
            else:
                st.error("❌ Password lama salah")

# ==================== USER DASHBOARD ====================
else:
    with st.sidebar:
        st.markdown(f"<h3 style='color:#00ff88;'>👤 {st.session_state.nama}</h3>", unsafe_allow_html=True)
        components.html("""
        <div id="live-clock" style="color:#cccccc; font-size:16px; margin-bottom:10px;"></div>
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
        updateClock();
        setInterval(updateClock, 1000);
        </script>
        """, height=60)
        
        st.markdown(f"<p style='color:#888;'>{datetime.now().strftime('%A, %d %B %Y')}</p>", unsafe_allow_html=True)
        if st.button("📊 ANALISA", use_container_width=True):
            st.session_state.page = "analisa"
            st.rerun()
        if st.button("🎯 SINYAL", use_container_width=True):
            st.session_state.page = "sinyal"
            st.rerun()
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT expired_date, is_trial FROM users WHERE nama=?", (st.session_state.nama,))
        row = c.fetchone()
        conn.close()
        if row:
            exp = datetime.strptime(row[0], "%Y-%m-%d")
            sisa = (exp - datetime.now()).days
            st.info(f"⏳ {sisa} hari tersisa" if not row[1] else f"🎁 Trial {sisa} hari")
        if st.button("🚪 LOGOUT", use_container_width=True):
            st.session_state.logged_in = False
            st.rerun()

    st.markdown("<h2 style='color:#00ff88;'>📊 ATS / Alu Trading System</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:#ccc;'>👤 {st.session_state.nama} | 📅 {datetime.now().strftime('%d %B %Y')}</p>", unsafe_allow_html=True)
    st.markdown("---")
    
    kategori = st.selectbox("Kategori", ["KOMODITAS","FOREX","CRYPTO"])
    if kategori == "KOMODITAS":
        pairs = ["XAUUSD","XAGUSD","USOIL"]
    elif kategori == "FOREX":
        pairs = ["EURUSD","GBPUSD","USDJPY","AUDUSD","NZDUSD","USDCAD","USDCHF"]
    else:
        pairs = ["BTCUSD","ETHUSD","XRPUSD","ADAUSD","SOLUSD"]
    pair = st.selectbox("Pair", pairs)

    if st.session_state.page == "analisa":
        tv_sym = TV_SYMBOL.get(pair, "OANDA:XAUUSD")
        tv = f"""<div class="tradingview-widget-container" style="height:500px"><div id="tv"></div>
        <script src="https://s3.tradingview.com/tv.js"></script>
        <script>new TradingView.widget({{"width":"100%","height":500,"symbol":"{tv_sym}","interval":"15","timezone":"Asia/Jakarta","theme":"dark","style":"1","locale":"id","toolbar_bg":"#0E1117","enable_publishing":false,"hide_side_toolbar":false,"allow_symbol_change":false,"studies":["RSI@tv-basicstudies","MACD@tv-basicstudies"],"container_id":"tv"}});</script></div>"""
        components.html(tv, height=520)
        
        st.markdown("---")
        if st.button("🔍 ANALISA SEKARANG", use_container_width=True):
            with st.spinner("Menganalisa semua timeframe..."):
                res, err = full_ict_analysis(pair)
            if err:
                st.error(err)
            else:
                st.session_state.result = res
                st.session_state.page = "sinyal"
                st.rerun()

    else:
        if st.button("⬅️ Kembali ke Chart"):
            st.session_state.page = "analisa"
            st.rerun()
        res = st.session_state.result
        if res:
            sig = res["signal"]
            is_pending = res.get("is_pending", False)
            cls = "signal-buy" if sig=="BUY" else "signal-sell"
            if is_pending:
                cls += " pending"
            emj = "🟢" if sig=="BUY" else "🔴"
            title = "📌 PENDING LIMIT ORDER" if is_pending else "📈 SINYAL ICT MULTI-TF"
            st.markdown(f"<div class='{cls}'><p>{title}</p><h1>{emj} {sig}</h1><p style='color:#fff'>{pair}</p></div>", unsafe_allow_html=True)
            
            st.markdown(f"<div class='details'><p>📍 ENTRY : {res['entry']:.2f}</p><p>🛑 SL : {res['sl']:.2f}</p>"
                        f"<p>🎯 TP1 (Scalping) : {res['tp1']:.2f}</p><p>🎯 TP2 (Intraday) : {res['tp2']:.2f}</p>"
                        f"<p>🎯 TP3 (Swing) : {res['tp3']:.2f}</p></div>", unsafe_allow_html=True)
            
            st.markdown("### 📝 Alasan Entry")
            st.markdown(f"<div style='background:#1a1a2e;border-radius:15px;padding:20px;color:#ccc'><ul>{''.join(f'<li>{r}</li>' for r in res['reasons'])}</ul></div>", unsafe_allow_html=True)
        else:
            st.info("Klik ANALISA SEKARANG di halaman Chart")
        
    st.markdown("---")
    st.markdown("""
    <div style='text-align:center; color:#888; padding:10px;'>
        <small>© 2026 Alu Trading System. All rights reserved.</small><br>
        <small>Disclaimer: Trading mengandung risiko. Sinyal ini bukan rekomendasi investasi. Gunakan dengan bijak.</small>
    </div>
    """, unsafe_allow_html=True)
