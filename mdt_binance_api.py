# -*- coding: utf-8 -*-
"""Transporte con Binance Futures TESTNET: firma HMAC, petición, precisión.

Capa más baja de la ejecución (auditoría 16 jul: mdt_ejecutor mezclaba 4 trabajos
en 488 líneas). Aquí NO hay decisiones: solo hablar con el exchange.

  mdt_binance_api.py  <- este: firma + request + info del símbolo + redondeo
  mdt_ejecutor.py     órdenes (entrada, stops algo, parcial, cancelar)
  mdt_cartera.py      vista de conjunto (posiciones, cobertura, red de seguridad)
"""
import hashlib
import hmac
import logging
import os
import time
import urllib.parse

import requests

log = logging.getLogger('mdt.api')

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


def request(method, path, params=None, firmado=True):
    if not API_KEY or not API_SECRET:
        raise ErrorEjecucion("MDT_BINANCE_TESTNET_KEY/SECRET vacíos: no se puede operar en testnet.")
    params = dict(params or {})
    headers = {'X-MBX-APIKEY': API_KEY}
    try:
        if firmado:
            params['timestamp'] = int(time.time() * 1000)
            params['recvWindow'] = 5000
            url = f"{BASE_URL}{path}?{_firmar(params)}"
        else:
            url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}" if params else f"{BASE_URL}{path}"
        r = requests.request(method, url, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise ErrorEjecucion(f"{method} {path}: fallo de red — {e}") from e
    if r.status_code != 200:
        raise ErrorEjecucion(f"{method} {path} -> {r.status_code}: {r.text}")
    return r.json()


def info_simbolo(symbol):
    """Precisión de cantidad/precio del símbolo (exchangeInfo, público, cacheado)."""
    if symbol in _info_simbolo_cache:
        return _info_simbolo_cache[symbol]
    data = request('GET', '/fapi/v1/exchangeInfo', firmado=False)
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


def redondear(valor, paso, precision):
    if not paso:
        return round(valor, precision)
    pasos = round(valor / paso)
    return round(pasos * paso, precision)
