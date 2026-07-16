# -*- coding: utf-8 -*-
"""Órdenes REALES contra Binance Futures TESTNET (regla usuario 14 jul: "que
operen como si fueran reales, sin meter dinero real").

Solo se usa cuando MDT_MODO=testnet; en 'observacion' (default) nada de este
módulo se llama. Este módulo no decide estrategia: REPRODUCE las decisiones de
mdt_gestion con órdenes reales y devuelve lo que REALMENTE pasó.

Capas (auditoría 16 jul — antes todo vivía aquí, 488 líneas):
  mdt_binance_api.py  firma + request + info del símbolo + redondeo
  mdt_ejecutor.py     <- este: las órdenes (entrada, stops algo, parcial)
  mdt_cartera.py      vista de conjunto (posiciones, cobertura, red, P&L)

TRES COSAS QUE HAY QUE ENTENDER (auditoría 14 jul):

1. MODO HEDGE OBLIGATORIO. En one-way Binance tiene UNA posición neta por
   símbolo: una venta a mercado estando largo NO abre un corto — REDUCE el largo.
   Con hedge conviven LONG y SHORT y cada orden dice su positionSide. En hedge,
   las órdenes de cierre NO llevan reduceOnly (Binance las rechaza).

2. LAS CONDICIONALES VAN A LA ALGO API. Desde el 9-dic-2025 Binance migró
   STOP_MARKET/TAKE_PROFIT a /fapi/v1/algoOrder (el endpoint clásico las rechaza
   con -4120). triggerPrice en vez de stopPrice; se cancelan por algoId.

3. LAS ÓRDENES SE CANCELAN UNA A UNA (cancelar_ordenes): cancelarlo todo borraba
   los SL/TP de las demás operaciones vivas del mismo símbolo.

Sizing: RIESGO_USD fijo si está configurado; si no, RIESGO_CUENTA_PCT del
patrimonio neto (la "cuenta neta" del operador, 15 jul).
"""
import logging
import time

from mdt_binance_api import (BASE_URL, ErrorEjecucion, info_simbolo,  # noqa: F401
                             redondear, request)
from mdt_config import RIESGO_CUENTA_PCT, RIESGO_USD

log = logging.getLogger('mdt.ejecutor')

_hedge_ok = False          # se comprueba una vez por proceso


class StopDispararia(ErrorEjecucion):
    """El stop pedido se dispararía de inmediato: el precio ya cruzó el nivel."""


# ---------------------------------------------------------------------------
# Modo hedge
# ---------------------------------------------------------------------------
def asegurar_modo_hedge():
    """Activa dualSidePosition si no lo estaba. Binance solo deja cambiarlo con
    la cuenta SIN posiciones ni órdenes abiertas."""
    global _hedge_ok
    if _hedge_ok:
        return
    estado = request('GET', '/fapi/v1/positionSide/dual')
    if estado.get('dualSidePosition'):
        _hedge_ok = True
        return
    try:
        request('POST', '/fapi/v1/positionSide/dual', {'dualSidePosition': 'true'})
    except ErrorEjecucion as e:
        raise ErrorEjecucion(
            "La cuenta del testnet está en modo ONE-WAY y no se pudo cambiar a HEDGE "
            "(Binance solo lo permite sin posiciones ni órdenes abiertas). En one-way, "
            "una venta estando largo REDUCE el largo en vez de abrir un corto: las "
            f"operaciones del bot no se reflejarían. Cierra todo y reintenta. [{e}]") from e
    _hedge_ok = True
    log.info("testnet: modo HEDGE activado")


def _position_side(lado):
    return 'LONG' if lado == 'BUY' else 'SHORT'


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------
def calcular_cantidad(symbol, entrada, sl, balance_virtual):
    """Cantidad (en el activo base) para arriesgar lo configurado, según la
    distancia al SL. Redondeada al step del símbolo."""
    riesgo_precio = abs(entrada - sl)
    if riesgo_precio <= 0:
        raise ErrorEjecucion("Riesgo en precio es cero: no se puede dimensionar.")
    # Monto fijo en dólares si está configurado; si no, % de la cuenta neta.
    riesgo_dolares = RIESGO_USD if RIESGO_USD > 0 else balance_virtual * RIESGO_CUENTA_PCT
    cantidad = riesgo_dolares / riesgo_precio
    info = info_simbolo(symbol)
    cantidad = redondear(cantidad, info['qty_step'], info['qty_precision'])
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
        o = request('GET', '/fapi/v1/order', {'symbol': symbol, 'orderId': order_id})
        precio = float(o.get('avgPrice') or 0)
        if o.get('status') == 'FILLED' and precio > 0:
            return precio
        time.sleep(0.4 * (i + 1))
    return None


