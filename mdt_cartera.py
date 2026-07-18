# -*- coding: utf-8 -*-
"""Vista de CONJUNTO de la cuenta del testnet: posiciones, cobertura, patrimonio,
P&L real y las maniobras de cartera (red de seguridad, cerrar todo).

Capas (auditoría 16 jul):
  mdt_binance_api.py  firma + request + info del símbolo + redondeo
  mdt_ejecutor.py     las órdenes (entrada, stops algo, parcial)
  mdt_cartera.py      <- este: lo que ve y protege el CONJUNTO
"""
import logging
import time

from mdt_binance_api import ErrorEjecucion, info_simbolo, redondear, request
from mdt_ejecutor import _algo_stop, cancelar_ordenes, cerrar_a_mercado

log = logging.getLogger('mdt.cartera')


# ---------------------------------------------------------------------------
# Vista
# ---------------------------------------------------------------------------
def posiciones(symbol):
    """Posiciones abiertas del símbolo: [{side, amt(con signo), entry, mark, upnl}]."""
    out = []
    for p in request('GET', '/fapi/v2/positionRisk', {'symbol': symbol}):
        amt = float(p.get('positionAmt', 0))
        if amt == 0:
            continue
        out.append({'side': p['positionSide'], 'amt': amt,
                    'entry': float(p['entryPrice']), 'mark': float(p['markPrice']),
                    'upnl': float(p['unRealizedProfit'])})
    return out


def cobertura_algos(symbol):
    """Por lado, cuánta cantidad cubren los STOP y los TP puestos, y el TP de
    referencia. Devuelve {'LONG': {...}, 'SHORT': {...}}."""
    cob = {'LONG': {'sl': 0.0, 'tp': 0.0, 'tp_px': None},
           'SHORT': {'sl': 0.0, 'tp': 0.0, 'tp_px': None}}
    for a in request('GET', '/fapi/v1/openAlgoOrders', {'symbol': symbol}):
        ps, q = a.get('positionSide'), float(a.get('quantity', 0))
        if ps not in cob:
            continue
        if a['orderType'] == 'STOP_MARKET':
            cob[ps]['sl'] += q
        elif a['orderType'] == 'TAKE_PROFIT_MARKET':
            cob[ps]['tp'] += q
            cob[ps]['tp_px'] = float(a['triggerPrice'])
    return cob


def equity_real():
    """PATRIMONIO de la cuenta = efectivo + flotante de las posiciones abiertas
    (regla usuario 15 jul: "el 0.1% de la cuenta NETA"). Es lo correcto para
    dimensionar: el disponible baja con el margen bloqueado y encogería el riesgo
    artificialmente cuando hay posiciones vivas."""
    acc = request('GET', '/fapi/v2/account', {})
    return float(acc['totalWalletBalance']) + float(acc['totalUnrealizedProfit'])


def balance_real(symbol=None):
    """La CUENTA NETA (patrimonio). El bot usa ESTE para dimensionar y reportar."""
    return equity_real()


def pnl_realizado(symbol, desde_ms, hasta_ms=None):
    """P&L REAL según el exchange en la ventana [desde_ms, hasta_ms]: suma de
    realizedPnl menos comisiones de los trades del símbolo.

    OJO — atribución con posiciones apiladas: cuando un stop condicional se
    dispara, Binance crea una orden nueva cuyo orderId no conocíamos, así que se
    suma por VENTANA TEMPORAL. Con varias del mismo lado abiertas a la vez, el
    reparto es aproximado; la verdad de la CUENTA la da siempre el balance real."""
    params = {'symbol': symbol, 'startTime': int(desde_ms), 'limit': 1000}
    if hasta_ms:
        params['endTime'] = int(hasta_ms)
    trades = request('GET', '/fapi/v1/userTrades', params)
    pnl = comision = 0.0
    for t in trades:
        pnl += float(t.get('realizedPnl', 0) or 0)
        comision += float(t.get('commission', 0) or 0)
    return {'pnl': pnl - comision, 'bruto': pnl, 'comision': comision,
            'n_trades': len(trades)}


# ---------------------------------------------------------------------------
# Maniobras de conjunto
# ---------------------------------------------------------------------------
def cerrar_todo(symbol):
    """Cierra TODAS las posiciones del símbolo a mercado y cancela sus algos.
    Devuelve el P&L realizado por la maniobra."""
    inicio = int(time.time() * 1000) - 500
    for a in request('GET', '/fapi/v1/openAlgoOrders', {'symbol': symbol}):
        cancelar_ordenes(symbol, [a.get('algoId')])
    for p in posiciones(symbol):
        lado_cierre = 'SELL' if p['amt'] > 0 else 'BUY'
        try:
            request('POST', '/fapi/v1/order', {
                'symbol': symbol, 'side': lado_cierre, 'positionSide': p['side'],
                'type': 'MARKET', 'quantity': abs(p['amt'])})
        except ErrorEjecucion:
            log.exception("cerrar_todo: no se pudo cerrar %s", p['side'])
    time.sleep(1)
    return pnl_realizado(symbol, inicio, int(time.time() * 1000))


def _algos_de_lado(symbol, lado):
    """STOP y TP abiertos de un lado (para la red de seguridad)."""
    sl, tp = [], []
    for a in request('GET', '/fapi/v1/openAlgoOrders', {'symbol': symbol}):
        if a.get('positionSide') != lado:
            continue
        (sl if a['orderType'] == 'STOP_MARKET' else tp).append(a)
    return sl, tp


