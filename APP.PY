from flask import Flask, request, jsonify
import os
import threading
from binance.client import Client
from binance.enums import *

app = Flask(__name__)

API_KEY        = os.environ.get("BINANCE_API_KEY")
API_SECRET     = os.environ.get("BINANCE_API_SECRET")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")
SYMBOL         = "ETHUSDT"
LEVERAGE       = 25
RIESGO_PCT     = 0.10
SL_ATR_MULT    = 2.4

def get_client():
    return Client(API_KEY, API_SECRET, ping=False)

def get_precision(client):
    try:
        info = client.futures_exchange_info()
        for s in info['symbols']:
            if s['symbol'] == SYMBOL:
                return int(s['quantityPrecision'])
    except:
        pass
    return 3

def get_quantity(atr, client):
    try:
        balance  = client.futures_account_balance()
        usdt     = next((b for b in balance if b["asset"] == "USDT"), None)
        if not usdt:
            raise Exception("No USDT balance")
        available        = float(usdt["availableBalance"])
        price            = float(client.futures_symbol_ticker(symbol=SYMBOL)["price"])
        precision        = get_precision(client)
        riesgo_cash      = available * RIESGO_PCT
        dist             = atr * SL_ATR_MULT
        qty              = round(riesgo_cash / dist, precision)
        margen_requerido = (qty * price) / LEVERAGE
        if margen_requerido > available * 0.90:
            qty = round((available * 0.90 * LEVERAGE) / price, precision)
        return qty
    except Exception as e:
        raise Exception(f"Error calculando quantity: {e}")

def process_signal(signal, atr):
    try:
        client = get_client()
        print(f"[PROCESS] signal={signal} atr={atr}")

        if signal in ["long", "short"]:
            qty = get_quantity(atr, client)
            if qty <= 0:
                print("[PROCESS] qty too small, abortando")
                return
            side = SIDE_BUY if signal == "long" else SIDE_SELL
            try:
                client.futures_change_leverage(symbol=SYMBOL, leverage=LEVERAGE)
            except Exception as e:
                print(f"[PROCESS] leverage warning: {e}")
            order = client.futures_create_order(
                symbol=SYMBOL,
                side=side,
                type=ORDER_TYPE_MARKET,
                quantity=qty
            )
            print(f"[PROCESS] Orden ejecutada: {order}")

        elif signal in ["close_long", "close_short"]:
            positions = client.futures_position_information(symbol=SYMBOL)
            closed = False
            for p in positions:
                amt = float(p["positionAmt"])
                if amt != 0:
                    close_side = SIDE_SELL if amt > 0 else SIDE_BUY
                    order = client.futures_create_order(
                        symbol=SYMBOL,
                        side=close_side,
                        type=ORDER_TYPE_MARKET,
                        quantity=abs(amt),
                        reduceOnly=True
                    )
                    print(f"[PROCESS] Posicion cerrada: {order}")
                    closed = True
            if not closed:
                print("[PROCESS] No habia posicion abierta")

    except Exception as e:
        print(f"[PROCESS] ERROR: {e}")

@app.route("/ping", methods=["GET"])
def ping():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True)

    if not data:
        print(f"[WEBHOOK] Body vacio. Raw: {request.data}")
        return jsonify({"error": "no data"}), 400

    print(f"[WEBHOOK] Recibido: {data}")

    if data.get("secret") != WEBHOOK_SECRET:
        print(f"[WEBHOOK] Secret invalido: '{data.get('secret')}'")
        return jsonify({"error": "unauthorized"}), 401

    signal = data.get("signal")
    if signal not in ["long", "short", "close_long", "close_short"]:
        print(f"[WEBHOOK] Signal invalida: '{signal}'")
        return jsonify({"error": "invalid signal"}), 400

    atr = 0.0
    if signal in ["long", "short"]:
        atr = float(data.get("atr", 0))
        if atr <= 0:
            return jsonify({"error": "invalid atr"}), 400

    t = threading.Thread(target=process_signal, args=(signal, atr))
    t.daemon = True
    t.start()

    print(f"[WEBHOOK] OK enviado a TV, procesando en background")
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
