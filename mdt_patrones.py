# -*- coding: utf-8 -*-
"""Escáner de patrones de giro (Secciones 9-18 de la biblia).

TODA la lógica vive UNA sola vez en "espacio canónico": un patrón de VENTAS con
la P1 arriba. La dirección BUY se procesa reflejando los precios (p -> -p, con
high/low intercambiados), igual que evaluar_ciclo y extraer_puntos_control.
Así compras y ventas no pueden divergir jamás: son literalmente el mismo código.

Convenciones canónicas (siempre semántica SELL):
  HI[i] = tope de la vela   (SELL: high  | BUY: -low)
  LO[i] = fondo de la vela  (SELL: low   | BUY: -high)
  zmax/zmin = techo/piso canónicos de la zona (en BUY se invierten y niegan)
  r(v) = valor real de un precio canónico (v en SELL, -v en BUY)
"""
from mdt_data import get_binance_klines
from mdt_fractal import find_micro_fractals
from mdt_config import NIVEL_618, NIVEL_809, ENGANO_1382, ENGANO_1618


def _espacio_canonico(df, zona_max, zona_min, direction):
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


def _entrada_profunda(df, HI, LO, zmax, r, palabras, p1_idx, p1_val, detalles):
    """Patrón de Entrada Profunda (Sección 16). Contexto ya validado: llegada profunda
    (P1 cruzó la mitad de la zona) + proyección de engaños escapada (cambio irreversible).

    Pauta 3 Corta: entrada a mercado al toque del 61.8 del fibo dinámico de la Pauta 2
    (la zona va del 61.8 al 80.9, medida desde el extremo). SL en el extremo de la llegada.
    No existe entrada agresiva. Replay cronológico: el toque solo cuenta desde el instante
    en que el escape se activó.
    """
    detalles["calidad"] = "ENTRADA PROFUNDA (Pauta 3 Corta)"
    p2_run = LO[p1_idx]
    escape_activo = False
    for i in range(p1_idx + 1, len(df)):
        if LO[i] < p2_run:
            p2_run = LO[i]
        imp = p1_val - p2_run
        if not escape_activo and p2_run + (imp * ENGANO_1618) >= zmax:
            escape_activo = True
        if escape_activo:
            n618 = p2_run + (imp * NIVEL_618)
            if HI[i] >= n618:
                n809 = p2_run + (imp * NIVEL_809)
                detalles.update({"pauta2_price": r(p2_run), "impulso": imp,
                                 "entrada_p3_corta": r(n618), "limite_gestion_809": r(n809),
                                 "stop_loss": r(p1_val), "hora_gatillo": df.loc[i, 'open_time']})
                return {"estado": "P3_CORTA_GATILLO",
                        "mensaje": f"Entrada Profunda: toque del 61.8 en {r(n618):.2f}. "
                                   f"{palabras['accion']} a mercado. SL {r(p1_val):.2f}",
                        "detalles": detalles}
    imp = p1_val - p2_run
    n618 = p2_run + (imp * NIVEL_618)
    n809 = p2_run + (imp * NIVEL_809)
    detalles.update({"pauta2_price": r(p2_run), "impulso": imp,
                     "entrada_p3_corta": r(n618), "limite_gestion_809": r(n809),
                     "stop_loss": r(p1_val)})
    return {"estado": "ENTRADA_PROFUNDA_ESPERANDO",
            "mensaje": f"Entrada Profunda activa. Esperando retroceso al 61.8 ({r(n618):.2f}, "
                       f"zona hasta {r(n809):.2f}). SL {r(p1_val):.2f}",
            "detalles": detalles}


