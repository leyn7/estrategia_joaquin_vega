# -*- coding: utf-8 -*-
"""Los patrones de la llegada extrema: Entrada Profunda (Secc 16) y Engaño
Extremo (Secc 17), más la vigilancia del límite exterior.

Los dos nacen cuando el precio NO respeta la zona con un giro normal:
  - Entrada Profunda: la llegada cruzó la mitad de la zona y la proyección de
    engaños se salió — el cambio es irreversible y solo queda la Pauta 3 Corta.
  - Engaño Extremo: la llegada se salió de la zona entera — "la última
    oportunidad" antes de la anulación.

Todo en espacio canónico (semántica SELL); ver mdt_canonico.py.
"""
from mdt_config import NIVEL_618, NIVEL_809, ENGANO_1618


def entrada_profunda(df, HI, LO, zmax, anulacion, r, palabras, p1_idx, p1_val, detalles):
    """Patrón de Entrada Profunda (Sección 16). Contexto ya validado: llegada profunda
    (P1 cruzó la mitad de la zona) + proyección de engaños escapada (cambio irreversible).

    Pauta 3 Corta: entrada a mercado al toque del 61.8 del fibo dinámico de la Pauta 2
    (la zona va del 61.8 al 80.9, medida desde el extremo). No existe entrada agresiva.
      - SL DILATABLE (Secc 16): "el punto extremo MÁS PROFUNDO que haya dejado el
        precio en la zona antes de iniciar el retroceso" — si la llegada profundiza,
        el fibo se re-ancla en el nuevo extremo y el retroceso se re-mide desde ahí.
      - P2 CORRECTA obligatoria (video Secc 16: "una nueva pauta número 2 que ahora
        pueda ser CORRECTA... nos hace ese máximo y damos por bueno"): el extremo de
        la nueva Pauta 2 debe estar confirmado con 2 velas cerradas a la derecha (y
        vecinos izquierdos que no lo profundicen) antes de que el toque del 61.8
        pueda disparar. Sin P2 correcta no hay entrada — mata los gatillos
        instantáneos de micro-impulso (la escala del patrón acompaña a la del ciclo).
      - Si la llegada escapa de la zona, el contexto muta a Engaño Extremo (Secc 17).
      - Tras el gatillo, un retorno al extremo de la llegada = SL (P3_CORTA_ROTA).
    Replay cronológico: el toque solo cuenta desde el instante del escape activo.
    """
    detalles["calidad"] = "ENTRADA PROFUNDA (Pauta 3 Corta)"
    extremo = p1_val
    p2_run = LO[p1_idx]
    p2_idx = p1_idx
    escape_activo = False
    for i in range(p1_idx + 1, len(df)):
        if HI[i] > extremo:
            # La llegada sigue profundizando: SL dilatable + re-anclaje del fibo.
            # (Sin chequeo de gatillo en esta vela: no hay retroceso en curso.)
            extremo = HI[i]
            p2_run = LO[i]
            p2_idx = i
            if extremo > zmax:
                # La "llegada" se salió de la zona: territorio del Engaño Extremo
                if anulacion is not None:
                    return engano_extremo(df, HI, LO, r, palabras, i, extremo,
                                          zmax, anulacion, p2_run, detalles)
                return {"estado": "ANULADO_POR_ESCAPE",
                        "mensaje": "La llegada profunda escapó de la zona.",
                        "detalles": detalles, "idx_muerte": i}
            continue
        if LO[i] <= p2_run:
            # <= : el último toque del extremo manda (la confirmación cuenta desde ahí)
            p2_run = LO[i]
            p2_idx = i
        imp = extremo - p2_run
        if imp <= 0:
            continue
        if not escape_activo and p2_run + (imp * ENGANO_1618) >= zmax:
            escape_activo = True
        # P2 correcta: 2 velas cerradas a la derecha del extremo, izquierda sin profundizarlo
        p2_correcta = (i - p2_idx >= 2 and p2_idx >= 2
                       and LO[p2_idx - 1] >= p2_run and LO[p2_idx - 2] >= p2_run)
        if escape_activo and p2_correcta:
            n618 = p2_run + (imp * NIVEL_618)
            if HI[i] >= n618:
                n809 = p2_run + (imp * NIVEL_809)
                detalles.update({"pauta2_price": r(p2_run), "impulso": imp,
                                 "entrada_p3_corta": r(n618), "limite_gestion_809": r(n809),
                                 "stop_loss": r(extremo), "hora_gatillo": df.loc[i, 'open_time']})
                # Verificación post-gatillo: retorno al extremo de la llegada = SL
                for k in range(i + 1, len(df)):
                    if HI[k] >= extremo:
                        return {"estado": "P3_CORTA_ROTA",
                                "mensaje": "El precio volvió al extremo de la llegada tras el gatillo (SL).",
                                "detalles": detalles, "idx_muerte": k}
                return {"estado": "P3_CORTA_GATILLO",
                        "mensaje": f"Entrada Profunda: toque del 61.8 en {r(n618):.2f}. "
                                   f"{palabras['accion']} a mercado. SL {r(extremo):.2f}",
                        "detalles": detalles}
    imp = extremo - p2_run
    n618 = p2_run + (imp * NIVEL_618)
    n809 = p2_run + (imp * NIVEL_809)
    detalles.update({"pauta2_price": r(p2_run), "impulso": imp,
                     "entrada_p3_corta": r(n618), "limite_gestion_809": r(n809),
                     "stop_loss": r(extremo)})
    return {"estado": "ENTRADA_PROFUNDA_ESPERANDO",
            "mensaje": f"Entrada Profunda activa. Esperando retroceso al 61.8 ({r(n618):.2f}, "
                       f"zona hasta {r(n809):.2f}). SL {r(extremo):.2f}",
            "detalles": detalles}


