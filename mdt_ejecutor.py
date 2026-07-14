# -*- coding: utf-8 -*-
"""Ejecución REAL de órdenes contra Binance Futures TESTNET (regla usuario 14
jul: "que operen como si fueran reales, sin meter dinero real").

Solo se usa cuando MDT_MODO=testnet (mdt_config.py); en 'observacion' (default)
nada de este módulo se llama y el bot se comporta exactamente igual que antes.

Diseño (a propósito conservador): la decisión de CUÁNDO entrar/salir la sigue
dando mdt_gestion.gestionar() sobre velas reales — la misma que ya se validó
toda la sesión. Este módulo no decide nada de estrategia: solo REPRODUCE esa
decisión con órdenes reales en el testnet (firma, redondeo, rate limits, rechazos
del exchange) y devuelve lo que REALMENTE pasó (precio de llenado, P&L, comisión).

TRES COSAS QUE HAY QUE ENTENDER (auditoría 14 jul — sin ellas la simulación miente):

1. MODO HEDGE OBLIGATORIO. En one-way Binance tiene UNA sola posición neta por
   símbolo: el bot abre varias operaciones a la vez en BNBUSDT (compras Y ventas
   concurrentes de zonas distintas), y una venta a mercado estando largo NO abre
   un corto — REDUCE el largo. Con hedge (dualSidePosition) conviven LONG y SHORT
   y cada orden dice a qué lado pertenece (positionSide). En hedge, las órdenes de
   cierre NO llevan reduceOnly (Binance las rechaza): basta el positionSide.

2. LAS ÓRDENES SE CANCELAN UNA A UNA. `cancelar_todas(symbol)` borraba el SL y el
   TP de las OTRAS operaciones vivas del mismo símbolo — las dejaba a pelo.

3. EL P&L SALE DE LOS LLENADOS REALES (userTrades: realizedPnl - commission), no
   de la R teórica. Si no, el deslizamiento y las comisiones — justo lo que se
   quiere medir con el testnet — quedan invisibles.

Sizing: arriesga RIESGO_CUENTA_PCT del balance virtual ACTUAL (compone) en cada
gatillo nuevo — cantidad = (balance * riesgo%) / distancia_al_SL.
"""
import hashlib
import hmac
import logging
import os
import time
import urllib.parse

import requests

from mdt_config import RIESGO_CUENTA_PCT

log = logging.getLogger('mdt.ejecutor')

BASE_URL = "https://testnet.binancefuture.com"
TIMEOUT = 10

API_KEY = os.environ.get('MDT_BINANCE_TESTNET_KEY', '')
API_SECRET = os.environ.get('MDT_BINANCE_TESTNET_SECRET', '').encode()

_info_simbolo_cache = {}
_hedge_ok = False          # se comprueba una vez por proceso


class ErrorEjecucion(Exception):
    """Cualquier fallo hablando con el testnet (red, firma, orden rechazada)."""


def _firmar(params):
    query = urllib.parse.urlencode(params)
    firma = hmac.new(API_SECRET, query.encode(), hashlib.sha256).hexdigest()
    return f"{query}&signature={firma}"


