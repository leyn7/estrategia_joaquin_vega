# -*- coding: utf-8 -*-
"""Las 4 Informaciones de una señal (Secc 7) + qué zona manda el precio.

De un patrón accionable a una OPERACIÓN: entrada, stop loss estructural,
objetivo (la zona contraria) y ratio. La extracción de entrada/SL vive en
mdt_gestion (única fuente de verdad, la misma que usan el registro de
operaciones reales y el backtest); aquí se le añade el objetivo y el veredicto.
"""
from mdt_config import MIN_RIESGO_PCT, RATIO_MINIMO, ZONA_MAX_OPERABLE_PCT
from mdt_gestion import entrada_de_resultado

# Estados que representan un setup accionable o vivo (para resaltar en el reporte)
ESTADOS_OPERABLES = ("GATILLO_ACTIVADO", "P3_CORTA_GATILLO", "DT_IMPULSO_GATILLO",
                     "EE_GATILLO", "EE_ARMADO", "VALIDADO_POSTERIOR",
                     "ENTRADA_PROFUNDA_ESPERANDO", "DT_IMPULSO_ESPERANDO",
                     "ENGAÑO_EN_CURSO", "ESPERANDO_1618")


def es_accionable(escaneo):
    """Señal operable de verdad: patrón en estado accionable y zona no-contexto."""
    return (escaneo['resultado']['estado'] in ESTADOS_OPERABLES
            and not escaneo['contexto'])


def direccion_prioritaria(mapa):
    """Regla del usuario (4 jul): "el que manda es el ciclo cuya zona se está
    trabajando ACTIVAMENTE" — la zona MÁS ESPECÍFICA (la más angosta) que contiene
    al precio, no la más grande que lo envuelva.

    Refinada (10 jul): las zonas macro de CONTEXTO no mandan — si no se operan,
    tampoco dictan la prioridad (caso real: la Media del Macro Alcista 638-410
    dictaba COMPRAS y marcaba Secundaria una venta nacida de un trabajo real).
    Esta dirección global queda como contexto del mapa; la prioridad de cada
    señal la hereda de SU propia zona en trabajo (construir_operacion)."""
    precio = mapa['precio']
    candidatos = [("SELL", z) for z in mapa['sells']] + [("BUY", z) for z in mapa['buys']]
    contienen = [(lado, z) for lado, z in candidatos
                 if z.get('z') and min(z['z']) <= precio <= max(z['z'])
                 and (max(z['z']) - min(z['z'])) <= precio * ZONA_MAX_OPERABLE_PCT]
    if not contienen:
        return None, None
    lado, z = min(contienen, key=lambda t: max(t[1]['z']) - min(t[1]['z']))
    return lado, z['name']


def construir_operacion(escaneo, prioritaria):
    """Construye las 4 Informaciones (Secc 7) de una señal accionable:
    entrada, SL estructural, TP (zona contraria / 61.8 de alerta), ratio mínimo
    1:3 (Secc 1, al borde cercano de la zona objetivo — conservador) y la
    etiqueta Prioritario/Secundario con su volumen."""
    res = escaneo['resultado']
    d = res.get('detalles', {})
    lado = escaneo['lado']
    hechos = entrada_de_resultado(res, lado, escaneo['rango'])
    if hechos is not None:
        # Gatillo EJECUTADO: extracción unificada (mdt_gestion, misma que
        # usan el registro de operaciones reales y el backtest)
        entrada, sl, _ = hechos
    else:
        # Patrón sin gatillo aún: VISTA PREVIA de la operación (entrada
        # calmada esperada / cruce del límite en el EE armado)
        entrada = (d.get('gatillo_agresivo') or d.get('entrada_p3_corta')
                   or d.get('entrada_dt_618') or d.get('espera_calmada'))
        if entrada is None and res['estado'].startswith('EE_'):
            entrada = escaneo['rango'][0] if lado == "SELL" else escaneo['rango'][1]
        sl = d.get('stop_loss', d.get('extremo_escape'))
    tp_zona = escaneo.get('tp_zona')
    if entrada is None or sl is None or tp_zona is None:
        return None
    tp = max(tp_zona) if lado == "SELL" else min(tp_zona)  # borde cercano (conservador)
    riesgo = abs(sl - entrada)
    if riesgo <= 0:
        return None
    recompensa = abs(entrada - tp)
    ratio = recompensa / riesgo
    # Regla del usuario (10 jul): la señal HEREDA la prioridad de SU zona — si
    # una zona en trabajo te da la entrada, esa operación es el Movimiento
    # Prioritario de ese trabajo, con sus propios TP ("en el trading nada es
    # seguro: cada oportunidad que se opere tendrá sus propios TP"). La
    # dirección global (zona más angosta no-contexto con el precio dentro) ya
    # no degrada la señal a Secundaria; si hay trabajo vivo en contra, se avisa.
    avisos = []
    if prioritaria is not None and lado != prioritaria:
        avisos.append("hay trabajo vivo en contra: el precio está dentro de una zona de "
                       + ("VENTAS" if prioritaria == "SELL" else "COMPRAS"))
    # SL pegado a la entrada (Secc 7 + regla usuario 14 jul): un ratio alto no
    # sirve de nada si el riesgo es tan chico que las comisiones (~0.1% ida y
    # vuelta) se lo comen antes de que el trade respire. Se avisa, no se oculta.
    riesgo_pct = riesgo / entrada
    cumple_riesgo_minimo = riesgo_pct >= MIN_RIESGO_PCT
    if not cumple_riesgo_minimo:
        riesgo_min = entrada * MIN_RIESGO_PCT
        avisos.append(f"SL demasiado ajustado ({riesgo_pct:.2%} de riesgo, {riesgo:.2f} en "
                       f"precio): las comisiones se lo comen — necesita al menos "
                       f"{MIN_RIESGO_PCT:.2%} ({riesgo_min:.2f})")
    return {"entrada": entrada, "stop_loss": sl,
            "tp_zona": (max(tp_zona), min(tp_zona)), "tp_nivel": tp,
            "riesgo": riesgo, "recompensa": recompensa, "ratio": ratio,
            "cumple_ratio": ratio >= RATIO_MINIMO,
            "riesgo_pct": riesgo_pct, "cumple_riesgo_minimo": cumple_riesgo_minimo,
            "movimiento": "PRIORITARIO (su zona en trabajo)",
            "aviso": " | ".join(avisos) or None,
            "volumen": "Normal"}
