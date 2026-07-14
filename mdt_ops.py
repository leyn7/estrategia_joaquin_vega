# -*- coding: utf-8 -*-
"""Operaciones REALES del operador: gatillos ejecutados persistidos + gestión.

Por qué existen: la cadena de patrones es SIN ESTADO, y al re-parsear el
episodio con velas nuevas puede borrar del historial un gatillo que SÍ disparó
(caso real: el EE_GATILLO venta 590.28/SL 593.83 del 5 jul desapareció el 8 jul
cuando la Entrada Profunda re-leyó el episodio). Por eso, cuando un gatillo se
ejecuta, se guarda como un HECHO en estado_vivo.json con sus datos originales
(entrada, SL, TP) y se sigue con velas reales pase lo que pase con el re-parseo.
Sobrevive reinicios.

La caminata de gestión (Secc 20: parcial obligatorio si el objetivo supera 1:3,
mitad fuera + stop a breakeven) vive en mdt_gestion — la MISMA que usa el
backtest, para que ambos midan lo mismo.
"""
import logging

import pandas as pd

import mdt_telegram
from mdt_config import BALANCE_VIRTUAL_INICIAL, MAX_OPS_DIA, MDT_MODO, RIESGO_CUENTA_PCT
from mdt_data import to_cot
from mdt_estado import MAX_OPS_CERRADAS, get_klines_vivo, naive
from mdt_formato import hora_cot
from mdt_gestion import ESTADOS_EJECUTADOS, entrada_de_resultado, gestionar

log = logging.getLogger('mdt.ops')

FASES_CERRADAS = ('SL', 'BE', 'TP')


def op_de_escaneo(e):
    """Extrae los HECHOS de un gatillo ejecutado (o None): entrada, SL original,
    TP del ciclo y hora. La extracción vive en mdt_gestion (única fuente de
    verdad compartida con el escáner y el backtest)."""
    res = e['resultado']
    if res['estado'] not in ESTADOS_EJECUTADOS:
        return None
    hechos = entrada_de_resultado(res, e['lado'], e['rango'])
    tp = e.get('tp_zona')
    if hechos is None or tp is None:
        return None
    entrada, sl, hora = hechos
    return {'zona': e['zona'], 'lado': e['lado'], 'patron': res['estado'],
            'tf': e['tf_patron'], 'ancla': float(e['ancla']),
            'entrada': round(entrada, 4), 'sl': round(sl, 4),
            'tp_zona': [round(float(max(tp)), 4), round(float(min(tp)), 4)],
            'hora_gatillo': str(naive(hora))}


def seguir_operacion(sym, op):
    """Sigue la operación con velas reales desde su gatillo (gestión Secc 20)."""
    lado = op['lado']
    tp = max(op['tp_zona']) if lado == 'SELL' else min(op['tp_zona'])
    hora = pd.Timestamp(op['hora_gatillo'])
    df = get_klines_vivo(sym, op['tf'], hora.tz_localize('UTC'))
    velas = df[df['open_time'] > hora]
    return gestionar(velas, lado, op['entrada'], op['sl'], tp)


def texto_op_real(op, s):
    """Estado de una operación real (para el resumen y las alertas)."""
    accion = 'VENTA' if op['lado'] == 'SELL' else 'COMPRA'
    hora = hora_cot(pd.Timestamp(op['hora_gatillo']))
    txt = (f"{accion} {op['entrada']:.2f} ({op['patron']}, {hora})\n"
           f"  zona: {op['zona']} | SL original {op['sl']:.2f} | "
           f"TP {op['tp_zona'][0]:.2f}-{op['tp_zona'][1]:.2f} (1:{s['ratio']:.1f})")
    if s['fase'] == 'PARCIAL':
        txt += (f"\n  PARCIAL HECHO en {s['nivel_parcial']:.2f} "
                f"(+{s.get('r_asegurada', 0):.2f}R asegurada) -> STOP EN BREAKEVEN "
                f"{s['sl_actual']:.2f} | flotante total {s['r']:+.2f}R")
    elif s['fase'] == 'ABIERTA':
        extra = (f" | parcial (Secc 20) en {s['nivel_parcial']:.2f}"
                 if s['nivel_parcial'] is not None else "")
        txt += f"\n  ABIERTA: SL {s['sl_actual']:.2f}{extra} | flotante {s['r']:+.2f}R"
    else:
        cierre = {'SL': 'STOP LOSS', 'BE': 'BREAKEVEN (tras parcial)', 'TP': 'TP COMPLETO'}
        txt += f"\n  CERRADA por {cierre.get(s['fase'], s['fase'])}: {s['r']:+.2f}R"
    return txt