def _request(method, path, params=None, firmado=True):
    if not API_KEY or not API_SECRET:
        raise ErrorEjecucion("MDT_BINANCE_TESTNET_KEY/SECRET vacíos: no se puede operar en testnet.")
    params = dict(params or {})
    headers = {'X-MBX-APIKEY': API_KEY}
    try:
        if firmado:
            params['timestamp'] = int(time.time() * 1000)
            params['recvWindow'] = 5000
            url = f"{BASE_URL}{path}?{_firmar(params)}"
            r = requests.request(method, url, headers=headers, timeout=TIMEOUT)
        else:
            r = requests.request(method, f"{BASE_URL}{path}", params=params,
                                 headers=headers, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise ErrorEjecucion(f"{method} {path}: fallo de red — {e}") from e
    if r.status_code != 200:
        raise ErrorEjecucion(f"{method} {path} -> {r.status_code}: {r.text}")
    return r.json()


# ---------------------------------------------------------------------------
# Modo hedge: sin él, una venta estando largo reduce el largo (no abre corto)
# ---------------------------------------------------------------------------
def asegurar_modo_hedge():
    """Activa dualSidePosition si no lo estaba. Binance solo deja cambiarlo con
    la cuenta SIN posiciones ni órdenes abiertas."""
    global _hedge_ok
    if _hedge_ok:
        return
    estado = _request('GET', '/fapi/v1/positionSide/dual')
    if estado.get('dualSidePosition'):
        _hedge_ok = True
        return
    try:
        _request('POST', '/fapi/v1/positionSide/dual', {'dualSidePosition': 'true'})
    except ErrorEjecucion as e:
        raise ErrorEjecucion(
            "La cuenta del testnet está en modo ONE-WAY y no se pudo cambiar a HEDGE "
            "(Binance solo lo permite sin posiciones ni órdenes abiertas). En one-way, "
            "una venta estando largo REDUCE el largo en vez de abrir un corto: las "
            f"operaciones del bot no se reflejarían. Cierra todo en el testnet y reintenta. [{e}]") from e
    _hedge_ok = True
    log.info("testnet: modo HEDGE activado")


def _position_side(lado):
    return 'LONG' if lado == 'BUY' else 'SHORT'


def info_simbolo(symbol):
    """Precisión de cantidad/precio del símbolo (exchangeInfo, público, cacheado)."""
    if symbol in _info_simbolo_cache:
        return _info_simbolo_cache[symbol]
    data = _request('GET', '/fapi/v1/exchangeInfo', firmado=False)
    for s in data.get('symbols', []):
        if s['symbol'] != symbol:
            continue
        qty_step = price_step = None
        for f in s['filters']:
            if f['filterType'] == 'LOT_SIZE':
                qty_step = float(f['stepSize'])
            elif f['filterType'] == 'PRICE_FILTER':
                price_step = float(f['tickSize'])
        info = {'qty_step': qty_step, 'price_step': price_step,
                'qty_precision': s['quantityPrecision'],
                'price_precision': s['pricePrecision']}
        _info_simbolo_cache[symbol] = info
        return info
    raise ErrorEjecucion(f"Símbolo {symbol} no existe en exchangeInfo del testnet.")


def _redondear(valor, paso, precision):
    if not paso:
        return round(valor, precision)
    pasos = round(valor / paso)
    return round(pasos * paso, precision)


def balance_disponible_testnet():
    """Balance USDT real del testnet (informativo, para cruzar contra la cuenta
    virtual — NO es lo que se usa para dimensionar posiciones)."""
    data = _request('GET', '/fapi/v2/balance', firmado=True)
    for b in data:
        if b['asset'] == 'USDT':
            return float(b['availableBalance'])
    return None


def calcular_cantidad(symbol, entrada, sl, balance_virtual):
    """Cantidad (en el activo base) para arriesgar RIESGO_CUENTA_PCT del balance
    virtual dado, según distancia al SL. Redondeada al step del símbolo."""
    riesgo_precio = abs(entrada - sl)
    if riesgo_precio <= 0:
        raise ErrorEjecucion("Riesgo en precio es cero: no se puede dimensionar.")
    riesgo_dolares = balance_virtual * RIESGO_CUENTA_PCT
    cantidad = riesgo_dolares / riesgo_precio
    info = info_simbolo(symbol)
    cantidad = _redondear(cantidad, info['qty_step'], info['qty_precision'])
    if cantidad <= 0:
        raise ErrorEjecucion(f"Cantidad calculada es {cantidad} tras redondear "
                             f"(riesgo ${riesgo_dolares:.2f} / {riesgo_precio:.4f} "
                             f"de distancia) — muy chica para el step del símbolo.")
    return cantidad


def _precio_llenado(symbol, order_id, intentos=5):
    """avgPrice REAL de una orden a mercado (lo que de verdad pagó, con
    deslizamiento). Una MARKET llena al instante, pero se reintenta por si el
    exchange aún no la reporta."""
    for i in range(intentos):
        o = _request('GET', '/fapi/v1/order', {'symbol': symbol, 'orderId': order_id})
        precio = float(o.get('avgPrice') or 0)
        if o.get('status') == 'FILLED' and precio > 0:
            return precio
        time.sleep(0.4 * (i + 1))
    return None


def abrir_posicion(symbol, lado, entrada, sl, tp, balance_virtual):
    """ENTRADA a mercado + SL + TP reales en el testnet (modo hedge).

    Devuelve {'cantidad', 'ordenes' (ids para cancelar sólo las suyas),
    'order_id_sl', 'entrada_real' (precio de llenado), 'inicio_ms', 'position_side'}.
    """
    asegurar_modo_hedge()
    cantidad = calcular_cantidad(symbol, entrada, sl, balance_virtual)
    info = info_simbolo(symbol)
    sl_r = _redondear(sl, info['price_step'], info['price_precision'])
    tp_r = _redondear(tp, info['price_step'], info['price_precision'])
    ps = _position_side(lado)
    cierre = 'SELL' if lado == 'BUY' else 'BUY'
    inicio_ms = int(time.time() * 1000) - 1000

    orden_entrada = _request('POST', '/fapi/v1/order', {
        'symbol': symbol, 'side': lado, 'positionSide': ps,
        'type': 'MARKET', 'quantity': cantidad,
    })
    id_entrada = orden_entrada.get('orderId')
    entrada_real = _precio_llenado(symbol, id_entrada)
    log.info("testnet %s: ENTRADA %s qty=%s -> orderId=%s llenó en %s (teórica %s)",
             symbol, lado, cantidad, id_entrada, entrada_real, entrada)

    # En HEDGE las órdenes de cierre NO llevan reduceOnly: manda el positionSide
    comun = {'symbol': symbol, 'side': cierre, 'positionSide': ps, 'quantity': cantidad}
    orden_sl = _request('POST', '/fapi/v1/order',
                        {**comun, 'type': 'STOP_MARKET', 'stopPrice': sl_r})
    orden_tp = _request('POST', '/fapi/v1/order',
                        {**comun, 'type': 'TAKE_PROFIT_MARKET', 'stopPrice': tp_r})
    return {'cantidad': cantidad,
            'position_side': ps,
            'entrada_real': entrada_real,
            'inicio_ms': inicio_ms,
            'order_id_sl': orden_sl.get('orderId'),
            'ordenes': [i for i in (id_entrada, orden_sl.get('orderId'),
                                    orden_tp.get('orderId')) if i is not None]}


def mover_stop(symbol, lado, cantidad, order_id_viejo, nuevo_stop, position_side):
    """Cancela el SL viejo y coloca uno nuevo (ej. a breakeven tras el parcial)."""
    info = info_simbolo(symbol)
    stop_r = _redondear(nuevo_stop, info['price_step'], info['price_precision'])
    cierre = 'SELL' if lado == 'BUY' else 'BUY'
    if order_id_viejo is not None:
        cancelar_ordenes(symbol, [order_id_viejo])
    orden = _request('POST', '/fapi/v1/order', {
        'symbol': symbol, 'side': cierre, 'positionSide': position_side,
        'type': 'STOP_MARKET', 'stopPrice': stop_r, 'quantity': cantidad,
    })
    return orden.get('orderId')


def cerrar_parcial(symbol, lado, cantidad_parcial, position_side):
    """Cierra media posición a mercado (Secc 20: parcial obligatorio)."""
    cierre = 'SELL' if lado == 'BUY' else 'BUY'
    info = info_simbolo(symbol)
    cantidad_parcial = _redondear(cantidad_parcial, info['qty_step'], info['qty_precision'])
    if cantidad_parcial <= 0:
        return None
    orden = _request('POST', '/fapi/v1/order', {
        'symbol': symbol, 'side': cierre, 'positionSide': position_side,
        'type': 'MARKET', 'quantity': cantidad_parcial,
    })
    return orden.get('orderId')


def cerrar_a_mercado(symbol, lado, cantidad, position_side):
    """Cierra lo que quede de la posición a mercado (cuando la gestión da la
    operación por terminada pero el SL/TP del exchange no ha saltado)."""
    return cerrar_parcial(symbol, lado, cantidad, position_side)


def cancelar_ordenes(symbol, order_ids):
    """Cancela SOLO las órdenes indicadas. NUNCA `allOpenOrders`: eso borraba los
    SL/TP de las demás operaciones vivas del mismo símbolo (auditoría 14 jul)."""
    for oid in order_ids or []:
        try:
            _request('DELETE', '/fapi/v1/order', {'symbol': symbol, 'orderId': oid})
        except ErrorEjecucion:
            # Lo normal: ya se llenó o ya no existe. No es un fallo.
            log.debug("testnet: la orden %s de %s ya no estaba abierta", oid, symbol)


def pnl_realizado(symbol, order_ids, desde_ms):
    """P&L REAL de esta operación según el exchange: suma de realizedPnl menos
    comisiones de los trades de SUS órdenes. Aquí es donde aparecen el
    deslizamiento y las comisiones que la R teórica no ve."""
    trades = _request('GET', '/fapi/v1/userTrades',
                      {'symbol': symbol, 'startTime': int(desde_ms), 'limit': 1000})
    ids = {str(i) for i in (order_ids or [])}
    pnl = comision = 0.0
    for t in trades:
        if str(t.get('orderId')) not in ids:
            continue
        pnl += float(t.get('realizedPnl', 0) or 0)
        comision += float(t.get('commission', 0) or 0)
    return {'pnl': pnl - comision, 'bruto': pnl, 'comision': comision}