def proteger_descubierto(symbol, stop_pct=0.005):
    """RED DE SEGURIDAD, cada ciclo: los stops/TP deben igualar la posición.
      - Si FALTA cobertura (posición sin stop): pone un stop de emergencia (o
        cierra a mercado si ese stop se dispararía ya). Bug del parcial 15 jul.
      - Si SOBRA (huérfanos de operaciones ya cerradas por su TP): ajusta la
        cobertura al tamaño exacto (regla usuario 15 jul: "hay que cerrarlos").
    Devuelve la lista de acciones tomadas."""
    info = info_simbolo(symbol)
    paso = float(info['qty_step'])
    acciones = []
    lados_con_pos = set()

    for p in posiciones(symbol):
        lado = p['side']
        lados_con_pos.add(lado)
        cob = cobertura_algos(symbol).get(lado, {})
        neto = abs(p['amt'])

        # POLVO de redondeo (p.ej. 0.49 con parcial de 0.24+0.24 deja 0.01): no
        # se le puede poner stop útil y queda flotando para siempre — se barre.
        if neto <= paso * 1.01:
            try:
                cerrar_a_mercado(symbol, 'BUY' if lado == 'LONG' else 'SELL', neto, lado)
                acciones.append({'side': lado, 'qty': neto, 'polvo_cerrado': True})
                log.info("cartera: polvo %s %s cerrado", lado, neto)
            except ErrorEjecucion:
                log.exception("cartera: no se pudo cerrar el polvo %s", lado)
            continue

        descubierto = neto - cob.get('sl', 0.0)

        if descubierto > paso:                       # FALTA stop -> proteger
            qty = redondear(descubierto, paso, info['qty_precision'])
            if lado == 'LONG':
                trigger = redondear(p['mark'] * (1 - stop_pct), info['price_step'], info['price_precision'])
                cierre = 'SELL'
            else:
                trigger = redondear(p['mark'] * (1 + stop_pct), info['price_step'], info['price_precision'])
                cierre = 'BUY'
            try:
                aid = _algo_stop(symbol, cierre, lado, 'STOP_MARKET', trigger, qty)
                acciones.append({'side': lado, 'qty': qty, 'trigger': trigger, 'algoId': aid})
                log.warning("testnet: RED %s %s BNB sin stop -> STOP @ %s", lado, qty, trigger)
            except ErrorEjecucion:
                log.exception("red: stop falló, cierro %s a mercado", qty)
                cerrar_a_mercado(symbol, 'BUY' if lado == 'LONG' else 'SELL', qty, lado)
                acciones.append({'side': lado, 'qty': qty, 'cerrado_a_mercado': True})
        elif -descubierto > paso:                    # SOBRAN stops -> ajustar
            n = _ajustar_cobertura(symbol, lado, neto, info)
            if n:
                acciones.append({'side': lado, 'huerfanos_ajustados': n})

    # Lados SIN posición pero con algos colgando (todo cerrado): cancelar todo
    for lado in ('LONG', 'SHORT'):
        if lado in lados_con_pos:
            continue
        sl, tp = _algos_de_lado(symbol, lado)
        colgados = sl + tp
        if colgados:
            cancelar_ordenes(symbol, [a['algoId'] for a in colgados])
            acciones.append({'side': lado, 'huerfanos_cancelados': len(colgados)})
    return acciones


def _ajustar_cobertura(symbol, lado, neto, info):
    """Deja los STOP (y TP) del lado sumando EXACTAMENTE la posición neta. Recorre
    las órdenes de la más protectora a la menos: las que caben se conservan, la que
    excede se recorta (cancelar + recolocar por lo que falta a su mismo trigger), y
    las que sobran enteras se cancelan. Conserva los stops más CERCANOS al precio
    (los que cortan antes la pérdida)."""
    paso = float(info['qty_step'])
    cierre = 'SELL' if lado == 'LONG' else 'BUY'
    n = 0
    for tipo in ('STOP_MARKET', 'TAKE_PROFIT_MARKET'):
        vivos = [a for a in request('GET', '/fapi/v1/openAlgoOrders', {'symbol': symbol})
                 if a.get('positionSide') == lado and a['orderType'] == tipo]
        # el más protector primero: STOP más alto en LONG (corta antes), y para el
        # TP el más bajo en LONG (se cobra antes) — reflejado en SHORT
        rev = (tipo == 'STOP_MARKET') == (lado == 'LONG')
        vivos.sort(key=lambda a: float(a['triggerPrice']), reverse=rev)
        acum = 0.0
        for a in vivos:
            q = float(a['quantity'])
            if acum >= neto - paso:                  # ya cubierto: sobra entero
                cancelar_ordenes(symbol, [a['algoId']]); n += 1
            elif acum + q > neto + paso:             # excede: recortar al tamaño justo
                falta = redondear(neto - acum, paso, info['qty_precision'])
                cancelar_ordenes(symbol, [a['algoId']]); n += 1
                if falta > 0:
                    try:
                        _algo_stop(symbol, cierre, lado, tipo,
                                   float(a['triggerPrice']), falta)
                    except ErrorEjecucion:
                        log.exception("ajuste: no se pudo recolocar %s %s", tipo, falta)
                acum = neto
            else:
                acum += q
    return n
