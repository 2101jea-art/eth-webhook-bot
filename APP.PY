from flask import Flask, request, jsonify
import os
from binance.client import Client
from binance.enums import *

app = Flask(__name__)

API_KEY        = os.environ.get("BINANCE_API_KEY")
API_SECRET     = os.environ.get("BINANCE_API_SECRET")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")
SYMBOL         = "ETHUSDT"
LEVERAGE       = 25

client = Client(API_KEY, API_SECRET)

def get_quantity():
    balance = client.futures_account_balance()
    usdt = next((b for b in balance if b["asset"] == "USDT"), None)
    if not usdt:
        raise Exception("No USDT balance")
    capital = float(usdt["availableBalance"])
    price = float(client.futures_symbol_ticker(symbol=SYMBOL)["price"])
    position_value = capital * 0.90 * LEVERAGE
    quantity = round(position_value / price, 3)
    return quantity

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    if not data:
        return jsonify({"error": "no data"}), 400

    # Validar clave secreta
    if data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"error": "unauthorized"}), 401

    # Validar que tenga señal explícita
    signal = data.get("signal")
    if signal not in ["long", "short", "close_long", "close_short"]:
        return jsonify({"error": "invalid signal"}), 400

    try:
        if signal == "long":
            qty = get_quantity()
            client.futures_create_order(
                symbol=SYMBOL,
                side=SIDE_BUY,
                type=ORDER_TYPE_MARKET,
                quantity=qty
            )
        elif signal == "short":
            qty = get_quantity()
            client.futures_create_order(
                symbol=SYMBOL,
                side=SIDE_SELL,
                type=ORDER_TYPE_MARKET,
                quantity=qty
            )
        elif signal in ["close_long", "close_short"]:
            positions = client.futures_position_information(symbol=SYMBOL)
            for p in positions:
                amt = float(p["positionAmt"])
                if amt != 0:
                    close_side = SIDE_SELL if amt > 0 else SIDE_BUY
                    client.futures_create_order(
                        symbol=SYMBOL,
                        side=close_side,
                        type=ORDER_TYPE_MARKET,
                        quantity=abs(amt),
                        reduceOnly=True
                    )
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