def _doble_techo_impulso(df, HI, LO, r, palabras, idx_ruptura, dilatacion, extremo, detalles):
    """Patrón de Doble Suelo/Techo con Impulso (Sección 18). Contexto ya validado:
    la P3 nunca llegó a los niveles de engaño (ni al 138.2) y el precio rompió el
    extremo de la Pauta 2 por >= 1/3 de la altura de esa Pauta 2 (regla del tercio).

    El Fibo de Entrada se descarta. Fibo de seguimiento DINÁMICO a todo el nuevo
    impulso: desde la máxima dilatación (mecha absoluta en la base de la Pauta 3,
    donde va el SL) hasta el extremo corrido de la rotura. No existe entrada
    agresiva: se entra al toque de la zona del 61.8 (retroceso del impulso).
    Muerte: el precio tiene prohibido volver a tocar la máxima dilatación.
    """
    detalles["calidad"] = "DOBLE TECHO/SUELO CON IMPULSO (Secc 18)"
    detalles["dilatacion_maxima"] = r(dilatacion)
    ext = extremo
    for i in range(idx_ruptura + 1, len(df)):
        if HI[i] >= dilatacion:
            return {"estado": "ROTO_POR_RETESTEO_DILATACION",
                    "mensaje": f"Retesteó la máxima dilatación ({r(dilatacion):.2f}): patrón roto, nuevo análisis.",
                    "detalles": detalles, "idx_muerte": i}
        if LO[i] < ext:
            ext = LO[i]
        imp = dilatacion - ext
        n618 = ext + imp * NIVEL_618
        if HI[i] >= n618:
            detalles.update({"impulso_dt": imp, "extremo_impulso": r(ext),
                             "entrada_dt_618": r(n618), "limite_gestion_809": r(ext + imp * NIVEL_809),
                             "stop_loss": r(dilatacion), "hora_gatillo": df.loc[i, 'open_time']})
            return {"estado": "DT_IMPULSO_GATILLO",
                    "mensaje": f"{palabras['dt']} con Impulso: toque del 61.8 en {r(n618):.2f}. "
                               f"{palabras['accion']} a mercado. SL {r(dilatacion):.2f}",
                    "detalles": detalles}
    imp = dilatacion - ext
    n618 = ext + imp * NIVEL_618
    detalles.update({"impulso_dt": imp, "extremo_impulso": r(ext),
                     "entrada_dt_618": r(n618), "limite_gestion_809": r(ext + imp * NIVEL_809),
                     "stop_loss": r(dilatacion)})
    return {"estado": "DT_IMPULSO_ESPERANDO",
            "mensaje": f"{palabras['dt']} con Impulso. Esperando retroceso al 61.8 ({r(n618):.2f}, "
                       f"zona hasta {r(ext + imp * NIVEL_809):.2f}). SL {r(dilatacion):.2f}",
            "detalles": detalles}


def evaluate_peak_as_p1(df, p1_idx, zona_max, zona_min, direction):
    HI, LO, zmax, zmin, r, palabras = _espacio_canonico(df, zona_max, zona_min, direction)

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
        "proporcional": proporcional
    }

    # Escape de proyección (Sección 16): basta el 161.8 fuera O al ras del límite. Irreversible.
    escapado = fibo_1618 >= zmax
    # Llegada profunda: la Pauta 1 debe haber cruzado la mitad de la zona
    llegada_profunda = p1_val >= mitad_zona

    if escapado:
        if llegada_profunda:
            # Llegada profunda + escape -> Patrón de Entrada Profunda (Pauta 3 Corta)
            return _entrada_profunda(df, HI, LO, zmax, r, palabras, p1_idx, p1_val, detalles)
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
                        return _doble_techo_impulso(df, HI, LO, r, palabras, j, pico_engano, tercio_ext, detalles)
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
                    if pico_engano > zmax: return {"estado": "ANULADO_POR_ESCAPE", "mensaje": "Escape de zona tras tocar 161.8%", "detalles": detalles, "idx_muerte": j}
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


