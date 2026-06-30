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

# ==================== DUAL-ZONE SIGNAL GENERATOR ====================
def generate_dual_signals(symbol):
    dfs = fetch_all_timeframes(symbol)
    if not dfs:
        return None, None, "Data tidak lengkap."

    daily_df = dfs.get("1d")
    if daily_df is None or not isinstance(daily_df, pd.DataFrame) or daily_df.empty or len(daily_df) < 10:
        return None, None, "Data daily tidak cukup."
    sh_d, sl_d = find_swings(daily_df, 2)
    bull_bias, bear_bias = detect_bos(daily_df, sh_d, sl_d)
    bias = "BUY" if bull_bias else ("SELL" if bear_bias else "NEUTRAL")

    zone_df = dfs.get("4h")
    if zone_df is None or not isinstance(zone_df, pd.DataFrame) or zone_df.empty:
        zone_df = dfs.get("1h")
    if zone_df is None or not isinstance(zone_df, pd.DataFrame) or zone_df.empty or len(zone_df) < 10:
        return None, None, "Data zona tidak cukup."

    sh_z, sl_z = find_swings(zone_df, 2)
    supply_zones = []
    demand_zones = []

    for idx in sh_z[-3:]:
        ob = find_ob(zone_df, "bear", idx)
        if ob:
            supply_zones.append(ob)
    for idx in sl_z[-3:]:
        ob = find_ob(zone_df, "bull", idx)
        if ob:
            demand_zones.append(ob)
    fvg = find_fvg(zone_df)
    if fvg:
        if fvg["type"] == "bearish":
            supply_zones.append({"high": fvg["top"], "low": fvg["bottom"]})
        elif fvg["type"] == "bullish":
            demand_zones.append({"high": fvg["top"], "low": fvg["bottom"]})

    entry_df = dfs.get("15m")
    if entry_df is None or not isinstance(entry_df, pd.DataFrame) or entry_df.empty:
        entry_df = dfs.get("5m")
    if entry_df is not None and not entry_df.empty:
        price = entry_df["Close"].iloc[-1]
        atr = (entry_df["High"] - entry_df["Low"]).rolling(14).mean().iloc[-1]
        if pd.isna(atr) or atr <= 0:
            atr = price * 0.002
    else:
        price = 2650
        atr = 10

    best_supply = None
    for zone in supply_zones:
        if zone["high"] > price and (zone["high"] - price) < 3 * atr:
            if best_supply is None or zone["high"] < best_supply["high"]:
                best_supply = zone
    best_demand = None
    for zone in demand_zones:
        if zone["low"] < price and (price - zone["low"]) < 3 * atr:
            if best_demand is None or zone["low"] > best_demand["low"]:
                best_demand = zone

    def calc_signal(direction, zone, price):
        if direction == "SELL":
            entry = zone["high"]
            zone_width = zone["high"] - zone["low"]
            if symbol == "XAUUSD" and zone_width > 1.0:
                zone_width = 1.0
            sl = entry + zone_width          # SL di atas entry
            tp1 = entry - zone_width        # TP1 1:1
            tp2 = entry - zone_width * 2    # TP2 1:2
            tp3 = entry - zone_width * 3    # TP3 1:3
        else:  # BUY
            entry = zone["low"]
            zone_width = zone["high"] - zone["low"]
            if symbol == "XAUUSD" and zone_width > 1.0:
                zone_width = 1.0
            sl = entry - zone_width          # SL di bawah entry
            tp1 = entry + zone_width        # TP1 1:1
            tp2 = entry + zone_width * 2    # TP2 1:2
            tp3 = entry + zone_width * 3    # TP3 1:3
        return entry, sl, tp1, tp2, tp3

    sell_signal = None
    if best_supply:
        entry, sl, tp1, tp2, tp3 = calc_signal("SELL", best_supply, price)
        sell_signal = {
            "direction": "SELL",
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "zone_high": best_supply["high"],
            "zone_low": best_supply["low"],
            "reason": f"Supply zone dari order block bearish di {best_supply['high']:.2f}-{best_supply['low']:.2f}. Konfirmasi: struktur lower high, potensi distribusi.",
            "status": "pending"
        }
    buy_signal = None
    if best_demand:
        entry, sl, tp1, tp2, tp3 = calc_signal("BUY", best_demand, price)
        buy_signal = {
            "direction": "BUY",
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "zone_high": best_demand["high"],
            "zone_low": best_demand["low"],
            "reason": f"Demand zone dari order block bullish di {best_demand['high']:.2f}-{best_demand['low']:.2f}. Konfirmasi: akumulasi, pantulan valid.",
            "status": "pending"
        }
    return sell_signal, buy_signal, bias

# ==================== SESSION STATE ====================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None
    st.session_state.nama = None
    st.session_state.pair = "XAUUSD"
    st.session_state.sell_touched = False
    st.session_state.buy_touched = False

st.set_page_config(page_title="ATS", page_icon="📊", layout="wide")
init_db()