def engano_extremo(df, HI, LO, r, palabras, idx_escape, extremo_inicial,
                   zmax, anulacion, origen_mov, detalles):
    """Patrón de Engaño Extremo (Sección 17) — la última oportunidad de la zona.

    Contexto ya validado: el precio rompió el límite exterior de la Zona de
    Decisión sin haber tocado la anulación. El espacio [límite, anulación] es la
    Zona de Indecisión: mientras el precio flota ahí, ES INOPERABLE.
      - Regla del 25%: el engaño extremo solo es válido si el precio se adentra
        al menos el 25% de la longitud total de la indecisión (busca liquidez
        profunda). Un escape más tímido se descarta: probable sacudida mayor.
      - Entrada agresiva: en el instante en que, cumplido el >=25%, el precio
        vuelve a cruzar la línea hacia el interior de la zona (1 pip, sin cierres).
      - SL: en el extremo absoluto que dejó el engaño en la indecisión.
      - Si toca la anulación, la zona muere con el ciclo (lo confirma el mapa).
      - Fibo de seguimiento desde el origen absoluto del movimiento (el extremo
        de la P2 que originó la subida al escape) para la entrada calmada 61.8.
    """
    detalles["calidad"] = "ENGAÑO EXTREMO (Secc 17)"
    span = anulacion - zmax
    ext = extremo_inicial
    for i in range(idx_escape, len(df)):
        if HI[i] > ext:
            ext = HI[i]
        if ext >= anulacion:
            return {"estado": "ANULADO_POR_ESCAPE",
                    "mensaje": f"El escape tocó la anulación ({r(anulacion):.2f}): zona y ciclo muertos.",
                    "detalles": detalles, "idx_muerte": i}
        profundidad = ext - zmax
        valido = profundidad >= span * 0.25
        if LO[i] <= zmax:
            # El precio volvió a meterse al interior de la Zona de Decisión
            if valido:
                imp = ext - origen_mov
                seg618 = ext - imp * NIVEL_618
                detalles.update({"stop_loss": r(ext), "gatillo_agresivo": r(zmax),
                                 "profundidad_indecision": profundidad,
                                 "espera_calmada": r(seg618), "fibo_seguimiento_618": r(seg618),
                                 "hora_gatillo": df.loc[i, 'open_time']})
                # Verificación post-gatillo: el precio no debe volver al extremo del escape
                for k in range(i + 1, len(df)):
                    if HI[k] >= ext:
                        detalles["idx_pico_engano"] = i
                        return {"estado": "ROTO_POR_STOP_LOSS",
                                "mensaje": "El precio volvió al extremo del engaño extremo tras el gatillo.",
                                "detalles": detalles, "idx_muerte": k}
                return {"estado": "EE_GATILLO",
                        "mensaje": f"Engaño Extremo válido ({profundidad:.2f} = {profundidad / span:.0%} de la indecisión). "
                                   f"{palabras['accion']} a mercado al cruce de {r(zmax):.2f}. SL {r(ext):.2f}",
                        "detalles": detalles}
            return {"estado": "EE_DESCARTADO_25",
                    "mensaje": f"Escape tímido ({profundidad:.2f} < 25% de la indecisión {span:.2f}): "
                               "se descarta, probable sacudida más potente después.",
                    "detalles": detalles, "idx_muerte": i}
    # Sigue flotando en la indecisión: inoperable (Secc 17)
    detalles.update({"extremo_escape": r(ext), "profundidad_indecision": ext - zmax,
                     "regla_25": r(zmax + span * 0.25)})
    if ext - zmax >= span * 0.25:
        return {"estado": "EE_ARMADO",
                "mensaje": f"Engaño Extremo ARMADO (se adentró {ext - zmax:.2f} >= 25% de la indecisión). "
                           f"{palabras['accion']} agresiva si el precio cruza de vuelta {r(zmax):.2f}. SL {r(ext):.2f}",
                "detalles": detalles}
    return {"estado": "EE_EN_INDECISION",
            "mensaje": f"Precio en Zona de Indecisión (inoperable): necesita adentrarse hasta "
                       f"{r(zmax + span * 0.25):.2f} (25%) para armar el Engaño Extremo.",
            "detalles": detalles}


