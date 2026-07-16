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
    media = t['cantidad'] / 2.0
    cierre = 'SELL' if op['lado'] == 'BUY' else 'BUY'
    info = mdt_ejecutor.info_simbolo(sym)
    be = mdt_ejecutor._redondear(op['entrada'], info['price_step'], info['price_precision'])
    try:
        mdt_ejecutor.cerrar_parcial(sym, op['lado'], media, t['position_side'])
        mdt_ejecutor.cancelar_ordenes(sym, [a for a in (t.get('algo_sl'), t.get('algo_tp')) if a])
        t['cantidad_viva'] = media
    except mdt_ejecutor.ErrorEjecucion as e:
        log.exception("testnet: fallo tomando el parcial de %s", k)
        mdt_telegram.enviar(chat_id, f"🧪❌ {sym} | TESTNET: fallo en parcial de {k}\n{e}")
        return

    # GARANTÍA: la mitad viva NUNCA queda sin stop. Se coloca primero el SL en
    # breakeven; si se dispararía ya (-2021) o falla, se cierra a mercado (bug 15
    # jul: si la recolocación fallaba, quedaba desnuda). El TP es secundario.
    try:
        t['algo_sl'] = mdt_ejecutor.mover_stop(sym, op['lado'], media, None, be, t['position_side'])
    except (mdt_ejecutor.StopDispararia, mdt_ejecutor.ErrorEjecucion):
        mdt_ejecutor.cerrar_a_mercado(sym, op['lado'], media, t['position_side'])
        t['algo_sl'] = t['algo_tp'] = None
        t['algos'] = []
        t['cantidad_viva'] = 0.0
        mdt_telegram.enviar(chat_id, f"🧪💰 {sym} | TESTNET: parcial hecho; el precio ya "
                                     f"tocaba breakeven, cerré el resto a mercado.")
        return
    try:
        tp_obj = max(op['tp_zona']) if op['lado'] == 'SELL' else min(op['tp_zona'])
        tp_r = mdt_ejecutor._redondear(tp_obj, info['price_step'], info['price_precision'])
        t['algo_tp'] = mdt_ejecutor._algo_stop(sym, cierre, t['position_side'],
                                               'TAKE_PROFIT_MARKET', tp_r, media)
    except mdt_ejecutor.ErrorEjecucion:
        t['algo_tp'] = None   # sin TP, pero CON stop: la posición está protegida
    t['algos'] = [a for a in (t.get('algo_sl'), t.get('algo_tp')) if a]
    mdt_telegram.enviar(chat_id, f"🧪💰 {sym} | TESTNET: parcial real ejecutado, "
                                 f"SL movido a breakeven ({op['entrada']:.4f})")


def _testnet_red_seguridad(sym, chat_id):
    """Cada ciclo: ninguna posición puede quedar sin stop. Si la hay (descuadre,
    parcial fallido...), se le pone uno de emergencia. Es la garantía última."""
    import mdt_ejecutor
    try:
        puestos = mdt_ejecutor.proteger_descubierto(sym)
    except Exception:  # noqa: BLE001
        log.exception("red de seguridad testnet")
        return
    for x in puestos:
        if x.get('cerrado_a_mercado'):
            mdt_telegram.enviar(chat_id, f"🧪🛟 {sym} | RED DE SEGURIDAD: {x['qty']} BNB "
                                         f"{x['side']} estaban sin stop; los cerré a mercado.")
        else:
            mdt_telegram.enviar(chat_id, f"🧪🛟 {sym} | RED DE SEGURIDAD: {x['qty']} BNB "
                                         f"{x['side']} estaban SIN STOP; les puse uno de "
                                         f"emergencia @ {x['trigger']}.")


def _testnet_objetivo_conjunto(sym, ops, cuenta, chat_id):
    """GESTIÓN DE CONJUNTO (regla usuario 15 jul): cerrar TODAS las posiciones de
    golpe cuando el flotante conjunto alcanza lo que se ganaría si cada una llegara
    a su TP. En vez de esperar TP individuales (imposibles de cobrar todos: unos
    arriba, otros abajo), se toma la ganancia conjunta cuando iguala esa meta.

    Devuelve True si cerró todo."""
    import mdt_ejecutor
    pos = mdt_ejecutor.posiciones(sym)
    if not pos:
        return False
    flotante = sum(p['upnl'] for p in pos)
    if flotante <= 0:
        return False   # nunca se cierra el conjunto en pérdida

    # Objetivo = suma de lo que ganaría cada posición en SU take-profit
    cob = mdt_ejecutor.cobertura_algos(sym)
    objetivo = 0.0
    for p in pos:
        c = cob.get(p['side'], {})
        tp_px = c.get('tp_px')
        if tp_px is None:
            return False   # falta algún TP: no hay meta completa, no cerrar
        objetivo += (tp_px - p['entry']) * p['amt']   # amt con signo
    if objetivo <= 0 or flotante < objetivo:
        return False

    # El flotante conjunto ya iguala la meta de todos los TP: cerrar todo
    real = mdt_ejecutor.cerrar_todo(sym)
    cuenta['balance'] = mdt_ejecutor.balance_real(sym)
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