def _fecha_cot(ts):
    """Fecha (COT) de un instante. OJO: to_cot() ya hace el tz_localize('UTC'),
    así que hay que pasarle un timestamp NAIVE — pasarle uno con zona reventaba
    con 'Cannot localize tz-aware Timestamp' (bug encontrado al partir el bot)."""
    return str(to_cot(naive(ts)).date())


def _aviso_limite_diario(sym, ops):
    """Límite operativo diario (Secc 1): el bot no oculta hechos, pero avisa
    cuando los gatillos del día ya coparon el plan."""
    hoy = _fecha_cot(pd.Timestamp.now(tz='UTC'))
    del_dia = sum(1 for o in ops.values() if _fecha_cot(o['hora_gatillo']) == hoy)
    if del_dia > MAX_OPS_DIA:
        return (f"⚠️ {sym} | LÍMITE DIARIO (Secc 1): ya van {del_dia} gatillos "
                f"ejecutados hoy (máx {MAX_OPS_DIA}). No operar más por hoy.")
    return None


def _vivas_del_lado(ops, k_nueva, lado):
    """Operaciones de ese lado ya colocadas en el exchange y sin cerrar."""
    return [k for k, op in ops.items()
            if k != k_nueva and op.get('testnet') and op.get('lado') == lado
            and op.get('fase') not in FASES_CERRADAS]


def _testnet_abrir(sym, k, op, ops, cuenta, chat_id):
    """Coloca en el testnet la entrada+SL+TP reales que espejan este gatillo
    (regla usuario 14 jul). Nunca tumba el registro del HECHO si falla —
    solo avisa: la operación teórica sigue existiendo aunque el testnet falle.

    TODAS las señales van al exchange (decisión del usuario, 14 jul: "déjalo como
    está, a ver si se desploma la cuenta — ¿y si las que dejamos fuera son justo
    las que cierran en positivo?"). El bot opera cada señal por separado y así se
    prueba tal cual es.

    Binance funde las del MISMO lado en una sola posición (entrada promediada,
    margen y liquidación compartidos), pero cada señal conserva SU cantidad, SU
    stop y SU take profit, y el P&L se atribuye por orderId — así que la cuenta de
    cada operación sigue siendo exacta. Lo que se comparte es el riesgo de
    liquidación: si el mercado va en contra, caen juntas."""
    import mdt_ejecutor
    hermanas = _vivas_del_lado(ops, k, op['lado'])
    tp = max(op['tp_zona']) if op['lado'] == 'SELL' else min(op['tp_zona'])
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
    # El nocional dice la verdad de la exposición: con stops finos, una operación
    # de $10 de riesgo puede ser una posición de miles de dólares.
    nocional = r['cantidad'] * (real or op['entrada'])
    apilada = (f"\n  ⚠ ya hay {len(hermanas)} {op['lado']} viva(s): Binance las funde en "
               f"UNA posición (margen y liquidación compartidos)" if hermanas else "")
    mdt_telegram.enviar(chat_id,
        f"🧪📌 {sym} | TESTNET: orden real colocada ({op['patron']})\n"
        f"  {op['lado']} qty={r['cantidad']} @ {op['entrada']:.4f} | "
        f"SL {op['sl']:.4f} | TP {tp:.4f}{desliz}\n"
        f"  nocional ${nocional:,.0f} | riesgo ${cuenta['balance'] * RIESGO_CUENTA_PCT:.2f} "
        f"({RIESGO_CUENTA_PCT:.0%} de ${cuenta['balance']:.2f}){apilada}")