def detect_patron_institucional(df, zona_max, zona_min, direction):
    peaks, troughs = find_micro_fractals(df)
    fractals = peaks if direction == "SELL" else troughs

    # Solo nos importan los fractales que están dentro de la zona
    fractals_en_zona = [f for f in fractals if zona_min <= (df.loc[f, 'high'] if direction == "SELL" else df.loc[f, 'low']) <= zona_max]

    if not fractals_en_zona:
        return {"estado": "NO_INICIADO", "mensaje": "No hay picos en la zona."}

    numero_engano = 1
    idx_inicio_busqueda = fractals_en_zona[0]
    p1_forzado = None            # ancla directa del siguiente engaño (Secc 14)
    perdida_valida_en_2 = False  # Secc 15: el volumen solo baja si el 2º dio pérdida válida
    ultimo_p1 = -1
    ultimo_resultado = {"estado": "NO_INICIADO", "mensaje": "Error desconocido."}

    def _en_zona(idx):
        v = df.loc[idx, 'high'] if direction == "SELL" else df.loc[idx, 'low']
        return zona_min <= v <= zona_max

    while numero_engano <= 3:
        if p1_forzado is not None and p1_forzado > ultimo_p1:
            p1_idx = p1_forzado
            p1_forzado = None
        else:
            # Encontrar el primer fractal válido DESPUÉS del idx_inicio_busqueda
            p1_forzado = None
            fractales_validos = [f for f in fractals_en_zona if f >= idx_inicio_busqueda]
            if not fractales_validos:
                break
            p1_idx = fractales_validos[0]
        ultimo_p1 = p1_idx
        res = evaluate_peak_as_p1(df, p1_idx, zona_max, zona_min, direction)

        # Añadimos metadatos del nivel de engaño
        nombre_engano = "PRIMER ENGAÑO" if numero_engano == 1 else "SEGUNDO ENGAÑO" if numero_engano == 2 else "TERCER ENGAÑO"
        if "detalles" in res:
            res["detalles"]["nivel_engano"] = nombre_engano
            if numero_engano == 3 and res["estado"] in ("GATILLO_ACTIVADO", "DT_IMPULSO_GATILLO"):
                # Secc 15: menor volumen SOLO si el 2º engaño ejecutó una pérdida válida
                res["detalles"]["sugerencia_volumen"] = ("Medio Volumen (pérdida válida en el 2º, Secc 15)"
                                                         if perdida_valida_en_2 else "Volumen Normal")
            else:
                res["detalles"]["sugerencia_volumen"] = "Volumen Normal"

        ultimo_resultado = res

        # Si el patrón EXISTIÓ y fracasó (SL, Doble Toque o No Proporcional roto),
        # el institucional hará uno nuevo: evolucionamos al siguiente engaño.
        if res["estado"] in ["ROTO_POR_STOP_LOSS", "ROTO_POR_DOBLE_TOQUE", "ANULADO_POR_PROPORCIONALIDAD"]:
            idx_muerte = res.get("idx_muerte", p1_idx + 1)
            if numero_engano == 2:
                perdida_valida_en_2 = res["estado"] == "ROTO_POR_STOP_LOSS"
            numero_engano += 1
            # Secc 14: "se mide el rechazo que ocasionó el fallo". El nuevo punto de
            # engaño original YA existe en el gráfico: el pico del 161.8 roto (doble
            # toque) o el extremo dejado por el patrón no proporcional. Solo cuando el
            # SL fue saltado (nuevo extremo por fuera) hay que esperar al nuevo fractal.
            if res["estado"] == "ROTO_POR_DOBLE_TOQUE" \
                    and res.get("idx_pico_engano", -1) > p1_idx and _en_zona(res["idx_pico_engano"]):
                p1_forzado = res["idx_pico_engano"]
            elif res["estado"] == "ANULADO_POR_PROPORCIONALIDAD" \
                    and idx_muerte > p1_idx and _en_zona(idx_muerte):
                p1_forzado = idx_muerte
            else:
                siguientes_fractales = [f for f in fractals_en_zona if f >= idx_muerte and f > p1_idx]
                if not siguientes_fractales:
                    break  # No hay más picos después de la rotura
                idx_inicio_busqueda = siguientes_fractales[0]
            continue

        # Estructuras que nunca fueron un engaño operable: NO consumen el contador.
        # - ANULADO_POR_ESCAPE: patrón incompleto (video: "es la primera vez que busco")
        # - ANULADO_VUELTA_EN_V: solo 2 pautas (Secc 9)
        # - ANULADO_SIN_SALIDA_DE_ZONA: la P2 no salió de la zona (trabajo interno, Secc 9)
        # - ROTO_POR_RETESTEO_DILATACION: Doble Techo/Suelo roto (Secc 18: nuevo análisis)
        if res["estado"] in ("ANULADO_POR_ESCAPE", "ANULADO_VUELTA_EN_V",
                             "ANULADO_SIN_SALIDA_DE_ZONA", "ROTO_POR_RETESTEO_DILATACION"):
            idx_muerte = res.get("idx_muerte", p1_idx + 1)
            siguientes_fractales = [f for f in fractals_en_zona if f >= idx_muerte and f > p1_idx]
            if siguientes_fractales:
                idx_inicio_busqueda = siguientes_fractales[0]
                continue
            else:
                break # No hay más picos: queda registrado el último estado

        # Si el patrón está ACTIVO, FORMÁNDOSE, es CARENCIA VIVA, ENTRADA PROFUNDA,
        # DOBLE TECHO/SUELO CON IMPULSO o espera nueva Pauta 1, nos quedamos aquí
        return res

    if numero_engano > 3:
         return {"estado": "ZONA_AGOTADA", "mensaje": "Se rompieron 3 engaños. La zona ya no es válida para un 4to engaño (Descartada)."}

    return ultimo_resultado