st.markdown("""
<style>
.stApp {background:#0E1117}
.sell-card {background:linear-gradient(135deg,#4a1a1a,#28110d);border:2px solid #ff4444;border-radius:20px;padding:25px;margin:15px 0;color:#fff}
.buy-card {background:linear-gradient(135deg,#1a472a,#0d2818);border:2px solid #00ff88;border-radius:20px;padding:25px;margin:15px 0;color:#fff}
.running {border:2px dashed #ffff00 !important}
.details {background:#1a1a2e;border-radius:15px;padding:15px;margin-top:10px}
</style>
""", unsafe_allow_html=True)

# ==================== LOGIN PAGE ====================
if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("<br><br><h1 style='text-align:center;color:#00ff88;'>📊 ALU TRADING SYSTEM</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align:center;color:#888;'>Dual-Zone Limit Signal</p><br>", unsafe_allow_html=True)
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
    pair = st.selectbox("Pair", pairs, index=pairs.index(st.session_state.pair) if st.session_state.pair in pairs else 0)
    st.session_state.pair = pair

    sell_sig, buy_sig, bias = generate_dual_signals(pair)

    @st.cache_data(ttl=60)
    def get_live_price(symbol):
        ticker = SYMBOL_MAP.get(symbol, "GC=F")
        try:
            df = yf.download(ticker, period="1d", interval="1m")
            if not df.empty:
                return float(df["Close"].iloc[-1])
        except:
            pass
        return None

    live_price = get_live_price(pair)
    if live_price is not None:
        if sell_sig and not st.session_state.sell_touched and live_price >= sell_sig["entry"]:
            st.session_state.sell_touched = True
        if buy_sig and not st.session_state.buy_touched and live_price <= buy_sig["entry"]:
            st.session_state.buy_touched = True

    tv_sym = TV_SYMBOL.get(pair, "OANDA:XAUUSD")
    tv = f"""<div class="tradingview-widget-container" style="height:500px"><div id="tv"></div>
    <script src="https://s3.tradingview.com/tv.js"></script>
    <script>new TradingView.widget({{"width":"100%","height":500,"symbol":"{tv_sym}","interval":"15","timezone":"Asia/Jakarta","theme":"dark","style":"1","locale":"id","toolbar_bg":"#0E1117","enable_publishing":false,"hide_side_toolbar":false,"allow_symbol_change":false,"container_id":"tv"}});</script></div>"""
    components.html(tv, height=520)

    st.markdown("---")
    st.subheader("🎯 Sinyal Dual Limit Order (Zone Supply & Demand)")

    col1, col2 = st.columns(2)
    with col1:
        if sell_sig:
            card_class = "sell-card" + (" running" if st.session_state.sell_touched else "")
            status_text = "🔴 SELL RUNNING" if st.session_state.sell_touched else "🔴 SELL LIMIT (Pending)"
            st.markdown(f"""
            <div class='{card_class}'>
                <h3>{status_text}</h3>
                <p>ENTRY: {sell_sig['entry']:.2f}</p>
                <p>SL: {sell_sig['sl']:.2f} (di atas entry)</p>
                <p>TP1: {sell_sig['tp1']:.2f} (1:1)</p>
                <p>TP2: {sell_sig['tp2']:.2f} (1:2)</p>
                <p>TP3: {sell_sig['tp3']:.2f} (1:3)</p>
                <div class='details'><small>{sell_sig['reason']}</small></div>
            </div>""", unsafe_allow_html=True)
        else:
            st.info("Tidak ada supply zone valid di atas harga.")

    with col2:
        if buy_sig:
            card_class = "buy-card" + (" running" if st.session_state.buy_touched else "")
            status_text = "🟢 BUY RUNNING" if st.session_state.buy_touched else "🟢 BUY LIMIT (Pending)"
            st.markdown(f"""
            <div class='{card_class}'>
                <h3>{status_text}</h3>
                <p>ENTRY: {buy_sig['entry']:.2f}</p>
                <p>SL: {buy_sig['sl']:.2f} (di bawah entry)</p>
                <p>TP1: {buy_sig['tp1']:.2f} (1:1)</p>
                <p>TP2: {buy_sig['tp2']:.2f} (1:2)</p>
                <p>TP3: {buy_sig['tp3']:.2f} (1:3)</p>
                <div class='details'><small>{buy_sig['reason']}</small></div>
            </div>""", unsafe_allow_html=True)
        else:
            st.info("Tidak ada demand zone valid di bawah harga.")

    if st.session_state.sell_touched or st.session_state.buy_touched:
        st.warning("⚡ Ada sinyal yang sedang **RUNNING**. Pantau pergerakan harga.")

    if st.button("🔄 Reset Status Running"):
        st.session_state.sell_touched = False
        st.session_state.buy_touched = False
        st.rerun()

    st.markdown("---")
    st.markdown("""
    <div style='text-align:center; color:#888; padding:10px;'>
        <small>© 2026 Alu Trading System. All rights reserved.</small><br>
        <small>Disclaimer: Trading mengandung risiko. Sinyal ini bukan rekomendasi investasi. Gunakan dengan bijak.</small>
    </div>
    """, unsafe_allow_html=True)
