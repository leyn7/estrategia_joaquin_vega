# -*- coding: utf-8 -*-
"""Operaciones REALES del operador: gatillos ejecutados persistidos + gestión.

Por qué existen: la cadena de patrones es SIN ESTADO, y al re-parsear el
episodio con velas nuevas puede borrar del historial un gatillo que SÍ disparó
(caso real: el EE_GATILLO venta 590.28/SL 593.83 del 5 jul desapareció el 8 jul
cuando la Entrada Profunda re-leyó el episodio). Por eso, cuando un gatillo se
ejecuta, se guarda como un HECHO en estado_vivo.json con sus datos originales
(entrada, SL, TP) y se sigue con velas reales pase lo que pase con el re-parseo.
Sobrevive reinicios.

La caminata de gestión (Secc 20) vive en mdt_gestion — la MISMA que usa el
backtest. El espejo en el exchange (testnet) vive en mdt_testnet (auditoría 16
jul: antes estaba todo aquí, 422 líneas mezclando dos mundos).

CANDADO REGLA 3 (conectado 16 jul — estaba escrito y nadie lo llamaba): el mapa
es la única fuente de anclas, y el candado vigila LA PUERTA: un gatillo nuevo
cuya ancla ya no es un ciclo VIVO del mapa no se opera. Solo la puerta (regla
usuario 16 jul): "las posiciones, cuando se abren, ya solo dependen de su TP y
su stop loss — ya no dependen de ningún ancla". Una operación abierta es un
hecho con vida propia; la gobiernan su SL y su TP, no el mapa.
"""
import logging

import pandas as pd

from mdt_config import MAX_OPS_DIA, MDT_MODO, MIN_RIESGO_PCT
from mdt_data import to_cot
from mdt_estado import MAX_OPS_CERRADAS, get_klines_vivo, naive
from mdt_formato import hora_cot
from mdt_gestion import (ESTADOS_EJECUTADOS, FASES_CERRADAS,
                         entrada_de_resultado, gestionar, tp_cercano)
from mdt_macro_mapper import ancla_viva

log = logging.getLogger('mdt.ops')


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
    tp = tp_cercano(lado, op['tp_zona'])
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
        cierre = {'SL': 'STOP LOSS', 'BE': 'BREAKEVEN (tras parcial)', 'TP': 'TP COMPLETO',
                  'CANCELADA': 'CANDADO REGLA 3 (ancla muerta)'}
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


def actualizar_operaciones(sym, resultado, mem, cuenta=None, chat_id=None):
    """Registra gatillos ejecutados nuevos y sigue los abiertos con velas reales.
    Devuelve los eventos de transición. Las operaciones son HECHOS: se notifican
    siempre, sin filtro de notificaciones.

    Si MDT_MODO='testnet' y se pasa `cuenta`, cada transición se espeja con
    órdenes REALES en el testnet (mdt_testnet)."""
    ops = mem.setdefault('operaciones', {})
    eventos = []
    mapa = resultado.get('mapa')
    testnet = MDT_MODO == 'testnet' and cuenta is not None
    if testnet:
        import mdt_cartera
        import mdt_testnet
        # El balance que manda es el REAL de la cuenta demo (regla 15 jul)
        try:
            cuenta['balance'] = mdt_cartera.balance_real(sym)
        except Exception:  # noqa: BLE001 — si el exchange no responde, sigue lo último
            log.exception("testnet: no se pudo leer el balance real")
        # Red de seguridad: cobertura exacta (nada desnudo, cero huérfanos)
        mdt_testnet.red_seguridad(sym, chat_id)
        # Gestión de conjunto: cerrar todo si el flotante llega a la meta de los TP
        if mdt_testnet.objetivo_conjunto(sym, ops, cuenta, chat_id):
            return eventos   # se cerró todo: nada más que seguir este ciclo

    # 1) Registrar gatillos ejecutados nuevos (dedup por lado|ancla|patrón|entrada)
    for e in resultado['escaneos']:
        if e['contexto']:
            continue
        op = op_de_escaneo(e)
        if op is None:
            continue
        k = f"{op['lado']}|{op['ancla']:.2f}|{op['patron']}|{op['entrada']:.2f}"
        if k in ops:
            continue
        # CANDADO Regla 3 en la puerta: solo se opera un ancla VIVA del mapa.
        # Se registra igual (dedup: que no re-avise cada ciclo) pero CANCELADA.
        if mapa is not None and not ancla_viva(mapa, op['ancla'], tol=0.01):
            ops[k] = {**op, 'fase': 'CANCELADA', 'r_final': 0.0}
            eventos.append(f"⚓💀 {sym} | CANDADO REGLA 3: gatillo DESCARTADO — el ancla "
                           f"{op['ancla']:.2f} ya no es un ciclo vivo del mapa.\n"
                           f"  {op['lado']} {op['patron']} @ {op['entrada']:.2f} no se opera.")
            continue
        # COMPUERTA DEL STOP FINO (regla usuario 16 jul: "esa era la idea, que no
        # se tomaran"). Un SL más cerca del MIN_RIESGO_PCT no es operable: para
        # arriesgar $5 obliga a nocionales de miles y las comisiones se comen el
        # riesgo. Datos de la semana: 14/18 señales eran finas y las 14 murieron
        # en SL en minutos; las 4 sanas van bien. Se registra (dedup) pero NUNCA
        # se opera ni va al exchange. El análisis la sigue mostrando con su aviso.
        riesgo_pct = abs(op['entrada'] - op['sl']) / op['entrada'] if op['entrada'] else 0
        if riesgo_pct < MIN_RIESGO_PCT:
            ops[k] = {**op, 'fase': 'DESCARTADA', 'r_final': 0.0}
            eventos.append(f"🚫 {sym} | STOP FINO: gatillo descartado — SL a "
                           f"{riesgo_pct:.2%} del precio (mínimo {MIN_RIESGO_PCT:.2%}).\n"
                           f"  {op['lado']} {op['patron']} @ {op['entrada']:.2f}: las "
                           f"comisiones se comen el riesgo, no se opera.")
            continue
        ops[k] = {**op, 'fase': None}
        aviso = _aviso_limite_diario(sym, ops)
        if aviso:
            eventos.append(aviso)
        if testnet:
            mdt_testnet.abrir(sym, k, ops[k], ops, cuenta, chat_id)

    # 2) Seguir cada operación no cerrada. OJO: aquí el candado NO entra — una
    # posición abierta ya solo depende de su TP y su stop loss (regla usuario 16
    # jul); el ancla solo importaba para ENTRAR.
    for k, op in list(ops.items()):
        if op.get('fase') in FASES_CERRADAS:
            continue
        # En testnet, el cierre por SL/TP lo decide el EXCHANGE (reconciliación)
        if testnet and op.get('testnet'):
            import mdt_testnet
            try:
                if mdt_testnet.reconciliar(sym, k, op, cuenta, chat_id):
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
            # El parcial (1:2) SÍ es decisión del bot (por velas); el cierre final
            # lo decide el exchange (reconciliación arriba).
            if testnet and s['fase'] == 'PARCIAL' and previa != 'PARCIAL':
                import mdt_testnet
                mdt_testnet.parcial(sym, k, op, s, chat_id)
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
