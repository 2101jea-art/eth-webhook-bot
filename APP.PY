from flask import Flask, request, jsonify
import hmac, hashlib, os
from binance.client import Client

app = Flask(__name__)

API_KEY    = os.environ.get("BINANCE_API_KEY")
API_SECRET = os.environ.get("BINANCE_API_SECRET")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")
SYMBOL     = "ETHUSDT"
QUANTITY   = float(os.environ.get("QUANTITY", "0.01"))

client = Client(API_KEY, API_SECRET)

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
                    close_side = "SELL" if amt > 0 else "BUY"
                    client.futures_create_order(
                        symbol=SYMBOL,
                        side=close_side,
                        type="MARKET",
                        quantity=abs(amt),
                        reduceOnly=True
                    )
        else:
            client.futures_create_order(
                symbol=SYMBOL,
                side=side,
                type="MARKET",
                quantity=QUANTITY
            )
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
