# -*- coding: utf-8 -*-
"""Espejo de las operaciones en Binance Futures TESTNET (auditoría 16 jul:
vivía dentro de mdt_ops, 422 líneas mezclando la gestión teórica con esta capa).

Qué hace cada pieza, en el orden del ciclo del bot:
  red_seguridad()      ninguna posición sin stop; cobertura = posición exacta
  objetivo_conjunto()  cierra TODO cuando el flotante iguala la meta de los TP
  reconciliar()        el cierre por SL/TP lo decide el EXCHANGE, no las velas
  abrir()              entrada + SL + TP nativos por cada gatillo nuevo
  parcial()            Secc 20: media fuera + stop a breakeven (sin quedar desnuda)

El candado Regla 3 NO llega hasta aquí: vigila la PUERTA (mdt_ops) — una posición
abierta ya solo depende de su TP y su stop loss (regla usuario 16 jul).
"""
import logging
import time

import mdt_cartera
import mdt_ejecutor
import mdt_telegram
from mdt_config import RIESGO_CUENTA_PCT
from mdt_gestion import FASES_CERRADAS, tp_cercano

log = logging.getLogger('mdt.testnet')


def _vivas_del_lado(ops, k_nueva, lado):
    """Operaciones de ese lado ya colocadas en el exchange y sin cerrar."""
    return [k for k, op in ops.items()
            if k != k_nueva and op.get('testnet') and op.get('lado') == lado
            and op.get('fase') not in FASES_CERRADAS]


def abrir(sym, k, op, ops, cuenta, chat_id):
    """Coloca en el testnet la entrada+SL+TP reales que espejan este gatillo
    (regla usuario 14 jul). Nunca tumba el registro del HECHO si falla.

    TODAS las señales van al exchange (decisión del usuario, 14 jul). Binance
    funde las del MISMO lado en una posición (entrada promediada, margen y
    liquidación compartidos), pero cada señal conserva SU cantidad, SU stop y SU
    take profit."""
    hermanas = _vivas_del_lado(ops, k, op['lado'])
    tp = tp_cercano(op['lado'], op['tp_zona'])
    try:
        r = mdt_ejecutor.abrir_posicion(sym, op['lado'], op['entrada'], op['sl'],
                                        tp, cuenta['balance'])
    except mdt_ejecutor.ErrorEjecucion as e:
        log.exception("testnet: fallo abriendo %s", k)
        mdt_telegram.enviar(chat_id, f"🧪❌ {sym} | TESTNET: no se pudo abrir {k}\n{e}")
        return
    op['testnet'] = r
    real = r.get('entrada_real')
    desliz = (f"\n  llenó en {real:.4f} (deslizamiento {real - op['entrada']:+.4f})"
              if real else "")
    nocional = r['cantidad'] * (real or op['entrada'])
    apilada = (f"\n  ⚠ ya hay {len(hermanas)} {op['lado']} viva(s): Binance las funde en "
               f"UNA posición (margen y liquidación compartidos)" if hermanas else "")
    mdt_telegram.enviar(chat_id,
        f"🧪📌 {sym} | TESTNET: orden real colocada ({op['patron']})\n"
        f"  {op['lado']} qty={r['cantidad']} @ {op['entrada']:.4f} | "
        f"SL {op['sl']:.4f} | TP {tp:.4f}{desliz}\n"
        f"  nocional ${nocional:,.0f} | riesgo ${cuenta['balance'] * RIESGO_CUENTA_PCT:.2f} "
        f"({RIESGO_CUENTA_PCT:.2%} de ${cuenta['balance']:.2f}){apilada}")


