# -*- coding: utf-8 -*-
"""LA CADENA DE ENGAÑOS de una zona (Secciones 9-19) — puerta de entrada.

Este archivo solo ORQUESTA la cadena: busca la Pauta 1 en la zona, evalúa el
engaño, y si ese engaño fracasó busca el siguiente (el institucional insiste
hasta 3 veces, Secc 15). Cada pieza vive en su módulo:

  mdt_canonico.py         espacio canónico (SELL/BUY reflejado) + calidad de llegada
  mdt_engano.py           UN engaño: las 3 Pautas desde un pico (Secc 9-15)
  mdt_patron_profundo.py  Entrada Profunda (Secc 16) y Engaño Extremo (Secc 17)
  mdt_patron_doble.py     Doble Suelo/Techo con Impulso (Secc 18)

La API que usan el escáner y los backtests es `detect_patron_institucional`.
"""
from mdt_canonico import espacio_canonico
from mdt_engano import evaluate_peak_as_p1
from mdt_fractal import find_micro_fractals
from mdt_patron_profundo import vigilar_escape

# Re-exportes por comodidad de los scripts de análisis manual
from mdt_canonico import calidad_llegada  # noqa: F401
from mdt_patron_doble import doble_techo_impulso  # noqa: F401
from mdt_patron_profundo import engano_extremo, entrada_profunda  # noqa: F401


def detect_patron_institucional(df, zona_max, zona_min, direction, nivel_anulacion=None):
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
    historial = []               # TODA la cadena evaluada (para backtest: las entradas que murieron)
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
        res = evaluate_peak_as_p1(df, p1_idx, zona_max, zona_min, direction, nivel_anulacion)

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
        historial.append(res)

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
        # - EE_DESCARTADO_25: escape tímido, el Engaño Extremo se descarta (Secc 17)
        # - P3_CORTA_ROTA: Entrada Profunda con SL tras el gatillo (no es un engaño,
        #   no consume el contador; la zona sigue buscando estructura nueva)
        if res["estado"] in ("ANULADO_POR_ESCAPE", "ANULADO_VUELTA_EN_V",
                             "ANULADO_SIN_SALIDA_DE_ZONA", "ROTO_POR_RETESTEO_DILATACION",
                             "EE_DESCARTADO_25", "P3_CORTA_ROTA"):
            idx_muerte = res.get("idx_muerte", p1_idx + 1)
            siguientes_fractales = [f for f in fractals_en_zona if f >= idx_muerte and f > p1_idx]
            if siguientes_fractales:
                idx_inicio_busqueda = siguientes_fractales[0]
                continue
            else:
                break # No hay más picos: queda registrado el último estado

        # Si el patrón está ACTIVO, FORMÁNDOSE, es CARENCIA VIVA, ENTRADA PROFUNDA,
        # DOBLE TECHO/SUELO CON IMPULSO o espera nueva Pauta 1, nos quedamos aquí
        res["historial"] = historial
        return res

    # La cadena murió sin más P1 (o la zona se agotó con 3 engaños, Secc 15: el 4º
    # "obligaría al precio a salirse de la Zona de Decisión" — y salirse de la zona
    # ES el contexto del Engaño Extremo, Secc 17: "la última oportunidad"). En ambos
    # casos el límite exterior se sigue vigilando: sin esta vigilancia, un escape
    # cuyo pico queda fuera de la zona jamás genera P1 nuevo y es invisible.
    if nivel_anulacion is not None:
        HI, LO, zmax, _zmin, r, palabras = espacio_canonico(df, zona_max, zona_min, direction)
        anul = nivel_anulacion if direction == "SELL" else -nivel_anulacion
        etiqueta = ("ENGAÑO EXTREMO (tras zona agotada)" if numero_engano > 3
                    else "ENGAÑO EXTREMO (vigilancia de escape)")
        desde = max(ultimo_resultado.get("idx_muerte", ultimo_p1), 0)
        res_ee = vigilar_escape(df, HI, LO, zmax, anul, r, palabras, desde, etiqueta, historial)
        if res_ee is not None:
            res_ee["historial"] = historial
            return res_ee

    if numero_engano > 3:
        return {"estado": "ZONA_AGOTADA", "historial": historial,
                "mensaje": "Se rompieron 3 engaños. La zona ya no es válida para un 4to engaño (Descartada)."}

    ultimo_resultado["historial"] = historial
    return ultimo_resultado

# El escaneo de zonas reales vive en mdt_escaner.py (integración mapa->escáner);
# para pruebas manuales con zona/TF arbitrarias está _backtest_patron.py.
