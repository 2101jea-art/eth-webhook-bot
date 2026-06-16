from flask import Flask, request, jsonify
import os
import time
from binance.client import Client
from binance.enums import *
from binance.exceptions import BinanceAPIException

app = Flask(__name__)

API_KEY        = os.environ.get("BINANCE_API_KEY")
API_SECRET     = os.environ.get("BINANCE_API_SECRET")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")

SYMBOL         = "ETHUSDT"
LEVERAGE       = 25
RIESGO_PCT     = 0.10
SL_ATR_MULT    = 2.4

client = Client(API_KEY, API_SECRET, ping=False)

# ===== PRECISION CARGADA UNA SOLA VEZ =====
PRECISION = 3

try:
    info = client.futures_exchange_info()

    for s in info["symbols"]:
        if s["symbol"] == SYMBOL:
            PRECISION = int(s["quantityPrecision"])
            break

except Exception as e:
    print(f"Error obteniendo precision: {e}")

# ==========================================

# ===== RETRY PARA -1003 =====
```python
def retry_binance(func, *args, **kwargs):

    ultimo_error = None

    for intento in range(2):

        try:
            return func(*args, **kwargs)

        except BinanceAPIException as e:

            ultimo_error = e

            print("=" * 60)
            print("BINANCE ERROR COMPLETO")
            print(f"Codigo: {e.code}")
            print(f"Mensaje: {e}")
            print("=" * 60)

            if e.code == -1003:

                print(f"Rate limit. Reintento {intento+1}/2")
                time.sleep(1)

            else:
                raise

    raise Exception(
        f"Binance sigue respondiendo -1003. "
        f"Error completo: {ultimo_error}"
    )



# ================================

def get_quantity(atr):

    try:

        balance = retry_binance(client.futures_account_balance)

        usdt = next(
            (b for b in balance if b["asset"] == "USDT"),
            None
        )

        if not usdt:
            raise Exception("No USDT balance")

        available = float(usdt["availableBalance"])

        price = float(
            retry_binance(
                client.futures_symbol_ticker,
                symbol=SYMBOL
            )["price"]
        )

        riesgo_cash = available * RIESGO_PCT

        dist = atr * SL_ATR_MULT

        qty = round(
            riesgo_cash / dist,
            PRECISION
        )

        margen_requerido = (
            qty * price
        ) / LEVERAGE

        if margen_requerido > available * 0.90:

            qty = round(
                (
                    available
                    * 0.90
                    * LEVERAGE
                ) / price,
                PRECISION
            )

        return qty

    except Exception as e:

        raise Exception(
            f"Error calculando quantity: {e}"
        )

@app.route("/ping", methods=["GET"])
def ping():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():

    data = request.get_json(
        force=True,
        silent=True
    )

    if not data:
        return jsonify(
            {"error": "no data"}
        ), 400

    if data.get("secret") != WEBHOOK_SECRET:

        return jsonify(
            {"error": "unauthorized"}
        ), 401

    signal = data.get("signal")

    if signal not in [
        "long",
        "short",
        "close_long",
        "close_short"
    ]:

        return jsonify(
            {"error": "invalid signal"}
        ), 400

    try:

        print("WEBHOOK:", data)

        if signal in ["long", "short"]:

            atr = float(
                data.get("atr", 0)
            )

            if atr <= 0:

                return jsonify(
                    {"error": "invalid atr"}
                ), 400

            qty = get_quantity(atr)

            if qty <= 0:

                return jsonify(
                    {"error": "qty too small"}
                ), 400

            side = (
                SIDE_BUY
                if signal == "long"
                else SIDE_SELL
            )

            retry_binance(
                client.futures_create_order,
                symbol=SYMBOL,
                side=side,
                type=ORDER_TYPE_MARKET,
                quantity=qty
            )

        elif signal in [
            "close_long",
            "close_short"
        ]:

            positions = retry_binance(
                client.futures_position_information,
                symbol=SYMBOL
            )

            for p in positions:

                amt = float(
                    p["positionAmt"]
                )

                if amt != 0:

                    close_side = (
                        SIDE_SELL
                        if amt > 0
                        else SIDE_BUY
                    )

                    retry_binance(
                        client.futures_create_order,
                        symbol=SYMBOL,
                        side=close_side,
                        type=ORDER_TYPE_MARKET,
                        quantity=abs(amt),
                        reduceOnly=True
                    )

        return jsonify(
            {"status": "ok"}
        ), 200

    except Exception as e:

        import traceback

        traceback.print_exc()

        return jsonify(
            {"error": str(e)}
        ), 500

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