def vigilar_escape(df, HI, LO, zmax, anulacion, r, palabras, desde, etiqueta, historial):
    """Vigilancia del límite exterior (Secc 17) cuando la cadena de patrones ya no
    tiene P1 que evaluar. El EE es "la última oportunidad" de la zona y un escape
    tímido descartado anuncia "una sacudida más potente después": el escape se
    sigue vigilando episodio tras episodio (caso real 6 jul 2026: tras un
    EE_DESCARTADO_25 de 0.03, el escape real a 593.83 era invisible porque el pico
    del escape queda FUERA de la zona y jamás vuelve a haber P1 dentro).

    Devuelve el último episodio de EE encontrado (o None si nunca hubo escape).
    """
    ultimo = None
    j = desde
    while j < len(df):
        if HI[j] > zmax:
            detalles = {"nivel_engano": etiqueta,
                        "pauta1_time": df.loc[j, 'open_time'],
                        "sugerencia_volumen": "Volumen Normal"}
            origen_mov = float(LO[desde:j + 1].min())
            res = engano_extremo(df, HI, LO, r, palabras, j, HI[j],
                                 zmax, anulacion, origen_mov, detalles)
            historial.append(res)
            ultimo = res
            if res["estado"] == "ROTO_POR_STOP_LOSS":
                # La vela que saltó el SL sigue escapada: re-medir el episodio ahí
                j = res["idx_muerte"]
                continue
            if res["estado"] == "EE_DESCARTADO_25":
                # Escape tímido: seguir esperando la sacudida más potente
                j = res["idx_muerte"] + 1
                continue
            return res  # vivo (GATILLO/ARMADO/INDECISION) o ANULADO_POR_ESCAPE
        j += 1
    return ultimo
