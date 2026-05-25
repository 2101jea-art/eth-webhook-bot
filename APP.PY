from flask import Flask, request, jsonify
import os
from binance.client import Client
from binance.enums import *

app = Flask(__name__)

API_KEY    = os.environ.get("BINANCE_API_KEY")
API_SECRET = os.environ.get("BINANCE_API_SECRET")
SYMBOL     = "ETHUSDT"
LEVERAGE   = 25

client = Client(API_KEY, API_SECRET)

def get_quantity():
    balance = client.futures_account_balance()
    usdt = next((b for b in balance if b["asset"] == "USDT"), None)
    if not usdt:
        raise Exception("No se encontró balance USDT")
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

    side  = data.get("side")
    close = data.get("close", False)

    try:
        if close:
            position = client.futures_position_information(symbol=SYMBOL)
            for p in position:
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
        else:
            qty = get_quantity()
            client.futures_create_order(
                symbol=SYMBOL,
                side=side,
                type=ORDER_TYPE_MARKET,
                quantity=qty
            )
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