# ---------------------------------------------------------------------------
# Órdenes
# ---------------------------------------------------------------------------
def abrir_posicion(symbol, lado, entrada, sl, tp, balance_virtual):
    """ENTRADA a mercado + SL + TP reales en el testnet (modo hedge).

    Devuelve {'cantidad', 'position_side', 'entrada_real', 'inicio_ms',
    'order_id_entrada', 'algo_sl', 'algo_tp', 'algos'}.
    """
    asegurar_modo_hedge()
    cantidad = calcular_cantidad(symbol, entrada, sl, balance_virtual)
    info = info_simbolo(symbol)
    sl_r = redondear(sl, info['price_step'], info['price_precision'])
    tp_r = redondear(tp, info['price_step'], info['price_precision'])
    ps = _position_side(lado)
    cierre = 'SELL' if lado == 'BUY' else 'BUY'
    inicio_ms = int(time.time() * 1000) - 1000

    orden_entrada = request('POST', '/fapi/v1/order', {
        'symbol': symbol, 'side': lado, 'positionSide': ps,
        'type': 'MARKET', 'quantity': cantidad,
    })
    id_entrada = orden_entrada.get('orderId')
    entrada_real = _precio_llenado(symbol, id_entrada)
    log.info("testnet %s: ENTRADA %s qty=%s -> orderId=%s llenó en %s (teórica %s)",
             symbol, lado, cantidad, id_entrada, entrada_real, entrada)

    # SL y TP condicionales -> Algo API. Sin esto la entrada quedaba SIN STOP
    # (posición desnuda, el bug del 14 jul).
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
    Order API. Devuelve el algoId."""
    o = request('POST', '/fapi/v1/algoOrder', {
        'symbol': symbol, 'side': side, 'positionSide': position_side,
        'algoType': 'CONDITIONAL', 'type': tipo,
        'triggerPrice': trigger, 'quantity': cantidad,
    })
    return o.get('algoId')


def mover_stop(symbol, lado, cantidad, algo_viejo, nuevo_stop, position_side):
    """Cancela el SL viejo (algo) y coloca uno nuevo (ej. a breakeven tras el
    parcial). Devuelve el algoId nuevo.

    Si el nuevo stop se dispararía ya (el precio volvió al nivel antes de poder
    moverlo, -2021), avisa con StopDispararia para que quien llama cierre a
    mercado en vez de dejar la posición sin stop."""
    info = info_simbolo(symbol)
    stop_r = redondear(nuevo_stop, info['price_step'], info['price_precision'])
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
    """Cierra parte de la posición a mercado (Secc 20: parcial obligatorio)."""
    cierre = 'SELL' if lado == 'BUY' else 'BUY'
    info = info_simbolo(symbol)
    cantidad_parcial = redondear(cantidad_parcial, info['qty_step'], info['qty_precision'])
    if cantidad_parcial <= 0:
        return None
    orden = request('POST', '/fapi/v1/order', {
        'symbol': symbol, 'side': cierre, 'positionSide': position_side,
        'type': 'MARKET', 'quantity': cantidad_parcial,
    })
    return orden.get('orderId')


def cerrar_a_mercado(symbol, lado, cantidad, position_side):
    """Cierra lo que quede de la posición a mercado."""
    return cerrar_parcial(symbol, lado, cantidad, position_side)


def cancelar_ordenes(symbol, algo_ids):
    """Cancela SOLO las órdenes condicionales (SL/TP) indicadas, por su algoId.
    NUNCA todas: eso borraba los SL/TP de las demás operaciones vivas del mismo
    símbolo (auditoría 14 jul)."""
    for aid in algo_ids or []:
        try:
            request('DELETE', '/fapi/v1/algoOrder', {'symbol': symbol, 'algoId': aid})
        except ErrorEjecucion:
            # Lo normal: ya se disparó o ya no existe. No es un fallo.
            log.debug("testnet: el algo %s de %s ya no estaba abierto", aid, symbol)


def algos_abiertos(symbol, algo_ids):
    """De una lista de algoIds, cuáles siguen ABIERTOS en el exchange. El que
    desaparece es que se DISPARÓ (cerró su cantidad de la posición). Esta es la
    verdad del cierre: el exchange, no la lectura de velas del bot."""
    if not algo_ids:
        return set()
    abiertos = request('GET', '/fapi/v1/openAlgoOrders', {'symbol': symbol})
    vivos = {str(a.get('algoId')) for a in abiertos}
    return {a for a in algo_ids if str(a) in vivos}