def _testnet_parcial(sym, k, op, s, chat_id):
    """Espeja el parcial obligatorio (Secc 20): cierra la mitad a mercado y
    mueve el SL real a breakeven."""
    import mdt_ejecutor
    t = op.get('testnet')
    if t is None:
        return
    try:
        media = t['cantidad'] / 2.0
        orden = mdt_ejecutor.cerrar_parcial(sym, op['lado'], media, t['position_side'])
        if orden:
            t.setdefault('ordenes', []).append(orden)
        t['order_id_sl'] = mdt_ejecutor.mover_stop(
            sym, op['lado'], media, t.get('order_id_sl'), op['entrada'], t['position_side'])
        t['ordenes'] = [o for o in t.get('ordenes', []) if o] + [t['order_id_sl']]
        t['cantidad_viva'] = media
    except mdt_ejecutor.ErrorEjecucion as e:
        log.exception("testnet: fallo en parcial de %s", k)
        mdt_telegram.enviar(chat_id, f"🧪❌ {sym} | TESTNET: fallo en parcial de {k}\n{e}")
        return
    mdt_telegram.enviar(chat_id, f"🧪💰 {sym} | TESTNET: parcial real ejecutado, "
                                 f"SL movido a breakeven ({op['entrada']:.4f})")


def _testnet_cerrar(sym, k, op, s, cuenta, chat_id):
    """Cierre final (SL/BE/TP): deja la posición plana, cancela SOLO las órdenes
    de ESTA operación, y liquida el balance con el P&L REAL del exchange.

    Dos correcciones de la auditoría (14 jul):
      - Antes cancelaba TODAS las órdenes del símbolo: se llevaba por delante los
        SL/TP de las otras operaciones vivas, dejándolas a pelo.
      - Antes liquidaba con la R teórica (balance × riesgo% × R). Ahora suma los
        realizedPnl menos comisiones de SUS trades: ahí sí se ven el deslizamiento
        y las comisiones, que es justo lo que el testnet debe enseñar.
    """
    import mdt_ejecutor
    t = op.get('testnet')
    if t is None:            # señal que no llegó al exchange (posición ocupada)
        return
    real = None
    try:
        # La gestión da la operación por cerrada según las velas; si el SL/TP del
        # exchange no ha saltado aún, se cierra a mercado para no dejar cola.
        viva = t.get('cantidad_viva', t['cantidad'])
        if s['fase'] in ('BE',) or s['fase'] not in ('SL', 'TP'):
            mdt_ejecutor.cerrar_a_mercado(sym, op['lado'], viva, t['position_side'])
        mdt_ejecutor.cancelar_ordenes(sym, t.get('ordenes'))
        real = mdt_ejecutor.pnl_realizado(sym, t.get('ordenes'), t['inicio_ms'])
    except Exception:  # noqa: BLE001 — la cuenta igual se liquida (con la teórica)
        log.exception("testnet: fallo cerrando %s", k)

    antes = cuenta['balance']
    if real is not None:
        pnl = real['pnl']
        detalle = (f"  real: {real['bruto']:+.2f} bruto − {real['comision']:.2f} "
                   f"comisión = {pnl:+.2f} USD")
    else:
        pnl = antes * RIESGO_CUENTA_PCT * s['r']    # respaldo si el exchange no responde
        detalle = f"  (sin datos del exchange: estimado teórico {pnl:+.2f} USD)"
    cuenta['balance'] = antes + pnl
    cuenta.setdefault('historial', []).append({
        'op': k, 'patron': op['patron'], 'fase': s['fase'], 'r': round(s['r'], 3),
        'pnl': round(pnl, 2), 'balance': round(cuenta['balance'], 2),
        'hora': op['hora_gatillo'], 'real': real is not None,
    })
    mdt_telegram.enviar(chat_id,
        f"🧪 {sym} | TESTNET: {k} cerrada por {s['fase']} ({s['r']:+.2f}R teórica)\n"
        f"{detalle}\n"
        f"  balance virtual ${cuenta['balance']:.2f} "
        f"(arrancó en ${BALANCE_VIRTUAL_INICIAL:.2f})")


