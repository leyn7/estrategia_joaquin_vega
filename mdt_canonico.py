# -*- coding: utf-8 -*-
"""Espacio canónico + calidad de la llegada: las primitivas de los patrones.

TODA la lógica de patrones vive UNA sola vez en "espacio canónico": un patrón de
VENTAS con la P1 arriba. La dirección BUY se procesa reflejando los precios
(p -> -p, con high/low intercambiados), igual que evaluar_ciclo y
extraer_puntos_control. Así compras y ventas no pueden divergir jamás: son
literalmente el mismo código.

Convenciones canónicas (siempre semántica SELL):
  HI[i] = tope de la vela   (SELL: high  | BUY: -low)
  LO[i] = fondo de la vela  (SELL: low   | BUY: -high)
  zmax/zmin = techo/piso canónicos de la zona (en BUY se invierten y niegan)
  r(v) = valor real de un precio canónico (v en SELL, -v en BUY)
"""


def espacio_canonico(df, zona_max, zona_min, direction):
    """Devuelve (HI, LO, zmax, zmin, r, palabras) en espacio canónico."""
    if direction == "SELL":
        HI = df['high'].to_numpy()
        LO = df['low'].to_numpy()
        r = lambda v: v
        palabras = {"accion": "VENTA", "dt": "Doble Techo",
                    "rotura_p2": "nuevo mínimo bajo la Pauta 2"}
        return HI, LO, zona_max, zona_min, r, palabras
    HI = (-df['low']).to_numpy()
    LO = (-df['high']).to_numpy()
    r = lambda v: -v
    palabras = {"accion": "COMPRA", "dt": "Doble Suelo",
                "rotura_p2": "nuevo máximo sobre la Pauta 2"}
    return HI, LO, -zona_min, -zona_max, r, palabras


def calidad_llegada(df, HI, p1_idx, zmin, direction):
    """Clasifica la FORMA de la llegada a la zona en la visita que contiene a P1
    (regla usuario 11 jul: "quiero operar zonas que me den esa mechita — toca
    ese máximo y sale"). Caso patrón: mechita del 10 jul (mecha 6x el cuerpo,
    1 vela, 0 cierres dentro) vs el camping de la Media del 593.83 (horas
    adentro, 100+ cierres dentro).

      BARRIDO  = manipulación institucional: visita <=3 velas, ningún cierre
                 dentro de la zona, y la penetración fue PURA MECHA (el cuerpo
                 de la vela del extremo nunca entró a la zona) o mecha
                 dominante (mecha >= 2x cuerpo).
      LENTA    = camping: >=5 cierres dentro de la zona en la visita.
      NORMAL   = el resto.

    Informativo (no cambia estados ni gatillos): viaja en detalles y el bot lo
    muestra en alertas; MDT_NOTIF_LLEGADA=barrido filtra las notificaciones.
    """
    m = 1.0 if direction == "SELL" else -1.0
    CL = m * df['close'].to_numpy()
    OP = m * df['open'].to_numpy()
    ini = p1_idx
    while ini > 0 and HI[ini - 1] >= zmin:
        ini -= 1
    fin = p1_idx
    while fin + 1 < len(HI) and HI[fin + 1] >= zmin:
        fin += 1
    n_visita = fin - ini + 1
    cierres_dentro = int(sum(1 for j in range(ini, fin + 1) if CL[j] >= zmin))
    cuerpo = abs(CL[p1_idx] - OP[p1_idx])
    tope_cuerpo = max(CL[p1_idx], OP[p1_idx])
    mecha = HI[p1_idx] - tope_cuerpo
    # "toca y sale": el cuerpo nunca entró a la zona (solo la mecha penetró),
    # o la mecha domina claramente el cuerpo
    pura_mecha = tope_cuerpo < zmin
    mecha_dom = mecha > 0 and mecha >= 2.0 * cuerpo
    if n_visita <= 3 and cierres_dentro == 0 and (pura_mecha or mecha_dom):
        calidad = "BARRIDO"
    elif cierres_dentro >= 5:
        calidad = "LENTA"
    else:
        calidad = "NORMAL"
    return {"calidad_llegada": calidad, "velas_visita": n_visita,
            "cierres_dentro": cierres_dentro,
            "mecha_vs_cuerpo": (round(float(mecha / cuerpo), 1) if cuerpo > 0 else None)}
