# -*- coding: utf-8 -*-
"""Gestión de operaciones MDT (Secc 20) — ÚNICA fuente de verdad.

Unifica (auditoría 12 jul) lo que vivía triplicado y ya había divergido una
vez (la entrada del Engaño Extremo):
  - Extracción de entrada/SL/hora de un resultado de patrón — la usan el
    escáner (4 Informaciones), el bot en vivo (registro de operaciones reales)
    y el backtest (entradas ejecutadas).
  - La caminata de gestión Secc 20 sobre velas — la usan el seguimiento de
    operaciones reales del bot y el simulador del backtest.
"""
from mdt_config import RATIO_MINIMO, PARCIAL_R

# Gatillos EJECUTADOS = entrada a mercado real
ESTADOS_EJECUTADOS = ("GATILLO_ACTIVADO", "P3_CORTA_GATILLO",
                      "DT_IMPULSO_GATILLO", "EE_GATILLO")
# Ejecutados que además MURIERON después (el backtest también los simula)
ESTADOS_EJECUTADOS_MUERTOS = ("ROTO_POR_STOP_LOSS", "ROTO_POR_DOBLE_TOQUE",
                              "P3_CORTA_ROTA", "ROTO_POR_RETESTEO_DILATACION")


def entrada_de_resultado(res, lado, rango):
    """Extrae (entrada, sl, hora_gatillo) de un resultado de patrón, o None.

    El Engaño Extremo entra al cruce del límite exterior de la zona: el borde
    superior del rango en ventas, el inferior en compras (Secc 17).
    """
    d = res.get('detalles', {})
    hora = d.get('hora_gatillo')
    entrada = (d.get('gatillo_agresivo') or d.get('entrada_p3_corta')
               or d.get('entrada_dt_618'))
    if entrada is None and res['estado'].startswith('EE_'):
        entrada = rango[0] if lado == 'SELL' else rango[1]
    sl = d.get('stop_loss', d.get('extremo_escape'))
    if hora is None or entrada is None or sl is None:
        return None
    return float(entrada), float(sl), hora


def gestionar(velas, lado, entrada, sl, tp):
    """Caminata de gestión Secc 20 sobre velas (df con high/low/close), ya
    recortadas al periodo posterior al gatillo.

    - SL tocado -> fase SL (-1R sobre la posición completa).
    - Objetivo > 1:3 -> parcial OBLIGATORIO a la mitad del objetivo (mín 1:2):
      mitad fuera + stop a BREAKEVEN; el breakeven cierra el resto en lo
      asegurado; el TP completa. Objetivo <= 1:3: todo-o-nada al TP.
    - Conservador vela a vela: el lado malo primero; el TP nunca se otorga en
      la misma vela del parcial.

    Devuelve {'fase','r','r_asegurada','ratio','nivel_parcial','tp',
    'sl_actual','precio'} — fase: SL | TP | BE | PARCIAL (abierta con parcial
    hecho, stop en breakeven) | ABIERTA. `r` es el resultado en R (cerradas) o
    el flotante total (abiertas). None si el riesgo es cero.
    """
    riesgo = abs(sl - entrada)
    if riesgo <= 0:
        return None
    ratio = abs(entrada - tp) / riesgo
    signo = -1.0 if lado == 'SELL' else 1.0
    nivel_parcial = None
    ratio_parcial = 0.0
    if ratio > RATIO_MINIMO:
        ratio_parcial = max(PARCIAL_R, ratio / 2.0)
        nivel_parcial = entrada + signo * ratio_parcial * riesgo
    base = {'ratio': ratio, 'nivel_parcial': nivel_parcial, 'tp': tp,
            'r_asegurada': 0.0, 'precio': None}
    fase, r_aseg = 'ABIERTA', 0.0
    for v in velas.itertuples():
        if fase == 'ABIERTA':
            if (v.high >= sl) if lado == 'SELL' else (v.low <= sl):
                return {**base, 'fase': 'SL', 'r': -1.0, 'sl_actual': sl}
            if nivel_parcial is not None and \
                    ((v.low <= nivel_parcial) if lado == 'SELL' else (v.high >= nivel_parcial)):
                fase, r_aseg = 'PARCIAL', 0.5 * ratio_parcial
            elif nivel_parcial is None and \
                    ((v.low <= tp) if lado == 'SELL' else (v.high >= tp)):
                return {**base, 'fase': 'TP', 'r': ratio, 'sl_actual': sl}
        else:
            if (v.high >= entrada) if lado == 'SELL' else (v.low <= entrada):
                return {**base, 'fase': 'BE', 'r': r_aseg, 'r_asegurada': r_aseg,
                        'sl_actual': entrada}
            if (v.low <= tp) if lado == 'SELL' else (v.high >= tp):
                return {**base, 'fase': 'TP', 'r': r_aseg + 0.5 * ratio,
                        'r_asegurada': r_aseg, 'sl_actual': entrada}
    ult = float(velas['close'].iloc[-1]) if len(velas) else entrada
    r_flot = ((entrada - ult) if lado == 'SELL' else (ult - entrada)) / riesgo
    if fase == 'PARCIAL':
        return {**base, 'fase': 'PARCIAL', 'r': r_aseg + 0.5 * r_flot,
                'r_asegurada': r_aseg, 'sl_actual': entrada, 'precio': ult}
    return {**base, 'fase': 'ABIERTA', 'r': r_flot, 'sl_actual': sl, 'precio': ult}
