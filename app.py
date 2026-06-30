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

        # Tombol Clear diletakkan di sidebar dengan key unik dan konfirmasi
        if st.button("🗑️ Clear All Triggered Orders", use_container_width=True, key="clear_sidebar"):
            st.session_state.triggered_orders = []
            st.rerun()

    st.markdown("<h2 style='color:#00ff88;'>📊 ATS / Alu Trading System</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:#ccc;'>👤 {st.session_state.nama} | 📅 {datetime.now().strftime('%d %B %Y')}</p>", unsafe_allow_html=True)
    st.markdown("---")

    # Pilih Pair
    kategori = st.selectbox("Kategori", ["KOMODITAS","FOREX","CRYPTO"])
    if kategori == "KOMODITAS":
        pairs = ["XAUUSD","XAGUSD","USOIL"]
    elif kategori == "FOREX":
        pairs = ["EURUSD","GBPUSD","USDJPY","AUDUSD","NZDUSD","USDCAD","USDCHF"]
    else:
        pairs = ["BTCUSD","ETHUSD","XRPUSD","ADAUSD","SOLUSD"]
    pair = st.selectbox("Pair", pairs, index=pairs.index(st.session_state.pair) if st.session_state.pair in pairs else 0)
    if pair != st.session_state.pair:
        # Reset triggered orders saat ganti pair
        st.session_state.triggered_orders = []
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

    # === MANAGE TRIGGERED ORDERS ===
    if live_price is not None:
        to_remove = []
        for order in st.session_state.triggered_orders:
            if order["status"] != "running":
                continue
            if order["direction"] == "BUY":
                if live_price <= order["sl"] or live_price >= order["tp3"]:
                    to_remove.append(order["id"])
            else:  # SELL
                if live_price >= order["sl"] or live_price <= order["tp3"]:
                    to_remove.append(order["id"])
        st.session_state.triggered_orders = [
            o for o in st.session_state.triggered_orders if o["id"] not in to_remove
        ]

    if live_price is not None:
        if sell_sig and live_price >= sell_sig["entry"]:
            already_triggered = any(
                o["direction"] == "SELL" and o["entry"] == sell_sig["entry"] and o["status"] == "running"
                for o in st.session_state.triggered_orders
            )
            if not already_triggered:
                order = {
                    "id": f"SELL_{st.session_state.trigger_counter}",
                    "direction": "SELL",
                    "entry": sell_sig["entry"],
                    "sl": sell_sig["sl"],
                    "tp1": sell_sig["tp1"],
                    "tp2": sell_sig["tp2"],
                    "tp3": sell_sig["tp3"],
                    "tp4": sell_sig["tp4"],
                    "reason": sell_sig["reason"],
                    "status": "running",
                    "pair": pair
                }
                st.session_state.triggered_orders.append(order)
                st.session_state.trigger_counter += 1

        if buy_sig and live_price <= buy_sig["entry"]:
            already_triggered = any(
                o["direction"] == "BUY" and o["entry"] == buy_sig["entry"] and o["status"] == "running"
                for o in st.session_state.triggered_orders
            )
            if not already_triggered:
                order = {
                    "id": f"BUY_{st.session_state.trigger_counter}",
                    "direction": "BUY",
                    "entry": buy_sig["entry"],
                    "sl": buy_sig["sl"],
                    "tp1": buy_sig["tp1"],
                    "tp2": buy_sig["tp2"],
                    "tp3": buy_sig["tp3"],
                    "tp4": buy_sig["tp4"],
                    "reason": buy_sig["reason"],
                    "status": "running",
                    "pair": pair
                }
                st.session_state.triggered_orders.append(order)
                st.session_state.trigger_counter += 1

    # Chart
    tv_sym = TV_SYMBOL.get(pair, "OANDA:XAUUSD")
    tv = f"""<div class="tradingview-widget-container" style="height:500px"><div id="tv"></div>
    <script src="https://s3.tradingview.com/tv.js"></script>
    <script>new TradingView.widget({{"width":"100%","height":500,"symbol":"{tv_sym}","interval":"15","timezone":"Asia/Jakarta","theme":"dark","style":"1","locale":"id","toolbar_bg":"#0E1117","enable_publishing":false,"hide_side_toolbar":false,"allow_symbol_change":false,"container_id":"tv"}});</script></div>"""
    components.html(tv, height=520)

    st.markdown("---")

    # ========== LIMIT CARDS ==========
    st.subheader("🎯 Sinyal Limit Order (Pending)")
    col1, col2 = st.columns(2)
    with col1:
        active_sell_trigger = any(o["direction"] == "SELL" and o["status"] == "running" for o in st.session_state.triggered_orders)
        if active_sell_trigger:
            st.markdown("""<div class='sell-card'><h3>🟡 Waiting new SELL LIMIT</h3><p>Zona supply belum valid / sedang menunggu setup baru.</p></div>""", unsafe_allow_html=True)
        else:
            if sell_sig:
                st.markdown(f"""
                <div class='sell-card'>
                    <h3>🔴 SELL LIMIT (Pending)</h3>
                    <p>ENTRY: {sell_sig['entry']:.2f}</p>
                    <p>SL: {sell_sig['sl']:.2f}</p>
                    <p>TP1: {sell_sig['tp1']:.2f}</p>
                    <p>TP2: {sell_sig['tp2']:.2f}</p>
                    <p>TP3: {sell_sig['tp3']:.2f}</p>
                    <p>TP4: {sell_sig['tp4']}</p>
                    <div class='details'><small>{sell_sig['reason']}</small></div>
                </div>""", unsafe_allow_html=True)
            else:
                st.info("Tidak ada supply zone valid di atas harga.")

    with col2:
        active_buy_trigger = any(o["direction"] == "BUY" and o["status"] == "running" for o in st.session_state.triggered_orders)
        if active_buy_trigger:
            st.markdown("""<div class='buy-card'><h3>🟡 Waiting new BUY LIMIT</h3><p>Zona demand belum valid / sedang menunggu setup baru.</p></div>""", unsafe_allow_html=True)
        else:
            if buy_sig:
                st.markdown(f"""
                <div class='buy-card'>
                    <h3>🟢 BUY LIMIT (Pending)</h3>
                    <p>ENTRY: {buy_sig['entry']:.2f}</p>
                    <p>SL: {buy_sig['sl']:.2f}</p>
                    <p>TP1: {buy_sig['tp1']:.2f}</p>
                    <p>TP2: {buy_sig['tp2']:.2f}</p>
                    <p>TP3: {buy_sig['tp3']:.2f}</p>
                    <p>TP4: {buy_sig['tp4']}</p>
                    <div class='details'><small>{buy_sig['reason']}</small></div>
                </div>""", unsafe_allow_html=True)
            else:
                st.info("Tidak ada demand zone valid di bawah harga.")

    # ========== TRIGGERED ORDERS SECTION ==========
    running_orders = [o for o in st.session_state.triggered_orders if o["status"] == "running"]
    if running_orders:
        st.markdown("---")
        st.subheader("⚡ Active Triggered Orders")
        for order in running_orders:
            direction = order["direction"]
            emoji = "🔴" if direction == "SELL" else "🟢"
            tp4_str = f"<p>TP4: {order['tp4']}</p>" if order['tp4'] == "Open" else f"<p>TP4: {order['tp4']:.2f}</p>"
            st.markdown(f"""
            <div class='triggered-card'>
                <h3>{emoji} {direction} RUNNING</h3>
                <p>ENTRY: {order['entry']:.2f}</p>
                <p>SL: {order['sl']:.2f}</p>
                <p>TP1: {order['tp1']:.2f}</p>
                <p>TP2: {order['tp2']:.2f}</p>
                <p>TP3: {order['tp3']:.2f}</p>
                {tp4_str}
                <div class='details'><small>{order['reason']}</small></div>
            </div>
            """, unsafe_allow_html=True)

    # Footer
    st.markdown("---")
    st.markdown("""
    <div style='text-align:center; color:#888; padding:10px;'>
        <small>© 2026 Alu Trading System. All rights reserved.</small><br>
        <small>Disclaimer: Trading mengandung risiko. Sinyal ini bukan rekomendasi investasi. Gunakan dengan bijak.</small>
    </div>
    """, unsafe_allow_html=True)
