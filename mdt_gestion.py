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
from mdt_config import FAMILIAS_OPERABLES, RATIO_MINIMO, PARCIAL_R

# A qué FAMILIA pertenece cada estado del motor (única tabla; el backtest la usó
# para segmentar el año y de ahí salió la decisión de qué se opera).
FAMILIA_DE_ESTADO = {
    # Entrada Profunda (Secc 16) — el que más paga: +0.73R por operación
    'P3_CORTA_GATILLO': 'ENTRADA PROFUNDA',
    'ENTRADA_PROFUNDA_ESPERANDO': 'ENTRADA PROFUNDA',
    'P3_CORTA_ROTA': 'ENTRADA PROFUNDA',
    # Engaño Extremo (Secc 17) — rentable, pero llega tarde: +0.27R
    'EE_GATILLO': 'ENGAÑO EXTREMO',
    'EE_ARMADO': 'ENGAÑO EXTREMO',
    'EE_EN_INDECISION': 'ENGAÑO EXTREMO',
    'EE_DESCARTADO_25': 'ENGAÑO EXTREMO',
    # Engaño clásico de 3 Pautas (Secc 9-13) — PIERDE dinero en el año: -0.17R
    'GATILLO_ACTIVADO': 'ENGAÑO 3 PAUTAS',
    'ENGAÑO_EN_CURSO': 'ENGAÑO 3 PAUTAS',
    'ESPERANDO_1618': 'ENGAÑO 3 PAUTAS',
    'VALIDADO_POSTERIOR': 'ENGAÑO 3 PAUTAS',
    'ANULADO_POR_CARENCIA': 'ENGAÑO 3 PAUTAS',
    # Doble Techo/Suelo con Impulso (Secc 18) — PIERDE dinero: -0.30R
    'DT_IMPULSO_GATILLO': 'DOBLE TECHO/SUELO',
    'DT_IMPULSO_ESPERANDO': 'DOBLE TECHO/SUELO',
    'ROTO_POR_RETESTEO_DILATACION': 'DOBLE TECHO/SUELO',
}


def se_opera(estado):
    """¿Esta familia de patrón se opera? (FAMILIAS_OPERABLES, mdt_config)."""
    return FAMILIA_DE_ESTADO.get(estado, 'OTRA') in FAMILIAS_OPERABLES


# Gatillos que entran a mercado. La lista COMPLETA la conoce el motor; lo que se
# OPERA lo decide FAMILIAS_OPERABLES (decisión 14 jul con el año delante).
ESTADOS_EJECUTADOS_TODOS = ("GATILLO_ACTIVADO", "P3_CORTA_GATILLO",
                            "DT_IMPULSO_GATILLO", "EE_GATILLO")
ESTADOS_EJECUTADOS = tuple(e for e in ESTADOS_EJECUTADOS_TODOS if se_opera(e))
# Ejecutados que además MURIERON después (el backtest también los simula)
ESTADOS_EJECUTADOS_MUERTOS = ("ROTO_POR_STOP_LOSS", "ROTO_POR_DOBLE_TOQUE",
                              "P3_CORTA_ROTA", "ROTO_POR_RETESTEO_DILATACION")

# Fases terminales de una operación real (vivía en mdt_ops; aquí no crea ciclos
# de import y la usan ops, testnet y los textos). CANCELADA = ancla muerta
# (candado Regla 3, conectado 16 jul).
FASES_CERRADAS = ('SL', 'BE', 'TP', 'CANCELADA')


def tp_cercano(lado, tp_zona):
    """El TP operativo: el borde CERCANO de la zona objetivo (conservador, Secc 7).
    Estaba escrito 6 veces por el código (auditoría 16 jul); si un día cambia el
    criterio, se cambia aquí y en ningún otro sitio."""
    return max(tp_zona) if lado == 'SELL' else min(tp_zona)


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