def _testnet_reconciliar(sym, k, op, cuenta, chat_id):
    """El cierre lo decide el EXCHANGE, no la lectura de velas (corrección 15 jul).

    El bot pone SL y TP nativos con la cantidad de esta señal; Binance los ejecuta
    solo. Aquí se consulta cuál se disparó: si el SL desapareció, cerró por stop;
    si el TP desapareció, cerró por objetivo. El hermano que quede se cancela y se
    liquida el P&L real. El bot NUNCA cierra a mercado por su cuenta — eso
    duplicaba el cierre sobre la posición neta y dejaba restos sin stop.

    Devuelve True si la operación cerró en el exchange."""
    import mdt_ejecutor
    t = op.get('testnet')
    if t is None:
        return False
    algo_sl, algo_tp = t.get('algo_sl'), t.get('algo_tp')
    activos = [a for a in (algo_sl, algo_tp) if a]
    if not activos:
        return False
    vivos = mdt_ejecutor.algos_abiertos(sym, activos)
    if all(str(a) in {str(x) for x in vivos} for a in activos):
        return False   # ambos stops siguen puestos: la operación sigue viva

    # Uno se disparó -> la operación cerró. ¿Cuál?
    sl_disparo = algo_sl and str(algo_sl) not in {str(x) for x in vivos}
    fase = 'SL' if sl_disparo else 'TP'
    mdt_ejecutor.cancelar_ordenes(sym, [a for a in activos if str(a) in {str(x) for x in vivos}])

    import time as _t
    real = None
    try:
        real = mdt_ejecutor.pnl_realizado(sym, t['inicio_ms'], int(_t.time() * 1000))
    except Exception:  # noqa: BLE001
        log.exception("testnet: P&L de %s", k)

    pnl = real['pnl'] if real else 0.0
    op['fase'] = 'TP' if fase == 'TP' else 'SL'
    op['r_final'] = pnl
    cuenta['balance'] = mdt_ejecutor.balance_real(sym)   # el balance REAL manda
    cuenta.setdefault('historial', []).append({
        'op': k, 'patron': op['patron'], 'fase': fase, 'pnl': round(pnl, 2),
        'balance': round(cuenta['balance'], 2), 'hora': op['hora_gatillo'],
        'real': real is not None})
    icono = '🏁' if fase == 'TP' else '☠️'
    detalle = (f"real {real['bruto']:+.2f} − {real['comision']:.2f} comisión = {pnl:+.2f} USD"
               if real else "sin datos del exchange")
    mdt_telegram.enviar(chat_id,
        f"{icono} {sym} | TESTNET: {k} cerró por {fase} en el exchange\n"
        f"  {detalle}\n  balance real de la cuenta: ${cuenta['balance']:.2f}")
    return True


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
    if testnet:
        # El balance que manda es el REAL de la cuenta demo (regla usuario 15 jul:
        # "pon lo real que está ahora"), no un número inventado por dentro.
        try:
            import mdt_ejecutor
            cuenta['balance'] = mdt_ejecutor.balance_real(sym)
        except Exception:  # noqa: BLE001 — si el exchange no responde, se sigue con lo último
            log.exception("testnet: no se pudo leer el balance real")
        # Red de seguridad: ninguna posición sin stop (cada ciclo, garantía última)
        _testnet_red_seguridad(sym, chat_id)
        # Gestión de conjunto: cerrar todo si el flotante llega a la meta de los TP
        if _testnet_objetivo_conjunto(sym, ops, cuenta, chat_id):
            return eventos   # se cerró todo: nada más que seguir este ciclo

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
        # En testnet, el cierre por SL/TP lo decide el EXCHANGE (reconciliación),
        # no la lectura de velas: así no se cierra dos veces la posición neta.
        if testnet and op.get('testnet'):
            try:
                if _testnet_reconciliar(sym, k, op, cuenta, chat_id):
                    continue   # cerró en el exchange
            except Exception:  # noqa: BLE001
                log.exception("testnet: reconciliación de %s", k)
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
            # El parcial (1:2) SÍ es una decisión del bot (por velas): cierra media
            # y mueve el SL a breakeven. El cierre final NO — lo hace el exchange
            # (reconciliación arriba). Por eso aquí solo se maneja el parcial.
            if testnet and s['fase'] == 'PARCIAL' and previa != 'PARCIAL':
                _testnet_parcial(sym, k, op, s, chat_id)
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
