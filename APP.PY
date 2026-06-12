from flask import Flask, request, jsonify
import os
import ccxt

app = Flask(__name__)

API_KEY        = os.environ.get("BINANCE_API_KEY")
API_SECRET     = os.environ.get("BINANCE_API_SECRET")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")
SYMBOL         = "ETH/USDT:USDT"
LEVERAGE       = 25
RIESGO_PCT     = 0.10
SL_ATR_MULT    = 2.4

exchange = ccxt.binance({
    "apiKey": API_KEY,
    "secret": API_SECRET,
    "options": {
        "defaultType": "swap",
        "adjustForTimeDifference": True
    },
    "enableRateLimit": False
})

try:
    exchange.load_markets()
except Exception as e:
    print(f"[INIT] Warning: load_markets failed: {e}")

def get_quantity(atr):
    try:
        balance   = exchange.fetch_balance({"type": "future"})
        available = float(balance["USDT"]["free"])
        ticker    = exchange.fetch_ticker(SYMBOL)
        price     = float(ticker["last"])
        precision = exchange.markets[SYMBOL]["precision"]["amount"]
        riesgo_cash      = available * RIESGO_PCT
        dist             = atr * SL_ATR_MULT
        qty              = round(riesgo_cash / dist, precision)
        margen_requerido = (qty * price) / LEVERAGE
        if margen_requerido > available * 0.90:
            qty = round((available * 0.90 * LEVERAGE) / price, precision)
        return qty
    except Exception as e:
        raise Exception(f"Error calculando quantity: {e}")

@app.route("/ping", methods=["GET"])
def ping():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "no data"}), 400
    if data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"error": "unauthorized"}), 401
    signal = data.get("signal")
    if signal not in ["long", "short", "close_long", "close_short"]:
        return jsonify({"error": "invalid signal"}), 400
    try:
        exchange.set_leverage(LEVERAGE, SYMBOL)
        if signal in ["long", "short"]:
            atr = float(data.get("atr", 0))
            if atr <= 0:
                return jsonify({"error": "invalid atr"}), 400
            qty = get_quantity(atr)
            if qty <= 0:
                return jsonify({"error": "qty too small"}), 400
            side = "buy" if signal == "long" else "sell"
            exchange.create_order(SYMBOL, "market", side, qty)
        elif signal in ["close_long", "close_short"]:
            positions = exchange.fetch_positions([SYMBOL])
            for p in positions:
                contracts = float(p["contracts"] or 0)
                if contracts != 0:
                    close_side = "sell" if p["side"] == "long" else "buy"
                    exchange.create_order(
                        SYMBOL, "market", close_side, contracts,
                        params={"reduceOnly": "true"}
                    )
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