def actualizar_operaciones(sym, resultado, mem, cuenta=None, chat_id=None):
    """Registra gatillos ejecutados nuevos y sigue los abiertos con velas reales.
    Devuelve los eventos de transición (registro/parcial/breakeven/SL/TP). Las
    operaciones son HECHOS: se notifican siempre, sin filtro de notificaciones.

    Si MDT_MODO='testnet' (regla usuario 14 jul) y se pasa `cuenta` (el dict
    estado['cuenta_testnet']), cada transición además coloca/gestiona órdenes
    REALES en Binance Futures Testnet — ver mdt_ejecutor.py. Esas notificaciones
    van SIEMPRE por Telegram (nunca se silencian: son hechos, aunque el testnet
    no sea dinero real)."""
    ops = mem.setdefault('operaciones', {})
    eventos = []
    testnet = MDT_MODO == 'testnet' and cuenta is not None

    # 1) Registrar gatillos ejecutados nuevos (dedup por lado|ancla|patrón|entrada)
    for e in resultado['escaneos']:
        if e['contexto']:
            continue
        op = op_de_escaneo(e)
        if op is None:
            continue
        k = f"{op['lado']}|{op['ancla']:.2f}|{op['patron']}|{op['entrada']:.2f}"
        if k not in ops:
            ops[k] = {**op, 'fase': None}
            aviso = _aviso_limite_diario(sym, ops)
            if aviso:
                eventos.append(aviso)
            if testnet:
                _testnet_abrir(sym, k, ops[k], ops, cuenta, chat_id)

    # 2) Seguir cada operación no cerrada
    for k, op in list(ops.items()):
        if op.get('fase') in FASES_CERRADAS:
            continue
        try:
            s = seguir_operacion(sym, op)
        except Exception:  # noqa: BLE001 — una operación rota no tumba el bucle
            log.exception("seguimiento de operación %s", k)
            continue
        if s is None:
            ops.pop(k)
            continue
        previa = op.get('fase')
        if s['fase'] != previa:
            icono = {'PARCIAL': '💰', 'SL': '☠️', 'BE': '⚖️', 'TP': '🏁'}.get(s['fase'], '📌')
            titulo = {'PARCIAL': 'PARCIAL TOCADO -> STOP A BREAKEVEN (Secc 20)',
                      'SL': 'STOP LOSS: operación cerrada',
                      'BE': 'BREAKEVEN tocado: cerrada con lo asegurado',
                      'TP': 'TP COMPLETO'}.get(s['fase'], 'OPERACIÓN REGISTRADA')
            if previa is None and s['fase'] == 'ABIERTA':
                titulo = 'OPERACIÓN REGISTRADA (gatillo ejecutado)'
            eventos.append(f"{icono} {sym} | {titulo}\n{texto_op_real(op, s)}")
            if testnet:
                if s['fase'] == 'PARCIAL' and previa != 'PARCIAL':
                    _testnet_parcial(sym, k, op, s, chat_id)
                elif s['fase'] in FASES_CERRADAS:
                    _testnet_cerrar(sym, k, op, s, cuenta, chat_id)
        op['fase'] = s['fase']
        if s['fase'] in FASES_CERRADAS:
            op['r_final'] = round(s['r'], 2)

    # 3) Retención: las cerradas más viejas se purgan
    cerradas = [k for k, o in ops.items() if o.get('fase') in FASES_CERRADAS]
    if len(cerradas) > MAX_OPS_CERRADAS:
        cerradas.sort(key=lambda k: str(ops[k].get('hora_gatillo', '')))
        for k in cerradas[:-MAX_OPS_CERRADAS]:
            ops.pop(k)
    return eventos


def texto_operaciones(sym, mem):
    """Bloque 'OPERACIONES REALES' (arranque y comando `operaciones`)."""
    ops = mem.get('operaciones') or {}
    vivas, cerradas = [], []
    for op in ops.values():
        if op.get('fase') in FASES_CERRADAS:
            cerradas.append(op)
            continue
        try:
            s = seguir_operacion(sym, op)
        except Exception:  # noqa: BLE001
            continue
        if s is not None:
            vivas.append(texto_op_real(op, s))
    if not vivas and not cerradas:
        return ''
    lineas = [f"OPERACIONES REALES {sym}:"]
    lineas += vivas or ["  (ninguna abierta)"]
    if cerradas:
        lineas.append("Cerradas: " + ", ".join(
            f"{o['patron']} {o['entrada']:.2f} ({o.get('r_final', 0):+.2f}R)"
            for o in cerradas[-5:]))
    return '\n'.join(lineas)
