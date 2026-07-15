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

from mdt_config import RIESGO_CUENTA_PCT, RIESGO_USD

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
    # Monto fijo en dólares si está configurado (regla usuario: "riesgo $1"), si no
    # el % del balance. El fijo no cambia con el balance.
    riesgo_dolares = RIESGO_USD if RIESGO_USD > 0 else balance_virtual * RIESGO_CUENTA_PCT
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

    # SL y TP: órdenes CONDICIONALES -> Algo Order API (ver _algo_stop). El
    # STOP_MARKET en /fapi/v1/order dejó de existir el 9-dic-2025 y sin esto la
    # entrada quedaba SIN STOP (posición desnuda, el bug del 14 jul).
    algo_sl = _algo_stop(symbol, cierre, ps, 'STOP_MARKET', sl_r, cantidad)
    algo_tp = _algo_stop(symbol, cierre, ps, 'TAKE_PROFIT_MARKET', tp_r, cantidad)
    return {'cantidad': cantidad,
            'position_side': ps,
            'entrada_real': entrada_real,
            'inicio_ms': inicio_ms,
            'order_id_entrada': id_entrada,
            'algo_sl': algo_sl, 'algo_tp': algo_tp,
            'algos': [a for a in (algo_sl, algo_tp) if a is not None]}


def _algo_stop(symbol, side, position_side, tipo, trigger, cantidad):
    """Coloca una orden condicional (STOP_MARKET / TAKE_PROFIT_MARKET) en la Algo
    Order API. Devuelve el algoId. Desde el 9-dic-2025 Binance migró TODAS las
    condicionales a este servicio: el endpoint clásico las rechaza (-4120)."""
    o = _request('POST', '/fapi/v1/algoOrder', {
        'symbol': symbol, 'side': side, 'positionSide': position_side,
        'algoType': 'CONDITIONAL', 'type': tipo,
        'triggerPrice': trigger, 'quantity': cantidad,
    })
    return o.get('algoId')


class StopDispararia(ErrorEjecucion):
    """El stop pedido se dispararía de inmediato: el precio ya cruzó el nivel."""


def mover_stop(symbol, lado, cantidad, algo_viejo, nuevo_stop, position_side):
    """Cancela el SL viejo (algo) y coloca uno nuevo (ej. a breakeven tras el
    parcial). Devuelve el algoId nuevo.

    Si el nuevo stop se dispararía ya (el precio volvió al nivel antes de poder
    moverlo, -2021), se avisa con StopDispararia para que quien llama cierre a
    mercado en vez de dejar la posición sin stop."""
    info = info_simbolo(symbol)
    stop_r = _redondear(nuevo_stop, info['price_step'], info['price_precision'])
    cierre = 'SELL' if lado == 'BUY' else 'BUY'
    if algo_viejo is not None:
        cancelar_ordenes(symbol, [algo_viejo])
    try:
        return _algo_stop(symbol, cierre, position_side, 'STOP_MARKET', stop_r, cantidad)
    except ErrorEjecucion as e:
        if '-2021' in str(e):
            raise StopDispararia(str(e)) from e
        raise


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


def cancelar_ordenes(symbol, algo_ids):
    """Cancela SOLO las órdenes condicionales (SL/TP) indicadas, por su algoId.
    NUNCA todas: eso borraba los SL/TP de las demás operaciones vivas del mismo
    símbolo (auditoría 14 jul). La entrada ya está llenada, no se cancela."""
    for aid in algo_ids or []:
        try:
            _request('DELETE', '/fapi/v1/algoOrder', {'symbol': symbol, 'algoId': aid})
        except ErrorEjecucion:
            # Lo normal: ya se disparó o ya no existe. No es un fallo.
            log.debug("testnet: el algo %s de %s ya no estaba abierto", aid, symbol)


def algos_abiertos(symbol, algo_ids):
    """De una lista de algoIds, cuáles siguen ABIERTOS en el exchange. El que
    desaparece es que se DISPARÓ (cerró su cantidad de la posición). Esta es la
    verdad del cierre: el exchange, no la lectura de velas del bot."""
    if not algo_ids:
        return set()
    abiertos = _request('GET', '/fapi/v1/openAlgoOrders', {'symbol': symbol})
    vivos = {str(a.get('algoId')) for a in abiertos}
    return {a for a in algo_ids if str(a) in vivos}


def balance_real(symbol=None):
    """Balance USDT real del testnet (lo que de verdad tiene la cuenta demo).
    El bot usa ESTE para dimensionar y reportar, no un número inventado."""
    return balance_disponible_testnet()


def pnl_realizado(symbol, desde_ms, hasta_ms=None):
    """P&L REAL según el exchange en la ventana [desde_ms, hasta_ms]: suma de
    realizedPnl menos comisiones de los trades del símbolo.

    OJO — atribución con posiciones apiladas: cuando un stop condicional se
    dispara, Binance crea una orden nueva cuyo orderId NO conocíamos, así que ya
    no se puede filtrar por 'nuestras' órdenes. Se suma por VENTANA TEMPORAL (de
    la apertura al cierre de esta operación). Con varias del mismo lado abiertas a
    la vez, el reparto es aproximado; la verdad de la CUENTA la da siempre el
    balance real del testnet."""
    params = {'symbol': symbol, 'startTime': int(desde_ms), 'limit': 1000}
    if hasta_ms:
        params['endTime'] = int(hasta_ms)
    trades = _request('GET', '/fapi/v1/userTrades', params)
    pnl = comision = 0.0
    for t in trades:
        pnl += float(t.get('realizedPnl', 0) or 0)
        comision += float(t.get('commission', 0) or 0)
    return {'pnl': pnl - comision, 'bruto': pnl, 'comision': comision,
            'n_trades': len(trades)}
