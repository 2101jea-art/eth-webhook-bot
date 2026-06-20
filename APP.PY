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

# CACHE SIMPLE
_cache = {}
CACHE_TTL = 30

def get_cached(key, func, *args, **kwargs):

    now = time.time()

    if key in _cache:
        if now - _cache[key]["t"] < CACHE_TTL:
            return _cache[key]["v"]

    result = func(*args, **kwargs)

    _cache[key] = {
        "v": result,
        "t": now
    }

    return result

PRECISION = 3
BALANCE_CACHE = None

try:
    info = client.futures_exchange_info()

    for s in info["symbols"]:
        if s["symbol"] == SYMBOL:
            PRECISION = int(s["quantityPrecision"])
            break

except Exception as e:
    print(f"Error obteniendo precision: {e}")

def retry_binance(func, *args, **kwargs):

    ultimo_error = None

    for intento in range(2):

        try:
            return func(*args, **kwargs)

        except BinanceAPIException as e:

            ultimo_error = e

            print(f"Binance error codigo: {e.code} mensaje: {e}")

            if e.code == -1003:

                # Si el mensaje dice "banned until", NO reintentar.
                # Reintentar mientras el ban esta activo solo suma
                # peso y puede extender el ban (confirmado por Binance).
                if "banned until" in str(e):
                    print("IP banneada. No se reintenta.")
                    raise Exception(
                        f"IP banneada por Binance: {e}"
                    )

                print(f"Rate limit (no ban). Reintento {intento+1}/2")
                time.sleep(2)
            else:
                raise

    raise Exception(f"Binance -1003 persistente: {ultimo_error}")

def refresh_balance():

    global BALANCE_CACHE

    balance = retry_binance(
        client.futures_account_balance
    )

    usdt = next(
        (b for b in balance if b["asset"] == "USDT"),
        None
    )

    if not usdt:
        raise Exception("No USDT balance")

    BALANCE_CACHE = float(
        usdt["availableBalance"]
    )

    print(
        f"Balance actualizado: {BALANCE_CACHE}"
    )

try:
    refresh_balance()
except Exception as e:
    print(
        f"Error cargando balance inicial: {e}"
    )

def get_quantity(atr):

    global BALANCE_CACHE

    try:

        if BALANCE_CACHE is None:
            refresh_balance()

        available = BALANCE_CACHE

        price = float(
            get_cached(
                f"price_{SYMBOL}",
                lambda: retry_binance(
                    client.futures_symbol_ticker,
                    symbol=SYMBOL
                )
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

        if signal == "long":
            print("RECIBI LONG")
        elif signal == "short":
            print("RECIBI SHORT")
        elif signal == "close_long":
            print("RECIBI CLOSE_LONG")
        elif signal == "close_short":
            print("RECIBI CLOSE_SHORT")

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

            try:
                refresh_balance()
            except Exception as e:
                print(
                    f"Error actualizando balance: {e}"
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