def parcial(sym, k, op, s, chat_id):
    """Espeja el parcial obligatorio (Secc 20): media fuera + SL real a breakeven.
    GARANTÍA: la mitad viva NUNCA queda sin stop (bug del 15 jul) — si recolocar
    el SL falla, se cierra a mercado."""
    t = op.get('testnet')
    if t is None:
        return
    media = t['cantidad'] / 2.0
    cierre = 'SELL' if op['lado'] == 'BUY' else 'BUY'
    info = mdt_ejecutor.info_simbolo(sym)
    be = mdt_ejecutor.redondear(op['entrada'], info['price_step'], info['price_precision'])
    try:
        mdt_ejecutor.cerrar_parcial(sym, op['lado'], media, t['position_side'])
        mdt_ejecutor.cancelar_ordenes(sym, [a for a in (t.get('algo_sl'), t.get('algo_tp')) if a])
        t['cantidad_viva'] = media
    except mdt_ejecutor.ErrorEjecucion as e:
        log.exception("testnet: fallo tomando el parcial de %s", k)
        mdt_telegram.enviar(chat_id, f"🧪❌ {sym} | TESTNET: fallo en parcial de {k}\n{e}")
        return

    try:
        t['algo_sl'] = mdt_ejecutor.mover_stop(sym, op['lado'], media, None, be,
                                               t['position_side'])
    except (mdt_ejecutor.StopDispararia, mdt_ejecutor.ErrorEjecucion):
        mdt_ejecutor.cerrar_a_mercado(sym, op['lado'], media, t['position_side'])
        t['algo_sl'] = t['algo_tp'] = None
        t['algos'] = []
        t['cantidad_viva'] = 0.0
        mdt_telegram.enviar(chat_id, f"🧪💰 {sym} | TESTNET: parcial hecho; el precio ya "
                                     f"tocaba breakeven, cerré el resto a mercado.")
        return
    try:
        tp_r = mdt_ejecutor.redondear(tp_cercano(op['lado'], op['tp_zona']),
                                      info['price_step'], info['price_precision'])
        t['algo_tp'] = mdt_ejecutor._algo_stop(sym, cierre, t['position_side'],
                                               'TAKE_PROFIT_MARKET', tp_r, media)
    except mdt_ejecutor.ErrorEjecucion:
        t['algo_tp'] = None   # sin TP, pero CON stop: la posición está protegida
    t['algos'] = [a for a in (t.get('algo_sl'), t.get('algo_tp')) if a]
    mdt_telegram.enviar(chat_id, f"🧪💰 {sym} | TESTNET: parcial real ejecutado, "
                                 f"SL movido a breakeven ({op['entrada']:.4f})")


def red_seguridad(sym, chat_id):
    """Cada ciclo: cobertura = posición exacta (nada desnudo, cero huérfanos)."""
    try:
        acciones = mdt_cartera.proteger_descubierto(sym)
    except Exception:  # noqa: BLE001
        log.exception("red de seguridad testnet")
        return
    for x in acciones:
        if x.get('cerrado_a_mercado'):
            mdt_telegram.enviar(chat_id, f"🧪🛟 {sym} | RED DE SEGURIDAD: {x['qty']} "
                                         f"{x['side']} sin stop; cerrados a mercado.")
        elif x.get('trigger'):
            mdt_telegram.enviar(chat_id, f"🧪🛟 {sym} | RED DE SEGURIDAD: {x['qty']} "
                                         f"{x['side']} estaban SIN STOP; puse uno de "
                                         f"emergencia @ {x['trigger']}.")
        else:
            log.info("red: %s", x)   # ajuste de huérfanos: al log, no al chat


def objetivo_conjunto(sym, ops, cuenta, chat_id):
    """GESTIÓN DE CONJUNTO (regla usuario 15 jul): cerrar TODAS las posiciones de
    golpe cuando el flotante conjunto alcanza lo que se ganaría si cada una
    llegara a su TP (los TP individuales no pueden cobrarse todos: unos arriba,
    otros abajo). Devuelve True si cerró todo."""
    pos = mdt_cartera.posiciones(sym)
    if not pos:
        return False
    flotante = sum(p['upnl'] for p in pos)
    if flotante <= 0:
        return False   # nunca se cierra el conjunto en pérdida

    cob = mdt_cartera.cobertura_algos(sym)
    objetivo = 0.0
    for p in pos:
        tp_px = cob.get(p['side'], {}).get('tp_px')
        if tp_px is None:
            return False   # falta algún TP: no hay meta completa, no cerrar
        objetivo += (tp_px - p['entry']) * p['amt']   # amt con signo
    if objetivo <= 0 or flotante < objetivo:
        return False

    real = mdt_cartera.cerrar_todo(sym)
    cuenta['balance'] = mdt_cartera.balance_real(sym)
    for k, o in ops.items():
        if o.get('testnet') and o.get('fase') not in FASES_CERRADAS:
            o['fase'] = 'TP'
            o['r_final'] = 0.0
    cuenta.setdefault('historial', []).append({
        'op': 'CIERRE_CONJUNTO', 'patron': 'objetivo', 'fase': 'TP',
        'pnl': round(real['pnl'], 2), 'balance': round(cuenta['balance'], 2),
        'hora': 'objetivo conjunto', 'real': True})
    mdt_telegram.enviar(chat_id,
        f"🎯🧪 {sym} | OBJETIVO CONJUNTO ALCANZADO: cerré TODO\n"
        f"  el flotante conjunto (+{flotante:.2f}) llegó a la meta de los TP (+{objetivo:.2f})\n"
        f"  realizado: {real['pnl']:+.2f} USD | balance ${cuenta['balance']:.2f}")
    return True


