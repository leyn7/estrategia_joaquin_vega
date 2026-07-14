# -*- coding: utf-8 -*-
"""Ejecución REAL de órdenes contra Binance Futures TESTNET (regla usuario 14
jul: "que operen como si fueran reales, sin meter dinero real").

Solo se usa cuando MDT_MODO=testnet (mdt_config.py); en 'observacion' (default)
nada de este módulo se llama y el bot se comporta exactamente igual que antes.

Diseño (a propósito conservador): la decisión de CUÁNDO entrar/salir la sigue
dando mdt_gestion.gestionar() sobre velas reales — la misma que ya se validó
toda la sesión. Este módulo no decide nada de estrategia: solo REPRODUCE esa
decisión con órdenes reales en el testnet (firma, redondeo de cantidad/precio,
rate limits, rechazos del exchange) y lleva la cuenta virtual en dólares.

Sizing: arriesga RIESGO_CUENTA_PCT del balance virtual ACTUAL (compone) en
cada gatillo nuevo — cantidad = (balance * riesgo%) / distancia_al_SL.
"""
import hashlib
import hmac
import logging
import os
import time
import urllib.parse

import requests

from mdt_config import BALANCE_VIRTUAL_INICIAL, RIESGO_CUENTA_PCT

log = logging.getLogger('mdt.ejecutor')

BASE_URL = "https://testnet.binancefuture.com"
TIMEOUT = 10

API_KEY = os.environ.get('MDT_BINANCE_TESTNET_KEY', '')
API_SECRET = os.environ.get('MDT_BINANCE_TESTNET_SECRET', '').encode()

_info_simbolo_cache = {}


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
    """Balance USDT real del testnet (informativo, para cruzar contra la
    cuenta virtual — NO es lo que se usa para dimensionar posiciones)."""
    data = _request('GET', '/fapi/v2/balance', firmado=True)
    for b in data:
        if b['asset'] == 'USDT':
            return float(b['availableBalance'])
    return None


def calcular_cantidad(symbol, entrada, sl, balance_virtual):
    """Cantidad (en el activo base) para arriesgar RIESGO_CUENTA_PCT del
    balance virtual dado, según distancia al SL. Redondeada al step del symbol."""
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


def abrir_posicion(symbol, lado, entrada, sl, tp, balance_virtual):
    """Coloca ENTRADA a mercado + SL + TP reales en el testnet. Devuelve
    {'cantidad', 'order_id_entrada', 'order_id_sl', 'order_id_tp'}."""
    cantidad = calcular_cantidad(symbol, entrada, sl, balance_virtual)
    info = info_simbolo(symbol)
    sl_r = _redondear(sl, info['price_step'], info['price_precision'])
    tp_r = _redondear(tp, info['price_step'], info['price_precision'])
    cierre = 'SELL' if lado == 'BUY' else 'BUY'

    orden_entrada = _request('POST', '/fapi/v1/order', {
        'symbol': symbol, 'side': lado, 'type': 'MARKET', 'quantity': cantidad,
    })
    log.info("testnet %s: ENTRADA %s %s qty=%s -> orderId=%s", symbol, lado,
             entrada, cantidad, orden_entrada.get('orderId'))

    orden_sl = _request('POST', '/fapi/v1/order', {
        'symbol': symbol, 'side': cierre, 'type': 'STOP_MARKET',
        'stopPrice': sl_r, 'quantity': cantidad, 'reduceOnly': 'true',
    })
    orden_tp = _request('POST', '/fapi/v1/order', {
        'symbol': symbol, 'side': cierre, 'type': 'TAKE_PROFIT_MARKET',
        'stopPrice': tp_r, 'quantity': cantidad, 'reduceOnly': 'true',
    })
    return {'cantidad': cantidad,
            'order_id_entrada': orden_entrada.get('orderId'),
            'order_id_sl': orden_sl.get('orderId'),
            'order_id_tp': orden_tp.get('orderId')}


def mover_stop(symbol, lado, cantidad, order_id_viejo, nuevo_stop):
    """Cancela el SL viejo y coloca uno nuevo (ej. a breakeven tras el parcial)."""
    info = info_simbolo(symbol)
    stop_r = _redondear(nuevo_stop, info['price_step'], info['price_precision'])
    cierre = 'SELL' if lado == 'BUY' else 'BUY'
    if order_id_viejo is not None:
        try:
            _request('DELETE', '/fapi/v1/order', {'symbol': symbol, 'orderId': order_id_viejo})
        except ErrorEjecucion:
            log.warning("no se pudo cancelar SL viejo %s (%s): puede que ya haya llenado",
                       order_id_viejo, symbol)
    orden = _request('POST', '/fapi/v1/order', {
        'symbol': symbol, 'side': cierre, 'type': 'STOP_MARKET',
        'stopPrice': stop_r, 'quantity': cantidad, 'reduceOnly': 'true',
    })
    return orden.get('orderId')


def cerrar_parcial(symbol, lado, cantidad_parcial):
    """Cierra la mitad de la posición a mercado (Secc 20: parcial obligatorio)."""
    cierre = 'SELL' if lado == 'BUY' else 'BUY'
    info = info_simbolo(symbol)
    cantidad_parcial = _redondear(cantidad_parcial, info['qty_step'], info['qty_precision'])
    if cantidad_parcial <= 0:
        return None
    orden = _request('POST', '/fapi/v1/order', {
        'symbol': symbol, 'side': cierre, 'type': 'MARKET',
        'quantity': cantidad_parcial, 'reduceOnly': 'true',
    })
    return orden.get('orderId')


def cancelar_todas(symbol):
    """Cancela cualquier orden abierta del símbolo (limpieza al cerrar del todo)."""
    try:
        _request('DELETE', '/fapi/v1/allOpenOrders', {'symbol': symbol})
    except ErrorEjecucion:
        log.warning("no se pudieron cancelar las órdenes abiertas de %s", symbol)