if __name__ == "__main__":
    from mdt_config import SYMBOL
    from mdt_data import to_cot
    print(f"Descargando velas M3 de {SYMBOL} para prueba (Últimas 10 horas)...")
    df_m3 = get_binance_klines(SYMBOL, "3m").tail(200).reset_index(drop=True)
    df_m3['open_time'] = to_cot(df_m3['open_time'])

    zona_max = 573.74
    zona_min = 565.14

    print("--- FRACTALES DETECTADOS (ÚLTIMAS VELAS) ---")
    peaks, troughs = find_micro_fractals(df_m3)
    print("Picos (Candidatos a P1):")
    for p in peaks[-5:]:
        print(f"  [{p}] {df_m3.loc[p, 'open_time']} -> {df_m3.loc[p, 'high']:.2f}")
    print("\nValles (Candidatos a P2):")
    for t in troughs[-5:]:
        print(f"  [{t}] {df_m3.loc[t, 'open_time']} -> {df_m3.loc[t, 'low']:.2f}")
    print("------------------------------------------\n")

    print(f"Buscando Patrones en Zona REAL DE VENTAS (Nivel 5 Media): {zona_max:.2f} a {zona_min:.2f}...\n")
    resultado = detect_patron_institucional(df_m3, zona_max, zona_min, "SELL")

    print("RESULTADO DEL ESCÁNER:")
    print(f"Estado: {resultado['estado']}")
    print(f"Mensaje: {resultado['mensaje']}")

    if 'detalles' in resultado:
        d = resultado['detalles']
        print(f"\n--- DETALLES DEL {d.get('nivel_engano', 'PATRÓN')} ---")
        print(f" PAUTA 1 (Llegada/Stop Anterior): Pico en {d.get('pauta1_price', 0):.2f} (Vela de las {d.get('pauta1_time', '')})")
        print(f" PAUTA 2 (Rechazo Actual): Valle en {d.get('pauta2_price', 0):.2f} (Vela de las {d.get('pauta2_time', '')})")
        print(f" Impulso (P1 - P2): {d.get('impulso', 0):.2f} USDT")
        print(f" Zona de Engaños (138.2% a 161.8%): {d.get('fibo_1382', 0):.2f} a {d.get('fibo_1618', 0):.2f}")
        print(f" Mitad de la zona operativa: {d.get('mitad_zona', 0):.2f} | Proporcional: {'SÍ' if d.get('proporcional') else 'NO'}")
        print(f" Calidad: {d.get('calidad', 'N/A')}")
        print(f" Volumen Recomendado: {d.get('sugerencia_volumen', 'N/A')}")

    if "GATILLO" in resultado['estado'] or "ENTRADA_PROFUNDA" in resultado['estado']:
        d = resultado['detalles']
        print("\n--- ZONAS DE OPERACIÓN ---")
        if 'gatillo_agresivo' in d: print(f" 🔥 GATILLO AGRESIVO (Market): {d['gatillo_agresivo']:.2f}")
        if 'entrada_p3_corta' in d: print(f" 🎯 ENTRADA P3 CORTA (toque 61.8): {d['entrada_p3_corta']:.2f} (zona hasta {d['limite_gestion_809']:.2f})")
        if 'entrada_dt_618' in d: print(f" 🎯 ENTRADA DOBLE TECHO/SUELO (toque 61.8): {d['entrada_dt_618']:.2f} (zona hasta {d['limite_gestion_809']:.2f})")
        if 'hora_gatillo' in d: print(f" ⏱️ HORA DEL GATILLO: {d['hora_gatillo']}")
        print(f" 🛑 STOP LOSS ESTRUCTURAL: {d['stop_loss']:.2f}")
        if 'espera_calmada' in d: print(f" 🧘 ENTRADA CALMADA (Límite): {d['espera_calmada']:.2f}")
        if 'fibo_seguimiento_618' in d: print(f" 🛡️ NIVEL DE PROTECCIÓN (50% OUT): {d['fibo_seguimiento_618']:.2f}")