def reconciliar(sym, k, op, cuenta, chat_id):
    """El cierre lo decide el EXCHANGE, no la lectura de velas (corrección 15 jul).
    Si el SL de esta señal desapareció, cerró por stop; si el TP, por objetivo. El
    hermano que quede se cancela y se liquida el P&L real. Devuelve True si cerró."""
    t = op.get('testnet')
    if t is None:
        return False
    algo_sl, algo_tp = t.get('algo_sl'), t.get('algo_tp')
    activos = [a for a in (algo_sl, algo_tp) if a]
    if not activos:
        # Sin algos rastreados (p.ej. ambos dispararon en el mismo ciclo, o el
        # parcial cerró por breakeven y el polvo se barrió): si el exchange ya no
        # tiene posición de este lado, la operación TERMINÓ — sin esto quedaba
        # fantasma en PARCIAL para siempre (caso SELL|602.79, 18 jul).
        if t.get('cantidad_viva', t.get('cantidad', 0)) > 0:
            pos = mdt_cartera.posiciones(sym)
            if not any(p['side'] == t.get('position_side') for p in pos):
                _liquidar(sym, k, op, cuenta, chat_id, 'BE', t,
                          titulo="cerró en el exchange (posición ya plana)", icono='⚖️')
                return True
        return False
    vivos = {str(x) for x in mdt_ejecutor.algos_abiertos(sym, activos)}
    if all(str(a) in vivos for a in activos):
        return False   # ambos siguen puestos: la operación sigue viva

    sl_disparo = algo_sl and str(algo_sl) not in vivos
    fase = 'SL' if sl_disparo else 'TP'
    mdt_ejecutor.cancelar_ordenes(sym, [a for a in activos if str(a) in vivos])
    _liquidar(sym, k, op, cuenta, chat_id, fase, t,
              titulo=f"cerró por {fase} en el exchange",
              icono='🏁' if fase == 'TP' else '☠️')
    return True


def _liquidar(sym, k, op, cuenta, chat_id, fase, t, titulo, icono):
    """Marca la fase final, liquida el P&L real y avisa."""
    real = None
    if t is not None:
        try:
            real = mdt_cartera.pnl_realizado(sym, t['inicio_ms'], int(time.time() * 1000))
        except Exception:  # noqa: BLE001
            log.exception("testnet: P&L de %s", k)
    pnl = real['pnl'] if real else 0.0
    op['fase'] = fase
    op['r_final'] = pnl
    try:
        cuenta['balance'] = mdt_cartera.balance_real(sym)
    except Exception:  # noqa: BLE001
        pass
    cuenta.setdefault('historial', []).append({
        'op': k, 'patron': op['patron'], 'fase': fase, 'pnl': round(pnl, 2),
        'balance': round(cuenta['balance'], 2), 'hora': op['hora_gatillo'],
        'real': real is not None})
    detalle = (f"real {real['bruto']:+.2f} − {real['comision']:.2f} comisión = {pnl:+.2f} USD"
               if real else "sin datos del exchange")
    mdt_telegram.enviar(chat_id,
        f"{icono} {sym} | TESTNET: {k} {titulo}\n"
        f"  {detalle}\n  balance real de la cuenta: ${cuenta['balance']:.2f}")
