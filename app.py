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
        if symbol == "XAUUSD":
            distance = 10.0
            tp2_dist = 15.0
            tp3_dist = 20.0
            if direction == "SELL":
                entry = zone["high"]
                sl = entry + distance
                tp1 = entry - distance
                tp2 = entry - tp2_dist
                tp3 = entry - tp3_dist
                tp4 = "Open"
            else:
                entry = zone["low"]
                sl = entry - distance
                tp1 = entry + distance
                tp2 = entry + tp2_dist
                tp3 = entry + tp3_dist
                tp4 = "Open"
        else:
            zone_width = zone["high"] - zone["low"]
            if direction == "SELL":
                entry = zone["high"]
                sl = entry + zone_width
                tp1 = entry - zone_width
                tp2 = entry - zone_width * 2
                tp3 = entry - zone_width * 3
                tp4 = "Open"
            else:
                entry = zone["low"]
                sl = entry - zone_width
                tp1 = entry + zone_width
                tp2 = entry + zone_width * 2
                tp3 = entry + zone_width * 3
                tp4 = "Open"
        return entry, sl, tp1, tp2, tp3, tp4

    sell_signal = None
    if best_supply:
        entry, sl, tp1, tp2, tp3, tp4 = calc_signal("SELL", best_supply, price)
        sell_signal = {
            "direction": "SELL",
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "tp4": tp4,
            "zone_high": best_supply["high"],
            "zone_low": best_supply["low"],
            "reason": f"Supply zone dari order block bearish di {best_supply['high']:.2f}-{best_supply['low']:.2f}. Konfirmasi: struktur lower high, potensi distribusi.",
            "status": "pending"
        }
    buy_signal = None
    if best_demand:
        entry, sl, tp1, tp2, tp3, tp4 = calc_signal("BUY", best_demand, price)
        buy_signal = {
            "direction": "BUY",
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "tp4": tp4,
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
    st.session_state.triggered_orders = []
    st.session_state.trigger_counter = 0

st.set_page_config(page_title="ATS - Alu Trading System", page_icon="📊", layout="wide")
init_db()

# ==================== GLOBAL CSS PREMIUM ====================
st.markdown("""
<style>
    .stApp { background: #0E1117; }
    .main-header { text-align: center; padding: 10px 0; border-bottom: 1px solid #2a2a3a; margin-bottom: 20px; }
    .main-header h1 { color: #00ff88; font-size: 2.2rem; margin: 0; letter-spacing: 2px; }
    .main-header p { color: #888; margin: 5px 0 0 0; }
    
    .glass-card {
        background: rgba(20, 25, 40, 0.8);
        backdrop-filter: blur(5px);
        border: 1px solid #2a3240;
        border-radius: 20px;
        padding: 20px;
        margin: 10px 0;
        transition: 0.3s;
    }
    .glass-card:hover { border-color: #00ff88; box-shadow: 0 0 20px rgba(0,255,136,0.05); }
    
    .sell-card { background: linear-gradient(145deg, #2a0f0f, #1a0808); border: 2px solid #ff4444; border-radius: 20px; padding: 25px; margin: 15px 0; color: #fff; box-shadow: 0 4px 15px rgba(255,68,68,0.2); }
    .buy-card { background: linear-gradient(145deg, #0f2a1a, #08180d); border: 2px solid #00ff88; border-radius: 20px; padding: 25px; margin: 15px 0; color: #fff; box-shadow: 0 4px 15px rgba(0,255,136,0.2); }
    
    .running-card { background: #1a1a2e; border: 2px solid #ffaa00; border-radius: 20px; padding: 20px; margin: 10px 0; color: #fff; box-shadow: 0 0 20px rgba(255,170,0,0.1); }
    
    .order-details { background: #0E1117; border-radius: 12px; padding: 12px; margin-top: 10px; border-left: 3px solid #00ff88; font-size: 0.9rem; color: #aaa; }
    .order-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; margin: 10px 0; }
    .order-item { background: #0E1117; padding: 8px 12px; border-radius: 8px; text-align: center; border: 1px solid #2a3240; }
    .order-item .label { font-size: 0.7rem; color: #888; text-transform: uppercase; }
    .order-item .value { font-weight: bold; font-family: monospace; font-size: 1.1rem; }

    .bias-badge { display: inline-block; padding: 5px 15px; border-radius: 20px; font-weight: bold; background: #2a3240; color: #ccc; }
    .bias-buy { background: #00ff8822; border: 1px solid #00ff88; color: #00ff88; }
    .bias-sell { background: #ff444422; border: 1px solid #ff4444; color: #ff4444; }
    .bias-neutral { background: #ffaa0022; border: 1px solid #ffaa00; color: #ffaa00; }
    
    .price-ticker { font-size: 2rem; font-weight: bold; font-family: monospace; }
    .green { color: #00ff88; }
    .red { color: #ff4444; }
    
    .footer { text-align: center; color: #555; padding: 20px 0; font-size: 0.8rem; border-top: 1px solid #1a1a2a; margin-top: 30px; }
</style>
""", unsafe_allow_html=True)

# ==================== LOGIN PAGE ====================
if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("<br><br><h1 style='text-align:center;color:#00ff88;'>📊 ALU TRADING SYSTEM</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align:center;color:#888;'>Dual-Zone Limit Signal Framework</p><br>", unsafe_allow_html=True)
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

# ==================== ADMIN PANEL (TIDAK DIUBAH) ====================
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

# ==================== USER DASHBOARD (DIPERBAIKI TAMPILAN) ====================
else:
    # --- SIDEBAR ---
    with st.sidebar:
        st.markdown(f"<h3 style='color:#00ff88; margin-bottom:0;'>👤 {st.session_state.nama}</h3>", unsafe_allow_html=True)
        
        # Jam Live
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
        updateClock();
        setInterval(updateClock, 1000);
        </script>
        """, height=65)
        
        # Sisa Masa Aktif
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT expired_date, is_trial FROM users WHERE nama=?", (st.session_state.nama,))
        row = c.fetchone()
        conn.close()
        if row:
            exp = datetime.strptime(row[0], "%Y-%m-%d")
            sisa = (exp - datetime.now()).days
            if sisa < 0: sisa = 0
            status_text = f"🎁 Trial {sisa} hari" if row[1] else f"⏳ {sisa} hari tersisa"
            st.info(status_text)
        
        st.markdown("---")
        st.markdown("### ⚙️ Kontrol")
        if st.button("🚪 LOGOUT", use_container_width=True):
            st.session_state.logged_in = False
            st.rerun()
        if st.button("🗑️ Clear Orders", use_container_width=True, key="clear_sidebar"):
            st.session_state.triggered_orders = []
            st.rerun()

    # --- HEADER UTAMA ---
    col_head1, col_head2 = st.columns([3,1])
    with col_head1:
        st.markdown("<h1 style='color:#00ff88; margin-bottom:0;'>📊 ATS Dashboard</h1>", unsafe_allow_html=True)
        st.markdown(f"<p style='color:#888; margin-top:0;'>👤 {st.session_state.nama} | 📅 {datetime.now().strftime('%d %B %Y')}</p>", unsafe_allow_html=True)
    with col_head2:
        # Live Price Ticker
        ticker = SYMBOL_MAP.get(st.session_state.pair, "GC=F")
        try:
            df_live = yf.download(ticker, period="1d", interval="1m")
            if not df_live.empty:
                live_p = float(df_live["Close"].iloc[-1])
                st.metric(label="💵 Harga Spot", value=f"{live_p:.2f}", delta=None)
        except:
            pass

    # --- PAIR SELECTOR ---
    kategori = st.selectbox("Kategori", ["KOMODITAS","FOREX","CRYPTO"])
    if kategori == "KOMODITAS":
        pairs = ["XAUUSD","XAGUSD","USOIL"]
    elif kategori == "FOREX":
        pairs = ["EURUSD","GBPUSD","USDJPY","AUDUSD","NZDUSD","USDCAD","USDCHF"]
    else:
        pairs = ["BTCUSD","ETHUSD","XRPUSD","ADAUSD","SOLUSD"]
    
    current_pair = st.session_state.pair
    if current_pair in pairs:
        idx = pairs.index(current_pair)
    else:
        idx = 0
    pair = st.selectbox("Pair", pairs, index=idx)
    if pair != st.session_state.pair:
        st.session_state.triggered_orders = []
        st.session_state.pair = pair

    # --- TRADINGVIEW CHART (WAJIB DIPERTAHANKAN) ---
    tv_sym = TV_SYMBOL.get(pair, "OANDA:XAUUSD")
    tv_html = f"""
    <div class="tradingview-widget-container" style="height:500px; margin-top:10px; border-radius:15px; overflow:hidden; border:1px solid #2a3240;">
        <div id="tv_chart"></div>
        <script src="https://s3.tradingview.com/tv.js"></script>
        <script>
        new TradingView.widget({{
            "width":"100%",
            "height":500,
            "symbol":"{tv_sym}",
            "interval":"15",
            "timezone":"Asia/Jakarta",
            "theme":"dark",
            "style":"1",
            "locale":"id",
            "toolbar_bg":"#0E1117",
            "enable_publishing":false,
            "hide_side_toolbar":false,
            "allow_symbol_change":false,
            "container_id":"tv_chart"
        }});
        </script>
    </div>
    """
    components.html(tv_html, height=520)

    # --- GENERATE SIGNAL & BIAS ---
    sell_sig, buy_sig, bias = generate_dual_signals(pair)
    
    # Tampilkan Bias
    bias_color = "bias-neutral"
    if bias == "BUY": bias_color = "bias-buy"
    elif bias == "SELL": bias_color = "bias-sell"
    st.markdown(f"<div style='display:flex; justify-content:center; gap:20px; margin:10px 0;'><span>📈 Daily Bias:</span> <span class='bias-badge {bias_color}'>{bias}</span></div>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 🎯 Sinyal Limit Order (Pending)")

    # --- LOGIKA TRIGGER OTOMATIS ---
    live_price = None
    try:
        df_live = yf.download(SYMBOL_MAP.get(pair, "GC=F"), period="1d", interval="1m")
        if not df_live.empty:
            live_price = float(df_live["Close"].iloc[-1])
    except:
        pass

    if live_price is not None:
        to_remove = []
        for order in st.session_state.triggered_orders:
            if order["status"] != "running":
                continue
            if order["direction"] == "BUY":
                if live_price <= order["sl"] or live_price >= order["tp3"]:
                    to_remove.append(order["id"])
            else:
                if live_price >= order["sl"] or live_price <= order["tp3"]:
                    to_remove.append(order["id"])
        st.session_state.triggered_orders = [o for o in st.session_state.triggered_orders if o["id"] not in to_remove]

    # Trigger baru
    if live_price is not None:
        if sell_sig and live_price >= sell_sig["entry"]:
            already = any(o["direction"] == "SELL" and o["entry"] == sell_sig["entry"] and o["status"] == "running" for o in st.session_state.triggered_orders)
            if not already:
                st.session_state.triggered_orders.append({
                    "id": f"SELL_{st.session_state.trigger_counter}",
                    "direction": "SELL", "entry": sell_sig["entry"], "sl": sell_sig["sl"],
                    "tp1": sell_sig["tp1"], "tp2": sell_sig["tp2"], "tp3": sell_sig["tp3"],
                    "tp4": sell_sig["tp4"], "reason": sell_sig["reason"], "status": "running", "pair": pair
                })
                st.session_state.trigger_counter += 1

        if buy_sig and live_price <= buy_sig["entry"]:
            already = any(o["direction"] == "BUY" and o["entry"] == buy_sig["entry"] and o["status"] == "running" for o in st.session_state.triggered_orders)
            if not already:
                st.session_state.triggered_orders.append({
                    "id": f"BUY_{st.session_state.trigger_counter}",
                    "direction": "BUY", "entry": buy_sig["entry"], "sl": buy_sig["sl"],
                    "tp1": buy_sig["tp1"], "tp2": buy_sig["tp2"], "tp3": buy_sig["tp3"],
                    "tp4": buy_sig["tp4"], "reason": buy_sig["reason"], "status": "running", "pair": pair
                })
                st.session_state.trigger_counter += 1

    # --- TAMPILAN DUAL ZONE ---
    col1, col2 = st.columns(2)

    with col1:
        active_sell = any(o["direction"] == "SELL" and o["status"] == "running" for o in st.session_state.triggered_orders)
        if active_sell:
            st.markdown("""<div class='sell-card'><h3 style='margin-top:0;'>⏳ MENUNGGU SELL</h3><p style='color:#ff8888;'>Zona supply sudah terisi atau sedang menunggu setup baru.</p><small style='color:#888;'>Harga menyentuh zona, order aktif di bawah.</small></div>""", unsafe_allow_html=True)
        else:
            if sell_sig:
                st.markdown(f"""
                <div class='sell-card'>
                    <h3 style='margin-top:0;'>🔴 SELL LIMIT (Pending)</h3>
                    <div class='order-grid'>
                        <div class='order-item'><div class='label'>Entry</div><div class='value' style='color:#ff6666;'>{sell_sig['entry']:.2f}</div></div>
                        <div class='order-item'><div class='label'>Stop Loss</div><div class='value' style='color:#ff4444;'>{sell_sig['sl']:.2f}</div></div>
                    </div>
                    <div class='order-grid'>
                        <div class='order-item'><div class='label'>TP 1 (1:1)</div><div class='value'>{sell_sig['tp1']:.2f}</div></div>
                        <div class='order-item'><div class='label'>TP 2 (1:1.5)</div><div class='value'>{sell_sig['tp2']:.2f}</div></div>
                        <div class='order-item'><div class='label'>TP 3 (1:2)</div><div class='value'>{sell_sig['tp3']:.2f}</div></div>
                    </div>
                    <div class='order-details'><small>📍 Zona: {sell_sig['zone_high']:.2f} - {sell_sig['zone_low']:.2f} | {sell_sig['reason']}</small></div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.info("📭 Tidak ada supply zone valid di atas harga.")

    with col2:
        active_buy = any(o["direction"] == "BUY" and o["status"] == "running" for o in st.session_state.triggered_orders)
        if active_buy:
            st.markdown("""<div class='buy-card'><h3 style='margin-top:0;'>⏳ MENUNGGU BUY</h3><p style='color:#88ffaa;'>Zona demand sudah terisi atau sedang menunggu setup baru.</p><small style='color:#888;'>Harga menyentuh zona, order aktif di bawah.</small></div>""", unsafe_allow_html=True)
        else:
            if buy_sig:
                st.markdown(f"""
                <div class='buy-card'>
                    <h3 style='margin-top:0;'>🟢 BUY LIMIT (Pending)</h3>
                    <div class='order-grid'>
                        <div class='order-item'><div class='label'>Entry</div><div class='value' style='color:#66ff88;'>{buy_sig['entry']:.2f}</div></div>
                        <div class='order-item'><div class='label'>Stop Loss</div><div class='value' style='color:#ff4444;'>{buy_sig['sl']:.2f}</div></div>
                    </div>
                    <div class='order-grid'>
                        <div class='order-item'><div class='label'>TP 1 (1:1)</div><div class='value'>{buy_sig['tp1']:.2f}</div></div>
                        <div class='order-item'><div class='label'>TP 2 (1:1.5)</div><div class='value'>{buy_sig['tp2']:.2f}</div></div>
                        <div class='order-item'><div class='label'>TP 3 (1:2)</div><div class='value'>{buy_sig['tp3']:.2f}</div></div>
                    </div>
                    <div class='order-details'><small>📍 Zona: {buy_sig['zone_high']:.2f} - {buy_sig['zone_low']:.2f} | {buy_sig['reason']}</small></div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.info("📭 Tidak ada demand zone valid di bawah harga.")

    # --- ACTIVE TRIGGERED ORDERS ---
    running_orders = [o for o in st.session_state.triggered_orders if o["status"] == "running"]
    if running_orders:
        st.markdown("---")
        st.markdown("### ⚡ Running Orders (Aktif)")
        for order in running_orders:
            emoji = "🔴" if order["direction"] == "SELL" else "🟢"
            border_color = "#ff4444" if order["direction"] == "SELL" else "#00ff88"
            st.markdown(f"""
            <div class='running-card' style='border-color:{border_color};'>
                <div style='display:flex; justify-content:space-between; align-items:center;'>
                    <h3 style='margin:0;'>{emoji} {order['direction']} RUNNING</h3>
                    <span style='color:#ffaa00; font-size:0.8rem;'>Entry tersentuh!</span>
                </div>
                <div class='order-grid'>
                    <div class='order-item'><div class='label'>Entry</div><div class='value'>{order['entry']:.2f}</div></div>
                    <div class='order-item'><div class='label'>SL</div><div class='value' style='color:#ff4444;'>{order['sl']:.2f}</div></div>
                    <div class='order-item'><div class='label'>TP1</div><div class='value'>{order['tp1']:.2f}</div></div>
                    <div class='order-item'><div class='label'>TP2</div><div class='value'>{order['tp2']:.2f}</div></div>
                    <div class='order-item'><div class='label'>TP3</div><div class='value'>{order['tp3']:.2f}</div></div>
                    <div class='order-item'><div class='label'>TP4</div><div class='value'>{order['tp4']}</div></div>
                </div>
                <div class='order-details'><small>{order['reason']}</small></div>
            </div>
            """, unsafe_allow_html=True)

    # --- FOOTER ---
    st.markdown("""
    <div class='footer'>
        <small>© 2026 Alu Trading System. All rights reserved.</small><br>
        <small>⚠️ Disclaimer: Trading mengandung risiko. Sinyal ini bukan rekomendasi investasi. Gunakan dengan bijak.</small>
    </div>
    """, unsafe_allow_html=True)
