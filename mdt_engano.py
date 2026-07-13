# -*- coding: utf-8 -*-
"""UN engaño: las 3 Pautas desde un pico dado (Secciones 9-15).

`evaluate_peak_as_p1` toma un fractal de la zona y lo trata como Pauta 1 (el
punto de engaño original), sigue la formación vela a vela y devuelve el estado
del patrón. Es el corazón de la estrategia; todo lo demás lo orquesta.

Aquí viven, por orden de aparición:
  Secc 9-10  Pauta 2 confirmada 2+2, rechazo que SALE de la zona (Vuelta en V no)
  Secc 11    Zona de Engaños 138.2-161.8 + proporcionalidad (mitad de la zona)
  Secc 12    Carencia y Validación Posterior
  Secc 13    El extremo del 161.8 es intocable: segundo toque = muerte
  Secc 16-18 Salidas a los patrones extremos (ver mdt_patron_profundo/doble)

Espacio canónico (semántica SELL); ver mdt_canonico.py.
"""
from mdt_canonico import calidad_llegada, espacio_canonico
from mdt_config import NIVEL_618, ENGANO_1382, ENGANO_1618
from mdt_patron_doble import doble_techo_impulso
from mdt_patron_profundo import engano_extremo, entrada_profunda


def evaluate_peak_as_p1(df, p1_idx, zona_max, zona_min, direction, nivel_anulacion=None):
    HI, LO, zmax, zmin, r, palabras = espacio_canonico(df, zona_max, zona_min, direction)
    anulacion = None
    if nivel_anulacion is not None:
        anulacion = nivel_anulacion if direction == "SELL" else -nivel_anulacion

    p1_val = HI[p1_idx]
    p2_val = LO[p1_idx]
    p2_idx = p1_idx
    p2_locked = False
    start_p3 = None

    for i in range(p1_idx + 1, len(df)):
        if HI[i] >= p1_val:
            # Secc 10: la P2 termina cuando el precio "vuelve a TOCAR exactamente"
            # el punto de engaño original (no hace falta superarlo)
            p2_locked = True
            start_p3 = i
            break
        if LO[i] <= p2_val:
            # <= : un retoque igual del extremo mueve p2_idx al ÚLTIMO toque
            # (la confirmación 2+2 se cuenta desde ahí)
            p2_val = LO[i]
            p2_idx = i

    impulso = p1_val - p2_val
    if impulso == 0: return {"estado": "ANULADO", "mensaje": "Impulso cero."}

    if p2_locked:
        # Secc 10: la P2 debe dejar un extremo confirmado con 2 velas cerradas a cada
        # lado. p2_idx es el ÚLTIMO toque del extremo (los toques iguales anteriores
        # son el mismo extremo, no lo invalidan); a la derecha exigen 2 velas cerradas
        # antes del retorno a P1, y a la izquierda velas que no lo profundicen.
        # Si el precio retornó a la P1 sin esa confirmación, el giro solo tiene
        # 2 pautas: es una Vuelta en V (Secc 9) y se descarta algorítmicamente.
        confirmada = p2_idx >= 2 and start_p3 - p2_idx >= 2
        if confirmada:
            confirmada = LO[p2_idx - 2] >= p2_val and LO[p2_idx - 1] >= p2_val
        if not confirmada:
            return {"estado": "ANULADO_VUELTA_EN_V",
                    "mensaje": f"Vuelta en V: retornó a P1 ({r(p1_val):.2f}) sin P2 confirmada 2+2. "
                               "Solo 2 pautas: sin información objetiva, se descarta.",
                    "detalles": {"pauta1_price": r(p1_val), "pauta2_price": r(p2_val),
                                 "pauta1_time": df.loc[p1_idx, 'open_time']},
                    "idx_muerte": start_p3}

        # Secc 9: la Pauta 2 es el "rechazo DE LA ZONA" y la Pauta 3 "VUELVE A TESTEAR
        # la zona" — solo se re-testea lo que se abandonó. Video Zona 61.8: "una cosa es
        # el precio está en zona (dentro, no ha salido) y otra es HA trabajado zona (ha
        # estado y HA SALIDO)". Si el precio retornó a P1 sin que la P2 saliera de la
        # zona, es trabajo interno de la zona: no hay patrón de giro (no consume contador).
        if not p2_val < zmin:
            return {"estado": "ANULADO_SIN_SALIDA_DE_ZONA",
                    "mensaje": f"El rechazo (P2 {r(p2_val):.2f}) nunca salió de la zona "
                               f"({zona_max:.2f} a {zona_min:.2f}): trabajo interno, no es Pauta 2.",
                    "detalles": {"pauta1_price": r(p1_val), "pauta2_price": r(p2_val),
                                 "pauta1_time": df.loc[p1_idx, 'open_time']},
                    "idx_muerte": start_p3}

    fibo_1618 = p2_val + (impulso * ENGANO_1618)
    fibo_1382 = p2_val + (impulso * ENGANO_1382)

    # Proporcionalidad: al menos UNO de los niveles de la Zona de Engaños (138.2 o 161.8)
    # debe quedar más allá de la mitad de la zona operativa. Como el 161.8 es siempre el
    # más profundo, basta con chequear que el 161.8 cruce la mitad. Si no, NUNCA se opera.
    mitad_zona = (zmax + zmin) / 2.0
    proporcional = fibo_1618 >= mitad_zona

    detalles = {
        "pauta1_time": df.loc[p1_idx, 'open_time'],
        "pauta1_price": r(p1_val),
        "pauta2_time": df.loc[p2_idx, 'open_time'],
        "pauta2_price": r(p2_val),
        "impulso": impulso,
        "fibo_1382": r(fibo_1382),
        "fibo_1618": r(fibo_1618),
        "mitad_zona": r(mitad_zona),
        "proporcional": proporcional,
        **calidad_llegada(df, HI, p1_idx, zmin, direction)
    }

    # Escape de proyección (Sección 16): basta el 161.8 fuera O al ras del límite. Irreversible.
    escapado = fibo_1618 >= zmax
    # Llegada profunda: la Pauta 1 debe haber cruzado la mitad de la zona
    llegada_profunda = p1_val >= mitad_zona

    if escapado:
        if llegada_profunda:
            # Llegada profunda + escape -> Patrón de Entrada Profunda (Pauta 3 Corta)
            return entrada_profunda(df, HI, LO, zmax, anulacion, r, palabras, p1_idx, p1_val, detalles)
        # Sin llegada profunda NO hay Entrada Profunda: no existe patrón (no consume contador).
        detalles["calidad"] = "DESCARTADA (escape de niveles sin llegada profunda)"
        if p2_locked:
            return {"estado": "ANULADO_POR_ESCAPE",
                    "mensaje": "Niveles de engaño fuera de zona sin llegada profunda (patrón incompleto).",
                    "detalles": detalles, "idx_muerte": start_p3}
        return {"estado": "ESTRUCTURA_DESCARTADA",
                "mensaje": f"Proyección fuera de zona ({r(fibo_1618):.2f}) con llegada tímida (P1 {r(p1_val):.2f} no cruza la mitad {r(mitad_zona):.2f}). Sin patrón: esperar nueva Pauta 1.",
                "detalles": detalles}

    if not p2_locked:
        # Fibo dinámico: la Pauta 2 sigue viva y la Zona de Engaños se mueve con cada nuevo extremo.
        detalles["calidad"] = "PROYECCION PROPORCIONAL" if proporcional else "PROYECCION NO PROPORCIONAL (por ahora)"
        return {"estado": "EN_FORMACION_PAUTA_2",
                "mensaje": f"Formando Pauta 2 (actualmente {r(p2_val):.2f}). Zona de Engaños proyectada: {r(fibo_1382):.2f} a {r(fibo_1618):.2f}",
                "detalles": detalles}

    if not proporcional:
        # Patrón NO proporcional: no se opera jamás. Se rastrea su Pauta 3 hasta que el precio
        # deje un extremo y rompa la Pauta 2: ese extremo será el P1 del siguiente engaño (evolución).
        detalles["calidad"] = "NO PROPORCIONAL (Zona de Engaños no llega a la mitad de la zona)"
        pico_evo = p1_val
        idx_pico_evo = p1_idx
        for j in range(start_p3, len(df)):
            if HI[j] > pico_evo:
                pico_evo = HI[j]; idx_pico_evo = j
                if pico_evo > zmax:
                    if anulacion is not None:
                        # Secc 17: escape de la zona sin anulación conocida tocada -> Engaño Extremo
                        return engano_extremo(df, HI, LO, r, palabras, j, pico_evo,
                                              zmax, anulacion, p2_val, detalles)
                    return {"estado": "ANULADO_POR_ESCAPE", "mensaje": "Escape de zona durante patrón no proporcional", "detalles": detalles, "idx_muerte": j}
            if LO[j] < p2_val:
                detalles["extremo_evolucion"] = r(pico_evo)
                return {"estado": "ANULADO_POR_PROPORCIONALIDAD",
                        "mensaje": f"Patrón no proporcional roto ({palabras['rotura_p2']}). Evoluciona: nuevo P1 en {r(pico_evo):.2f}",
                        "detalles": detalles, "idx_muerte": idx_pico_evo}
        return {"estado": "NO_PROPORCIONAL_EN_CURSO",
                "mensaje": "Patrón vivo pero NO operable (no proporcional). Esperando evolución al siguiente engaño.",
                "detalles": detalles}

    calidad = "BUENA"
    detalles["calidad"] = calidad

    toco_1618 = False
    pico_engano = p1_val
    idx_pico = p1_idx
    gatillo = False
    idx_gatillo = None
    carencia_idx = None  # Gatillo prematuro (con carencia): NO es entrada, es patrón vivo no operable
    tercio_ext = None    # Extremo corrido tras romper la P2 sin llegar al 138.2 (Secc 18)

    for j in range(start_p3, len(df)):
        h = HI[j]
        l = LO[j]

        if not toco_1618:
            if h >= fibo_1618:
                toco_1618 = True; pico_engano = h; idx_pico = j
                tercio_ext = None  # regresó y consumió el 161.8: vuelve a mandar el engaño
                if pico_engano > zmax:
                    # La vela que consumió el 161.8 escapó de la zona en el acto
                    if anulacion is not None:
                        return engano_extremo(df, HI, LO, r, palabras, j, pico_engano,
                                              zmax, anulacion, p2_val, detalles)
                    return {"estado": "ANULADO_POR_ESCAPE", "mensaje": "Escape de zona tras tocar 161.8%", "detalles": detalles, "idx_muerte": j}
                if carencia_idx is not None:
                    # Era un engaño fraccionado: regresó y consumió el 161.8%. Se completa.
                    carencia_idx = None
                    calidad = "BUENA (Engaño fraccionado completado)"
                    detalles["calidad"] = calidad
                # Gatillo agresivo: cruza el punto de engaño por 1 pip, SIN esperar cierres
                if l <= p1_val: gatillo = True; idx_gatillo = j; break
            else:
                if h > pico_engano:
                    pico_engano = h; idx_pico = j
                if carencia_idx is None and l <= p1_val and pico_engano >= fibo_1382:
                    # Carencia (cruzó 138.2 pero no tocó 161.8): gatillo prematuro, NO se opera.
                    # Queda vivo esperando: consumo del 161.8 (fraccionado) o Validación Posterior.
                    calidad = "DEBIL (Carencia)"
                    detalles["calidad"] = calidad
                    carencia_idx = j
                # Secc 18: la P3 nunca llegó al 138.2 y el precio rompe la P2 en contra.
                # Regla del 1/3: si la ruptura supera el extremo de la P2 por >= 1/3 de
                # la altura de la P2, muta a Doble Techo/Suelo con Impulso.
                if carencia_idx is None and pico_engano < fibo_1382 and l < p2_val:
                    if tercio_ext is None or l < tercio_ext:
                        tercio_ext = l
                    if tercio_ext <= p2_val - (p1_val - p2_val) / 3.0:
                        return doble_techo_impulso(df, HI, LO, r, palabras, j, pico_engano, tercio_ext, detalles)
                if carencia_idx is not None and l < p2_val:
                    # VALIDACIÓN POSTERIOR (Sección 12): tras el gatillo con carencia, el precio
                    # rompió con fuerza el origen de la Pauta 3 (extremo de la Pauta 2).
                    # El engaño se valida retroactivamente: SOLO entrada calmada.
                    min_post = LO[j:].min()  # extremo del impulso confirmado hasta ahora
                    impulso_conf = pico_engano - min_post
                    fibo_618_seg = pico_engano - (impulso_conf * NIVEL_618)
                    detalles["stop_loss"] = r(pico_engano)
                    detalles["extremo_impulso"] = r(min_post)
                    detalles["espera_calmada"] = r(fibo_618_seg)
                    detalles["fibo_seguimiento_618"] = r(fibo_618_seg)
                    detalles["hora_validacion"] = df.loc[j, 'open_time']
                    detalles["calidad"] = "VALIDADO POSTERIOR (solo entrada calmada)"
                    return {"estado": "VALIDADO_POSTERIOR",
                            "mensaje": f"Carencia validada retroactivamente (rompió {r(p2_val):.2f}). Esperar retroceso calmado a {r(fibo_618_seg):.2f}",
                            "detalles": detalles}
        else:
            # Secc 13: el extremo del 161.8 se confirma con 2 velas cerradas a la
            # derecha sin tocarlo; desde entonces es INTOCABLE (segundo toque = muerte).
            # Antes de confirmarse, un nuevo toque/extremo solo dilata el engaño.
            confirmado = j - idx_pico > 2
            if h >= pico_engano:
                if confirmado:
                    detalles["idx_pico_engano"] = idx_pico
                    return {"estado": "ROTO_POR_DOBLE_TOQUE",
                            "mensaje": f"Retesteó el extremo confirmado del engaño ({r(pico_engano):.2f})",
                            "detalles": detalles, "idx_muerte": j, "idx_pico_engano": idx_pico}
                if h > pico_engano:
                    pico_engano = h
                    if pico_engano > zmax:
                        if anulacion is not None:
                            return engano_extremo(df, HI, LO, r, palabras, j, pico_engano,
                                                  zmax, anulacion, p2_val, detalles)
                        return {"estado": "ANULADO_POR_ESCAPE", "mensaje": "Escape de zona tras tocar 161.8%", "detalles": detalles, "idx_muerte": j}
                idx_pico = j  # el engaño sigue dilatándose: se re-arma la confirmación
            # Gatillo agresivo: cruza el punto de engaño por 1 pip, SIN esperar cierres
            if l <= p1_val:
                gatillo = True; idx_gatillo = j; break

    if gatillo:
        # Gatillo REAL (consumió el 161.8). Secc 13: el retesteo mata "antes o después
        # del gatillo": toque exacto del pico = doble toque; superarlo = SL saltado.
        for k in range(idx_gatillo + 1, len(df)):
            if HI[k] >= pico_engano:
                estado = "ROTO_POR_STOP_LOSS" if HI[k] > pico_engano else "ROTO_POR_DOBLE_TOQUE"
                # La entrada SÍ ocurrió (y murió): el backtest necesita saberlo
                detalles["hora_gatillo"] = df.loc[idx_gatillo, 'open_time']
                detalles["gatillo_agresivo"] = r(p1_val)
                detalles["stop_loss"] = r(pico_engano)
                detalles["idx_pico_engano"] = idx_pico
                return {"estado": estado, "mensaje": "El precio volvió al extremo del engaño tras el gatillo.",
                        "detalles": detalles, "idx_muerte": k, "idx_pico_engano": idx_pico}

        impulso_seg = pico_engano - p2_val
        fibo_618_seg = pico_engano - (impulso_seg * NIVEL_618)
        detalles["stop_loss"] = r(pico_engano)
        detalles["gatillo_agresivo"] = r(p1_val)
        detalles["espera_calmada"] = r(fibo_618_seg)
        detalles["fibo_seguimiento_618"] = r(fibo_618_seg)
        detalles["hora_gatillo"] = df.loc[idx_gatillo, 'open_time']
        return {"estado": "GATILLO_ACTIVADO", "mensaje": "¡Engaño Completado! Entrada lista.", "detalles": detalles}

    if carencia_idx is not None:
        return {"estado": "ANULADO_POR_CARENCIA",
                "mensaje": "Entrada con Carencia (viva pero no operable). Esperando 161.8% o Validación Posterior.",
                "detalles": detalles}

    if not toco_1618:
        return {"estado": "ESPERANDO_1618", "mensaje": f"Buscando 161.8% en {r(fibo_1618):.2f}", "detalles": detalles}
    return {"estado": "ENGAÑO_EN_CURSO", "mensaje": "Esperando Gatillo.", "detalles": detalles}
