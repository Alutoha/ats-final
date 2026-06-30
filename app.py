from flask import Flask, request, render_template_string

app = Flask(__name__)

# ============ HTML TEMPLATE ============
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Trading Signal Dashboard - TP2 Otomatis</title>
    <style>
        body { font-family: Arial, sans-serif; background: #1e1e2f; color: #eee; padding: 30px; }
        .container { max-width: 1000px; margin: 0 auto; background: #2a2a3e; padding: 30px; border-radius: 16px; box-shadow: 0 0 20px rgba(0,0,0,0.5); }
        h1 { text-align: center; color: #f0c040; }
        .row { display: flex; flex-wrap: wrap; gap: 15px; }
        .col { flex: 1; min-width: 200px; }
        label { display: block; font-weight: bold; margin-top: 12px; color: #aab; }
        input, select { width: 100%; padding: 10px; border-radius: 8px; border: none; background: #3a3a52; color: #fff; }
        button { background: #f0c040; color: #1e1e2f; font-weight: bold; padding: 14px 30px; border: none; border-radius: 10px; margin-top: 25px; cursor: pointer; width: 100%; font-size: 18px; }
        button:hover { background: #f5d060; }
        .result { margin-top: 30px; background: #22223a; padding: 20px; border-radius: 12px; border-left: 6px solid #f0c040; white-space: pre-wrap; font-family: 'Courier New', monospace; font-size: 14px; line-height: 1.6; }
        .badge { color: #f0c040; font-weight: bold; }
        .note { color: #888; font-size: 13px; margin-top: 5px; }
        hr { border-color: #444; }
        .info-box { background: #1a1a2e; padding: 10px 15px; border-radius: 8px; border-left: 4px solid #f0c040; margin-top: 10px; color: #ccc; }
    </style>
</head>
<body>
<div class="container">
    <h1>📊 Analisa & Sinyal (TP2 Otomatis 1:2 ~ 1:2.5)</h1>
    <form method="POST">
        <div class="row">
            <div class="col">
                <label>Symbol</label>
                <select name="symbol">
                    <option value="XAUUSD" {{ 'selected' if data.symbol=='XAUUSD' else '' }}>XAUUSD (Gold)</option>
                    <option value="EURUSD" {{ 'selected' if data.symbol=='EURUSD' else '' }}>EURUSD</option>
                    <option value="GBPUSD" {{ 'selected' if data.symbol=='GBPUSD' else '' }}>GBPUSD</option>
                    <option value="USDJPY" {{ 'selected' if data.symbol=='USDJPY' else '' }}>USDJPY</option>
                </select>
            </div>
            <div class="col">
                <label>Arah Entry</label>
                <select name="direction">
                    <option value="BUY" {{ 'selected' if data.direction=='BUY' else '' }}>BUY</option>
                    <option value="SELL" {{ 'selected' if data.direction=='SELL' else '' }}>SELL</option>
                </select>
            </div>
        </div>
        <div class="row">
            <div class="col"><label>Harga Saat Ini (Entry)</label><input type="number" step="any" name="price" value="{{ data.price }}"></div>
            <div class="col"><label>ATR (Average True Range)</label><input type="number" step="any" name="atr" value="{{ data.atr }}"></div>
        </div>
        <div class="row">
            <div class="col"><label>Daily High</label><input type="number" step="any" name="daily_high" value="{{ data.daily_high }}"></div>
            <div class="col"><label>Daily Low</label><input type="number" step="any" name="daily_low" value="{{ data.daily_low }}"></div>
        </div>
        <div class="row">
            <div class="col"><label>Last Swing High (untuk SELL)</label><input type="number" step="any" name="swing_high" value="{{ data.swing_high }}"></div>
            <div class="col"><label>Last Swing Low (untuk BUY)</label><input type="number" step="any" name="swing_low" value="{{ data.swing_low }}"></div>
        </div>
        <div class="row">
            <div class="col"><label>Trend</label><input type="text" name="trend" value="{{ data.trend }}" placeholder="ex: Uptrend / Downtrend"></div>
            <div class="col"><label>Momentum</label><input type="text" name="momentum" value="{{ data.momentum }}" placeholder="ex: Konsolidasi, Strong Breakout"></div>
        </div>
        <div class="col">
            <label>Zona Kunci (Supply/Demand / S/R)</label>
            <input type="text" name="key_zone" value="{{ data.key_zone }}" placeholder="ex: Order Block 2645 - 2655">
        </div>
        
        <!-- Info otomatis -->
        <div class="info-box">
            ⚡ <strong>TP2 Otomatis</strong>: Sistem akan menghitung RR antara 1:2.0 hingga 1:2.5 berdasarkan ruang menuju Daily High/Low (TP3). 
            Jika ruang cukup, RR mendekati 2.5; jika terbatas, RR mendekati 2.0.
        </div>

        <button type="submit">🚀 Generate Analisa & Sinyal</button>
    </form>

    {% if result %}
    <div class="result">{{ result }}</div>
    {% endif %}
</div>
</body>
</html>
"""

# ============ LOGIKA SIGNAL (TP2 OTOMATIS) ============
def generate_signal(symbol, price, atr, daily_high, daily_low, swing_high, swing_low,
                    trend, momentum, key_zone, direction="BUY"):

    # ----- 1. Hitung jarak SL -----
    base_sl = atr * 1.5

    if symbol == "XAUUSD":
        if direction == "BUY":
            dist_to_swing = abs(price - swing_low)
        else:
            dist_to_swing = abs(swing_high - price)

        sl_distance = min(base_sl, 1.0, dist_to_swing * 0.9)
        sl_distance = max(sl_distance, 0.6)  # Minimal 60 pip
    else:
        sl_distance = base_sl
        if symbol in ["EURUSD", "GBPUSD"]:
            sl_distance = max(sl_distance, 0.0010)
        elif symbol == "USDJPY":
            sl_distance = max(sl_distance, 0.10)

    # ----- 2. Hitung Entry, SL, TP -----
    if direction == "BUY":
        entry = price
        stop_loss = entry - sl_distance
        tp1 = entry + (sl_distance * 1.5)
        
        # --- TP2 OTOMATIS (RENTANG 2.0 - 2.5) ---
        # Hitung max RR yang bisa dicapai ke Daily High
        max_rr_to_daily = (daily_high - entry) / sl_distance if sl_distance > 0 else 0
        # Clamp ke rentang 2.0 - 2.5
        tp2_mult = max(2.0, min(2.5, max_rr_to_daily))
        tp2 = entry + (sl_distance * tp2_mult)

        # TP3 Intraday = Daily High
        tp3 = daily_high
        # Jika TP3 keburu di bawah TP2 (karena daily high terlalu dekat), geser TP3 ke atas
        if tp3 <= tp2:
            tp3 = tp2 + (sl_distance * 0.5)

    else:  # SELL
        entry = price
        stop_loss = entry + sl_distance
        tp1 = entry - (sl_distance * 1.5)

        max_rr_to_daily = (entry - daily_low) / sl_distance if sl_distance > 0 else 0
        tp2_mult = max(2.0, min(2.5, max_rr_to_daily))
        tp2 = entry - (sl_distance * tp2_mult)

        tp3 = daily_low
        if tp3 >= tp2:
            tp3 = tp2 - (sl_distance * 0.5)

    # ----- 3. Format desimal -----
    dec = 2 if symbol == "XAUUSD" else 5
    if symbol == "USDJPY": dec = 3

    # ----- 4. Konversi SL ke pip -----
    if symbol == "XAUUSD":
        sl_pips = sl_distance * 100
    elif symbol in ["EURUSD", "GBPUSD"]:
        sl_pips = sl_distance * 10000
    else:
        sl_pips = sl_distance * 100

    # ----- 5. Buat output text -----
    analysis_text = f"""
=== 📈 ANALISA MARKET ({symbol}) ===
▸ Trend & Struktur  : {trend}
▸ Momentum          : {momentum} (ATR: {round(atr, 4)})
▸ Zona Kunci        : {key_zone}

=== 🎯 SINYAL {direction} ===
▸ Entry             : {round(entry, dec)}
▸ Stop Loss (SL)    : {round(stop_loss, dec)}  (Jarak: {round(sl_pips, 1)} pip)
▸ Take Profit 1 (TP1): {round(tp1, dec)}  (RR 1:1.5)
▸ Take Profit 2 (TP2): {round(tp2, dec)}  (RR 1:{tp2_mult:.1f})  ← OTOMATIS
▸ Take Profit 3 (TP3): {round(tp3, dec)}  (INTRADAY - target harian)

📝 REASON ENTRY:
Entry {direction} karena harga berada di area {key_zone} dengan konfirmasi struktur {trend}.
SL ditempatkan di {'bawah' if direction == 'BUY' else 'atas'} swing terdekat dan zona Supply/Demand untuk menghindari stop hunting.
Target TP1 diambil profit parsial, TP2 mengikuti ruang gerak ke target harian (otomatis 1:2.0 - 1:2.5), TP3 mengejar high/low hari ini.
"""
    return analysis_text


# ============ ROUTE FLASK ============
@app.route("/", methods=["GET", "POST"])
def index():
    data = {
        "symbol": "XAUUSD",
        "price": 2650.50,
        "atr": 12.5,
        "daily_high": 2665.00,
        "daily_low": 2640.00,
        "swing_high": 2660.00,
        "swing_low": 2645.00,
        "trend": "Uptrend",
        "momentum": "Konsolidasi setelah breakout",
        "key_zone": "Order Block 2645 - 2655",
        "direction": "BUY"
    }

    result = None

    if request.method == "POST":
        try:
            symbol = request.form.get("symbol", "XAUUSD")
            price = float(request.form.get("price", 2650))
            atr = float(request.form.get("atr", 10))
            daily_high = float(request.form.get("daily_high", 2665))
            daily_low = float(request.form.get("daily_low", 2640))
            swing_high = float(request.form.get("swing_high", 2660))
            swing_low = float(request.form.get("swing_low", 2645))
            trend = request.form.get("trend", "Uptrend")
            momentum = request.form.get("momentum", "Konsolidasi")
            key_zone = request.form.get("key_zone", "Order Block")
            direction = request.form.get("direction", "BUY").upper()

            data.update({
                "symbol": symbol, "price": price, "atr": atr,
                "daily_high": daily_high, "daily_low": daily_low,
                "swing_high": swing_high, "swing_low": swing_low,
                "trend": trend, "momentum": momentum,
                "key_zone": key_zone, "direction": direction
            })

            result = generate_signal(
                symbol, price, atr, daily_high, daily_low,
                swing_high, swing_low, trend, momentum, key_zone,
                direction
            )
        except Exception as e:
            result = f"⚠️ Error: {str(e)}. Pastikan semua input angka terisi."

    return render_template_string(HTML_TEMPLATE, data=data, result=result)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
