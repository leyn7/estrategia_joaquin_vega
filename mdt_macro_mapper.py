# -*- coding: utf-8 -*-
"""Motor Estructural Universal MDT — mapa cronológico multi-tramo.

Tres reglas de arquitectura (usuario, 3 jul 2026):
 1. La resolución del mapa es independiente de la TF de operación: la cascada de
    extracción SIEMPRE baja hasta 1m en el tramo interno (fractalidad infinita: un
    retroceso validado en TF fina es invisible en velas gruesas — caso 561.93 en 3m
    enterrando al 559.06 del 15m).
 2. Mapa vivo: generar_mapa(cutoff) reconstruye el mapa exacto en cualquier instante;
    cada ciclo se sigue vela a vela (validación, desgrane, muerte 138.2, dilatación,
    activación 38.2) — nunca contra una foto fija.
 3. El mapa es la única fuente de anclas: el escáner debe consultar los ciclos
    devueltos (y su estado VIVO) antes de armar o disparar cualquier patrón.
"""
import pandas as pd
from mdt_data import get_binance_klines
from mdt_math import calc_zones, evaluar_ciclo, apply_concurrency, format_z
from mdt_fractal import extraer_puntos_control

from mdt_config import (SYMBOL, ORIGENES_MACRO_MANUAL, TF_LADDER, TF_MINUTOS,
                        MIN_VELAS_TF, MAX_VELAS_DESCARGA, GRADO_MIN_OPERABLE_PCT,
                        ZONA_MAX_OPERABLE_PCT, NIVEL_382, NIVEL_618)


def _ahora():
    return pd.Timestamp.now(tz='UTC').tz_localize(None)


def _descargar(tf, desde=None, cutoff=None, symbol=SYMBOL):
    start = pd.Timestamp(desde).tz_localize('UTC') if desde is not None else None
    df = get_binance_klines(symbol, tf, start_time=start)
    if cutoff is not None:
        df = df[df['open_time'] <= cutoff]
    return df.reset_index(drop=True)


def _origen_por_munecas(df_1d, ath_idx):
    """Muñecas rusas mecánicas (Secc 2) sobre el diario, acotadas al ATH.

    Cada vez que un retroceso supera el 61.8% del impulso corrido (origen ->
    máximo alcanzado), el fractal queda SELLADO y el mercado se re-funda en el
    fondo completo de ese retroceso ("el retroceso del fractal 1 se convierte
    en el impulso del fractal 2"). Solo cuentan como muñecas los sellos de
    ESCALA MACRO (impulso sellado >= 38.2% del impulso total del gráfico): un
    fractal minúsculo de la infancia del activo no es estructura mensual (caso
    ETHUSDT: un sello de 50 puntos a 3 días del listado NO re-funda el mapa).
    El origen macro elegido es la re-fundación macro cuyo impulso hasta el ATH
    es el mayor — "el impulso mayor absoluto del gráfico". Sin re-fundaciones
    macro (moneda joven en tendencia): el mínimo global.
    """
    lows, highs = df_1d['low'].values, df_1d['high'].values
    min_global = int(df_1d.loc[:ath_idx, 'low'].idxmin())
    imp_total = highs[ath_idx] - lows[min_global]
    o = min_global
    candidatos = []  # re-fundaciones nacidas de sellos de escala macro
    while True:
        p_val = lows[o]
        sello = None
        for i in range(o + 1, ath_idx + 1):
            if highs[i] > p_val:
                p_val = highs[i]
            if p_val > lows[o] and (p_val - lows[i]) / (p_val - lows[o]) > NIVEL_618:
                sello = i
                break
        if sello is None:
            break
        imp_sellado = p_val - lows[o]
        # fondo del retroceso: el mínimo hasta que el precio supere el extremo sellado
        fin_retro = ath_idx
        for j in range(sello, ath_idx + 1):
            if highs[j] > p_val:
                fin_retro = j
                break
        o = sello + int(lows[sello:fin_retro + 1].argmin())
        if imp_sellado >= NIVEL_382 * imp_total:
            candidatos.append((o, highs[ath_idx] - lows[o]))
    if candidatos:
        return max(candidatos, key=lambda c: c[1])[0]
    return min_global


def derivar_estructura_macro(df_1d, symbol=SYMBOL, verbose=True):
    """Deriva la estructura macro del gráfico (Secc 2): origen alcista, ATH y fondo.

    ATH = máximo absoluto del histórico disponible. Origen del macro alcista:
    banda manual del operador si existe (ORIGENES_MACRO_MANUAL — la biblia deja
    la elección de la muñeca al operador), o la derivación automática de
    _origen_por_munecas. Fondo = mínimo absoluto posterior al ATH (el retroceso
    del fractal vigente, que a su vez es el impulso del siguiente).
    """
    ath_idx = int(df_1d['high'].idxmax())
    fondo_idx = int(df_1d.loc[ath_idx:, 'low'].idxmin()) if ath_idx < len(df_1d) - 1 else None

    banda = ORIGENES_MACRO_MANUAL.get(symbol)
    if banda is not None:
        en_banda = df_1d[(df_1d['low'] > banda[0]) & (df_1d['low'] < banda[1])]
        if en_banda.empty:
            raise RuntimeError(f"No hay velas diarias de {symbol} con low en la banda manual {banda}. "
                               "Revisar ORIGENES_MACRO_MANUAL o dejar la derivación automática.")
        origen_idx = int(en_banda.index[-1])
        modo = f"manual (banda {banda})"
    elif ath_idx > 0:
        origen_idx = _origen_por_munecas(df_1d, ath_idx)
        modo = "auto (muñecas rusas Secc 2)"
    else:
        origen_idx, modo = None, "sin tramo alcista (ATH al inicio del histórico)"

    if verbose:
        o_txt = (f"{df_1d.loc[origen_idx, 'low']:.2f} @ {df_1d.loc[origen_idx, 'open_time'].date()}"
                 if origen_idx is not None else "—")
        f_txt = (f"{df_1d.loc[fondo_idx, 'low']:.2f} @ {df_1d.loc[fondo_idx, 'open_time'].date()}"
                 if fondo_idx is not None else "—")
        print(f"ESTRUCTURA MACRO {symbol}: origen {o_txt} [{modo}] | "
              f"ATH {df_1d.loc[ath_idx, 'high']:.2f} @ {df_1d.loc[ath_idx, 'open_time'].date()} | "
              f"fondo post-ATH {f_txt}")
    return {'origen_idx': origen_idx, 'ath_idx': ath_idx, 'fondo_idx': fondo_idx}


def _tf_para_span(span_min):
    """La TF más fina cuyo número de velas cabe en el presupuesto."""
    for tf in reversed(TF_LADDER):
        if span_min / TF_MINUTOS[tf] <= MAX_VELAS_DESCARGA:
            return tf
    return TF_LADDER[0]


def extraer_mapa_tramo(inicio, fin_limite, direction, cutoff=None, verbose=True, symbol=SYMBOL):
    """Cascada de extracción cronológica sobre un tramo (Regla 1).

    Cada TF más fina re-escanea TODO el tramo (o hasta donde alcance su presupuesto
    de velas): un punto de control asesino puede esconderse dentro de CUALQUIER vela
    gruesa del tramo, no solo al final (caso 561.93: con el tramo extendido al 3 jul,
    un zoom "desde el CP más profundo" se saltaba su escondite del 2 jul 08:30 y el
    559.06 revivía). La deduplicación por ancla y el desgrane posicional entre
    temporalidades resuelven el solape entre TFs.

    inicio / fin_limite / cutoff en UTC naive; fin_limite es cota EXCLUSIVA del tramo
    (None = hasta el cutoff/presente: el extremo es el extremo corrido).
    Devuelve {'cps', 'cronologia', 'origen', 'origen_time', 'extremo', 'tf_macro'}.
    """
    bull = direction == "BULLISH"
    mapa, cronologia = [], []
    pendientes_por_trough = {}
    inicio_tramo = pd.Timestamp(inicio)
    limite = pd.Timestamp(fin_limite) if fin_limite is not None else (cutoff or _ahora())
    origen_val = origen_time = extremo_val = extremo_time = tf_macro = None

    for tf in TF_LADDER:
        span_min = max((limite - inicio_tramo).total_seconds() / 60.0, 0)
        n_est = span_min / TF_MINUTOS[tf]
        if tf != TF_LADDER[-1] and n_est < MIN_VELAS_TF:
            continue  # tramo demasiado corto para esta TF: bajar directo a una más fina
        desde = inicio_tramo
        if n_est > MAX_VELAS_DESCARGA:
            desde = limite - pd.Timedelta(minutes=MAX_VELAS_DESCARGA * TF_MINUTOS[tf])
            if verbose:
                print(f"   [!] {tf}: tramo más largo que el presupuesto; se cubre desde {desde}")
        df_tf = _descargar(tf, desde, cutoff, symbol)
        if fin_limite is not None:
            df_tf = df_tf[df_tf['open_time'] < pd.Timestamp(fin_limite)].reset_index(drop=True)
        if len(df_tf) < 6:
            continue

        if bull:
            o_idx = int(df_tf['low'].idxmin())
            e_idx = int(df_tf.loc[o_idx:, 'high'].idxmax())
        else:
            o_idx = int(df_tf['high'].idxmax())
            e_idx = int(df_tf.loc[o_idx:, 'low'].idxmin())
        if e_idx <= o_idx:
            continue
        if tf_macro is None:
            tf_macro = tf
            origen_val = float(df_tf.loc[o_idx, 'low' if bull else 'high'])
            origen_time = df_tf.loc[o_idx, 'open_time']
        extremo_val = float(df_tf.loc[e_idx, 'high' if bull else 'low'])
        extremo_time = df_tf.loc[e_idx, 'open_time']

        if verbose:
            print(f"   >>> [{tf}] extracción desde {df_tf.loc[o_idx, 'open_time']} "
                  f"hasta {df_tf.loc[e_idx, 'open_time']}")
        res = extraer_puntos_control(df_tf, o_idx, e_idx, direction)

        for ev in res['eventos']:
            ev['tf'] = tf
            ev['time'] = df_tf.loc[ev['idx'], 'open_time']
            if 'trough_idx' in ev:
                ev['trough_time'] = df_tf.loc[ev['trough_idx'], 'open_time']
            cronologia.append(ev)

        # Retrocesos pendientes (ruido: sin validar su 1/3) — candidatos a punto de
        # control. Dedupe entre TFs por el extremo del retroceso; manda la medición
        # con mayor altura (el impulso real más grande visto).
        for p in res['pendientes']:
            p['tf'] = tf
            p['peak_time'] = df_tf.loc[p['peak_idx'], 'open_time']
            p['trough_time'] = df_tf.loc[p['trough_idx'], 'open_time']
            clave = round(p['trough'], 2)
            previo = pendientes_por_trough.get(clave)
            if previo is None or p['altura'] > previo['altura']:
                pendientes_por_trough[clave] = p

        for cpv in res['vivos']:
            cp = {'trough': cpv['trough'], 'grado': cpv['grado'], 'peak': cpv['peak'], 'tf': tf,
                  'trough_time': df_tf.loc[cpv['trough_idx'], 'open_time'],
                  'valid_time': df_tf.loc[cpv['valid_idx'], 'open_time']}
            # las anclas gruesas reaparecen al re-escanear en fina: no duplicar
            if any(abs(x['trough'] - cp['trough']) < 1e-9 for x in mapa):
                continue
            # un CP del pool con ancla posterior y grado mayor ya habría matado a este
            if any(x['trough_time'] > cp['trough_time'] and x['grado'] > cp['grado'] for x in mapa):
                continue
            for x in list(mapa):
                if x['trough_time'] < cp['trough_time'] and x['grado'] < cp['grado']:
                    cronologia.append({'tipo': 'MUERE', 'tf': tf, 'time': cp['valid_time'],
                                       'trough': x['trough'], 'grado': x['grado'],
                                       'causa': f"DESGRANE (cascada {x['tf']}->{tf})",
                                       'asesino': cp['trough'], 'grado_asesino': cp['grado']})
                    mapa.remove(x)
            mapa.append(cp)

    mapa.sort(key=lambda x: x['trough_time'])
    # Un pendiente cuyo extremo coincide con un CP ya validado es la misma estructura
    anclas = {round(c['trough'], 2) for c in mapa}
    pendientes = sorted((p for k, p in pendientes_por_trough.items() if k not in anclas),
                        key=lambda p: p['altura'], reverse=True)
    return {'cps': mapa, 'cronologia': cronologia, 'pendientes': pendientes,
            'origen': origen_val, 'origen_time': origen_time,
            'extremo': extremo_val, 'extremo_time': extremo_time, 'tf_macro': tf_macro}


def analizar_tramo(nombre, inicio, fin_limite, direction, cutoff=None, verbose=True, symbol=SYMBOL):
    """Extrae los puntos de control del tramo (Regla 1) y sigue cada ciclo vela a vela
    hasta el cutoff/presente (Regla 2). Devuelve los ciclos con su estado — la fuente
    única de anclas para el escáner (Regla 3)."""
    ext = extraer_mapa_tramo(inicio, fin_limite, direction, cutoff, verbose, symbol)
    if ext['origen'] is None:
        return None

    ciclos = [{'nombre': f"Macro {nombre}", 'ancla': ext['origen'], 'grado': None,
               'tf': ext['tf_macro'], 'ancla_time': ext['origen_time'], 'es_macro': True}]
    for k, cp in enumerate(ext['cps'], start=1):
        ciclos.append({'nombre': f"Sub-C {nombre} Nivel {k}", 'ancla': cp['trough'],
                       'grado': cp['grado'], 'tf': cp['tf'], 'ancla_time': cp['trough_time'],
                       'es_macro': False})

    # Evaluación cronológica de cada ciclo: una descarga por TF desde el ancla más antigua
    por_tf = {}
    for c in ciclos:
        limite = cutoff or _ahora()
        span_min = (limite - c['ancla_time']).total_seconds() / 60.0
        tf_eval = c['tf']
        if span_min / TF_MINUTOS[tf_eval] > MAX_VELAS_DESCARGA:
            tf_eval = _tf_para_span(span_min)
        por_tf.setdefault(tf_eval, []).append(c)
    precio_ref = None
    t_ref = None
    for tf_eval, lista in por_tf.items():
        desde = min(c['ancla_time'] for c in lista)
        df_eval = _descargar(tf_eval, desde, cutoff, symbol)
        if len(df_eval) and (t_ref is None or df_eval['open_time'].iloc[-1] > t_ref):
            t_ref = df_eval['open_time'].iloc[-1]
            precio_ref = float(df_eval['close'].iloc[-1])
        for c in lista:
            idx0 = int(df_eval['open_time'].searchsorted(c['ancla_time']))
            c['eval'] = evaluar_ciclo(c['ancla'], df_eval, idx0, direction)

    # --- RESET 61.8 DEL TRAMO (regla usuario 10 jul; Secc 2) ---
    # "Si el precio de algún tramo llega al 0.618 ya no hay puntos de control
    # válidos": cuando el retroceso POSTERIOR al extremo del tramo cruza el
    # 61.8 del impulso completo (origen -> extremo), los puntos de control
    # internos dejan de ser válidos — queda solo el macro del tramo trabajando
    # su Media (que empieza justo en ese 61.8). La extracción no lo ve porque
    # el tramo se corta en su extremo; se verifica aquí con las velas post-extremo.
    ext['reset_618'] = None
    if (ext.get('extremo_time') is not None and ext['extremo'] is not None
            and ext['origen'] is not None):
        bull = direction == "BULLISH"
        imp = abs(ext['extremo'] - ext['origen'])
        if imp > 0:
            nivel618 = ext['extremo'] + imp * NIVEL_618 * (-1 if bull else 1)
            t_extremo = pd.Timestamp(ext['extremo_time'])
            limite = cutoff or _ahora()
            span_min = max((limite - t_extremo).total_seconds() / 60.0, 1)
            tf_post = ext['tf_macro']
            if span_min / TF_MINUTOS[tf_post] > MAX_VELAS_DESCARGA:
                tf_post = _tf_para_span(span_min)
            df_post = _descargar(tf_post, t_extremo, cutoff, symbol)
            df_post = df_post[df_post['open_time'] > t_extremo]
            cruce = (df_post[df_post['low'] <= nivel618] if bull
                     else df_post[df_post['high'] >= nivel618])
            if len(cruce):
                hora_reset = cruce['open_time'].iloc[0]
                ext['reset_618'] = {'nivel': nivel618, 'hora': hora_reset}
                for c in ciclos:
                    ev = c.get('eval') or {}
                    if not c['es_macro'] and ev.get('estado') == 'VIVO':
                        c['eval'] = {**ev, 'estado': 'MUERTO', 'nivel_muerte': nivel618,
                                     'hora_muerte': hora_reset, 'reset_tramo_618': True}

    # Capa operativa: grado mínimo del 1% del precio (el macro siempre es operable)
    for c in ciclos:
        c['operable'] = c['es_macro'] or (precio_ref is not None and
                                          c['grado'] >= precio_ref * GRADO_MIN_OPERABLE_PCT)

    ext['ciclos'] = ciclos
    ext['precio_ref'] = precio_ref
    return ext


def _registrar_ciclo(c, direction, buys, sells, alerts, verbose=True):
    """Registra las zonas operativas (o la alerta) de un ciclo según su estado.

    Reparto: BULLISH -> Compras: Baja y Media | Ventas: Alta
             BEARISH -> Compras: Baja | Ventas: Alta y Media
    """
    ev = c['eval']
    nombre = c['nombre']
    etiqueta = f"[{nombre.upper()} ({c['tf'].upper()})] ancla {c['ancla']:.2f}"

    if not c.get('operable', True) and ev['estado'] != 'MUERTO':
        if verbose:
            print(f"{etiqueta} -> SUB-OPERABLE (grado {c['grado']:.2f} < 1% del precio): "
                  f"vive en el motor, sin zonas operativas")
        return

    if ev['estado'] == 'MUERTO':
        if verbose:
            causa = ("RESET 61.8 del tramo" if ev.get('reset_tramo_618') else "tocó su 138.2")
            print(f"{etiqueta} -> MUERTO: {causa} ({ev['nivel_muerte']:.2f}) el {ev['hora_muerte']}")
        return
    if ev['estado'] == 'SIN_IMPULSO':
        if verbose:
            print(f"{etiqueta} -> sin impulso medible todavía")
        return

    z = ev['zonas']
    detalle = f"fin {ev['fin_vigente']:.2f}"
    if ev['evolucionado']:
        detalle += f" | EVOLUCIONADO: re-anclado en {ev['origen_vigente']:.2f} (ciclo mayor)"
    if ev['en_excursion']:
        if ev.get('zona_origen_en_trabajo'):
            # Sección 4/8: el primer 19.1% más allá del origen es la zona del origen
            # (Parte Alta en bajista, Parte Baja en alcista). Zona operativa en
            # trabajo; las zonas internas del ciclo se borran.
            peso = c['peso']
            # La zona del origen es operativa desde que abrió la excursión (Secc 8):
            # el escáner solo debe mirar velas de este episodio de trabajo. Su
            # anulación (Secc 17) es la muerte del ciclo (el ±38.2 fijo).
            # TP (Secc 8): al trabajar la Parte Alta/Baja, el objetivo es la Zona
            # del 61.8% de Alerta del nuevo Fibo Mayor (extremo excursión -> fin).
            tp_zona = calc_zones(ev['extremo_excursion'], ev['fin_vigente'], direction)['MEDIA']
            extra = {"tf": c['tf'], "ancla": c['ancla'],
                     "ciclo_origen": ev['origen_vigente'], "ciclo_fin": ev['fin_vigente'],
                     "operativa_desde": ev.get('hora_excursion'),
                     "nivel_anulacion": ev['nivel_muerte'],
                     "tp_zona": tp_zona}
            if direction == "BULLISH":
                caja = z['BAJA']
                buys.append({"name": f"{nombre} (Baja)", "z": caja, "peso": peso, **extra})
                lado = "PARTE BAJA (Compras)"
            else:
                caja = z['ALTA']
                sells.append({"name": f"{nombre} (Alta)", "z": caja, "peso": peso, **extra})
                lado = "PARTE ALTA (Ventas)"
            if verbose:
                print(f"{etiqueta} -> {detalle} | TRABAJANDO {lado}: {min(caja):.2f} a {max(caja):.2f} "
                      f"| muerte del ciclo en {ev['nivel_muerte']:.2f} "
                      f"| evolución a ciclo mayor si toca {ev['evolucion_38_2']:.2f}")
        elif verbose:
            print(f"{etiqueta} -> {detalle} | EN ZONA DE INDECISIÓN (superó el 19.1% del origen): "
                  f"inoperable | muerte del ciclo en {ev['nivel_muerte']:.2f} "
                  f"| evolución a ciclo mayor si toca {ev['evolucion_38_2']:.2f}")
        return
    if not ev['activado']:
        tipo = "COMPRAS" if direction == "BULLISH" else "VENTAS"
        alerts.append({'name': nombre, 'activacion': ev['nivel_activacion'],
                       'zona_alerta': z['MEDIA'], 'tipo': tipo})
        if verbose:
            print(f"{etiqueta} -> {detalle} | EN ALERTA: se activa al tocar su 38.2 ({ev['nivel_activacion']:.2f})")
        return

    if verbose:
        media_txt = " | media MUERTA (tocó el 100%)" if ev['media_muerta'] else ""
        cand_txt = (f" | medida candidata hasta {ev['fin_candidato']:.2f} "
                    f"(nace en {ev['activacion_candidata']:.2f})"
                    if ev.get('fin_candidato') is not None else "")
        print(f"{etiqueta} -> {detalle} | ACTIVADO ({ev['hora_activacion']}){media_txt}{cand_txt}")
    if ev.get('fin_candidato') is not None:
        # Extremo nuevo tras la activación (Secc 4/6): la medida vigente sigue
        # operativa (el precio arriba del fin es el trabajo de la Alta); la
        # medida candidata nace si el precio toca SU 38.2 — va como alerta.
        tipo_cand = "COMPRAS" if direction == "BULLISH" else "VENTAS"
        z_cand = calc_zones(ev['origen_vigente'], ev['fin_candidato'], direction)
        alerts.append({'name': f"{nombre} (nueva medida {ev['fin_candidato']:.2f})",
                       'activacion': ev['activacion_candidata'],
                       'zona_alerta': z_cand['MEDIA'], 'tipo': tipo_cand})
    peso = c['peso']
    # Las zonas existen desde la ACTIVACIÓN del ciclo (tocó su 38.2, Secc 3): el
    # escáner de patrones solo debe mirar velas desde entonces (Secc 13, checklist 1:
    # "el precio está operando dentro de una Zona de Decisión ACTIVA").
    extra = {"tf": c['tf'], "ancla": c['ancla'],
             "ciclo_origen": ev['origen_vigente'], "ciclo_fin": ev['fin_vigente'],
             "operativa_desde": ev.get('hora_activacion')}
    # Anulación de cada zona (Secc 4/17): el siguiente nivel fibo que la mata.
    # Baja -> extensión 138.2 | Media -> el origen (100%) | Alta -> extensión -38.2.
    # TP de las MEDIAS (Secc 7.2): "la zona contraria más alejada" DEL MISMO CICLO.
    # TP de las zonas del LADO DEL FIN (Alta alcista / Baja bajista — el
    # contra-movimiento; regla usuario 12 jul): al ir la operación, el precio
    # activa la medida nueva del ciclo tocando su 38.2 — el objetivo es la
    # MEDIA (zona 61.8) de esa medida que se forma (vigente o candidata),
    # dinámica. La zona contraria lejana es el "máximo potencial" del mapa,
    # no el TP operativo. (Caso M5: venta EE 582.05 -> la caída activó la
    # medida 560.85->583.42 en 574.80 y el objetivo era su Media 569.47-565.16;
    # el precio llegó a 570.52.)
    origen, fin, imp = z['origen'], z['fin'], z['impulse']
    fin_tp = ev.get('fin_candidato') if ev.get('fin_candidato') is not None else ev['fin_vigente']
    media_medida_nueva = calc_zones(ev['origen_vigente'], fin_tp, direction)['MEDIA']
    if direction == "BULLISH":
        anul = {"BAJA": origen - imp * 0.382, "MEDIA": origen, "ALTA": fin + imp * 0.382}
        buys.append({"name": f"{nombre} (Baja)", "z": z['BAJA'], "peso": peso,
                     "nivel_anulacion": anul["BAJA"], "tp_zona": z['ALTA'], **extra})
        if not ev['media_muerta']:
            buys.append({"name": f"{nombre} (Media)", "z": z['MEDIA'], "peso": peso,
                         "nivel_anulacion": anul["MEDIA"], "tp_zona": z['ALTA'], **extra})
        sells.append({"name": f"{nombre} (Alta)", "z": z['ALTA'], "peso": peso,
                      "nivel_anulacion": anul["ALTA"], "tp_zona": media_medida_nueva, **extra})
    else:
        anul = {"ALTA": origen + imp * 0.382, "MEDIA": origen, "BAJA": fin - imp * 0.382}
        buys.append({"name": f"{nombre} (Baja)", "z": z['BAJA'], "peso": peso,
                     "nivel_anulacion": anul["BAJA"], "tp_zona": media_medida_nueva, **extra})
        sells.append({"name": f"{nombre} (Alta)", "z": z['ALTA'], "peso": peso,
                      "nivel_anulacion": anul["ALTA"], "tp_zona": z['BAJA'], **extra})
        if not ev['media_muerta']:
            sells.append({"name": f"{nombre} (Media)", "z": z['MEDIA'], "peso": peso,
                          "nivel_anulacion": anul["MEDIA"], "tp_zona": z['BAJA'], **extra})


def resolver_concurrencia(zonas, buy_or_sell, current_price=None, verbose=True):
    """Aplica la concurrencia global (la zona de mayor peso manda) y devuelve las supervivientes.

    Excepción de la Zona en Trabajo (fractalidad infinita, Sección 3 Caso 2): la zona mayor
    que CONTIENE actualmente al precio es el campo de trabajo — no elimina a los sub-ciclos
    que nacen dentro de ella; esos sub-ciclos son la vía operativa del trabajo de la mayor.
    """
    if buy_or_sell == "BUY":
        zonas = sorted(zonas, key=lambda x: max(x['z']), reverse=True)
    else:
        zonas = sorted(zonas, key=lambda x: min(x['z']))

    finales = []
    for i in range(len(zonas)):
        current = zonas[i]
        if current['z'] is None: continue
        for j in range(len(zonas)):
            if i == j: continue
            otro = zonas[j]
            if otro['z'] is None: continue
            if current_price is not None and min(otro['z']) <= current_price <= max(otro['z']):
                continue  # la mayor está en trabajo (precio dentro): no tritura sub-ciclos
            if otro['peso'] > current['peso']:
                new_z, razon = apply_concurrency(otro['z'], current['z'], buy_or_sell)
                if verbose and new_z != current['z']:
                    print(f"[{current['name']} vs {otro['name']}] -> {razon}")
                current['z'] = new_z
                if current['z'] is None:
                    break
        if current['z'] is not None:
            finales.append(current)
    return finales


def _auditar_ultimo_ciclo(ciclos, buys, sells, precio, verbose=True):
    """Auditoría del último ciclo (regla usuario 7 jul 2026).

    El último punto de control que activa zonas (el ancla más reciente del mapa)
    es siempre el ciclo más pequeño de la estructura: sus zonas deben auditarse
    contra las concurrencias del ciclo anterior SIN privilegios — aquí el TOQUE
    cuenta como concurrencia (Secc 19: "se superponen o se tocan") y no aplica
    la excepción de zona-en-trabajo. Toda zona suya que toque o solape una zona
    de la misma dirección de un ciclo anterior se elimina (la Zona Mayor manda).
    Si pierde todas sus zonas, el ancla no sirve (caso real: la muñeca M5 573.21
    fabricaba Media/Baja de 2.4 pegadas a las Medias del 568.58 y el 556.45).

    Calibración con datos (7 jul): el TOQUE exacto en el borde solo mata a las
    MUÑECAS ANIDADAS — sus zonas tejen contra la estructura madre por
    construcción. Un CP normal que apenas toca en el borde convive (espíritu
    Caso 2: la Parte Alta del 572.71 del 3 jul tocaba la Media del 602.79 y fue
    una venta ganadora); para él solo elimina el solape real.
    """
    t_por_ciclo = {}
    for c in ciclos:
        if c.get('ancla') is not None and c.get('ancla_time') is not None:
            k = (round(c['ancla'], 2), c.get('tf'))
            if k not in t_por_ciclo or c['ancla_time'] > t_por_ciclo[k][0]:
                t_por_ciclo[k] = (c['ancla_time'], bool(c.get('muneca')))

    def info_de(z):
        return t_por_ciclo.get((round(z['ancla'], 2), z.get('tf'))) if z.get('ancla') is not None else None

    def t_de(z):
        i = info_de(z)
        return i[0] if i else None

    tiempos = [t_de(z) for z in buys + sells]
    tiempos = [t for t in tiempos if t is not None]
    if not tiempos:
        return buys, sells
    t_ultimo = max(tiempos)

    quedan_del_ultimo = 0
    ancla_ultimo = None
    resultado = []
    for lista in (sells, buys):
        finales = []
        for z in lista:
            t = t_de(z)
            if t != t_ultimo:
                finales.append(z)
                continue
            ancla_ultimo = z['ancla']
            zmax, zmin = max(z['z']), min(z['z'])
            es_muneca = (info_de(z) or (None, False))[1]
            # Choca solo contra zonas OPERATIVAS de ciclos anteriores: las zonas
            # macro de contexto (más anchas que el % del precio) cubren medio
            # gráfico y no son la concurrencia del "ciclo anterior".
            # Muñeca anidada: el toque en el borde cuenta (<=). CP normal: solo
            # el solape real (<) — el toque exacto convive (Caso 2).
            if es_muneca:
                toca = lambda o: min(o['z']) <= zmax and zmin <= max(o['z'])
            else:
                toca = lambda o: min(o['z']) < zmax and zmin < max(o['z'])
            choque = next((o for o in lista if o is not z and t_de(o) is not None
                           and t_de(o) < t_ultimo
                           and (max(o['z']) - min(o['z'])) <= precio * ZONA_MAX_OPERABLE_PCT
                           and toca(o)), None)
            if choque is not None:
                if verbose:
                    print(f"[AUDITORÍA ÚLTIMO CICLO] {z['name']} {zmax:.2f}-{zmin:.2f} "
                          f"ELIMINADA: toca/solapa {choque['name']} "
                          f"{max(choque['z']):.2f}-{min(choque['z']):.2f} (la mayor manda)")
                continue
            quedan_del_ultimo += 1
            finales.append(z)
        resultado.append(finales)
    if verbose and ancla_ultimo is not None and quedan_del_ultimo == 0:
        print(f"[AUDITORÍA ÚLTIMO CICLO] el ancla {ancla_ultimo:.2f} queda SIN zonas: no sirve")
    return resultado[1], resultado[0]


def generar_mapa(cutoff=None, verbose=True, symbol=SYMBOL):
    """Reconstruye el mapa completo en el instante `cutoff` (Regla 2; None = ahora).

    Devuelve {'ciclos', 'buys', 'sells', 'alerts', 'precio'}: los ciclos traen estado
    (VIVO/MUERTO, activación, dilatación) — Regla 3: el escáner opera SOLO anclas de
    ciclos VIVOS de esta estructura.

    Las rutas salen de la estructura macro derivada del diario (Secc 2): el
    impulso mayor hasta el ATH (alcista), su retroceso (bajista) y el retroceso
    de ese retroceso (post-fondo) — las tres muñecas vigentes. Los tramos que no
    existen en el gráfico (moneda en su ATH, ATH al inicio del histórico) se
    omiten solos.
    """
    if verbose:
        print("\n" + "=" * 70)
        print(f" MOTOR ESTRUCTURAL UNIVERSAL MDT — {symbol} (MAPA CRONOLÓGICO, CASCADA A 1M)")
        print("=" * 70 + "\n")

    df_1d = _descargar("1d", None, cutoff, symbol)
    if len(df_1d) < 2:
        raise RuntimeError(f"Sin histórico diario suficiente para {symbol}.")

    est = derivar_estructura_macro(df_1d, symbol, verbose)
    ath_idx, origen_idx, fondo_idx = est['ath_idx'], est['origen_idx'], est['fondo_idx']

    un_dia = pd.Timedelta(days=1)
    rutas = []
    if origen_idx is not None and ath_idx > origen_idx:
        rutas.append(("Alcista", df_1d.loc[origen_idx, 'open_time'],
                      df_1d.loc[ath_idx, 'open_time'] + un_dia, "BULLISH", 100))
    if fondo_idx is not None and fondo_idx > ath_idx:
        rutas.append(("Bajista", df_1d.loc[ath_idx, 'open_time'],
                      df_1d.loc[fondo_idx, 'open_time'] + un_dia, "BEARISH", 100))
        rutas.append(("Alcista Post-F", df_1d.loc[fondo_idx, 'open_time'], None, "BULLISH", 96))

    buys, sells, alerts, ciclos_todos, tramos = [], [], [], [], []

    def _acumular_tramo(nombre, direction, res, buys_r, sells_r, alerts_r):
        """Guarda la vista independiente del tramo (Secc 2: cada muñeca es un
        mapa 100% correcto por sí misma — regla usuario 10 jul: "cada tramo sea
        mirado y operado por separado"). Copias superficiales: la concurrencia
        GLOBAL muta las zonas del mapa unificado y no debe tocar esta vista."""
        buys.extend(buys_r)
        sells.extend(sells_r)
        alerts.extend(alerts_r)
        tramos.append({'nombre': nombre, 'direction': direction,
                       'origen': res['origen'], 'extremo': res['extremo'],
                       'origen_time': res['origen_time'], 'ciclos': res['ciclos'],
                       'reset_618': res.get('reset_618'),
                       'buys': [{**z} for z in buys_r], 'sells': [{**z} for z in sells_r],
                       'alerts': list(alerts_r)})

    res_prev = fin_prev = dir_prev = peso_prev = None
    for nombre, ini, fin, direction, peso_base in rutas:
        if verbose:
            print(f"\n--- RUTA {nombre.upper()} ({direction}) ---")
        res = analizar_tramo(nombre, ini, fin, direction, cutoff, verbose, symbol)
        if res is None:
            continue
        buys_r, sells_r, alerts_r = [], [], []
        for j, c in enumerate(res['ciclos']):
            c['peso'] = peso_base - j
            c['ruta'] = nombre
            c['direction'] = direction
            ciclos_todos.append(c)
            _registrar_ciclo(c, direction, buys_r, sells_r, alerts_r, verbose)
        _acumular_tramo(nombre, direction, res, buys_r, sells_r, alerts_r)
        res_prev, fin_prev, dir_prev, peso_prev = res, fin, direction, peso_base

    # --- Muñecas anidadas (Secc 2, regla usuario 6 jul 2026) ---
    # "El retroceso de este gran fractal 1 se convierte automáticamente en el
    # impulso del fractal 2": el desgrane no termina en las 3 muñecas del diario.
    # El retroceso corrido del impulso de la última ruta abierta es la siguiente
    # muñeca (ej. el retroceso del rebote post-fondo = ciclo bajista desde su
    # tope). Los ciclos pequeños, si hacen lo que se espera en sus zonas, también
    # son operables — el corte es la escala mínima operable (grado >= 1% del
    # precio, misma regla de la capa operativa).
    n_muneca = len(rutas) + 1
    while (res_prev is not None and fin_prev is None and n_muneca <= 8
           and res_prev.get('extremo_time') is not None):
        direction = "BEARISH" if dir_prev == "BULLISH" else "BULLISH"
        nombre = f"{'Bajista' if direction == 'BEARISH' else 'Alcista'} M{n_muneca}"
        peso_base = peso_prev - 4
        if verbose:
            print(f"\n--- RUTA {nombre.upper()} ({direction}, muñeca anidada) ---")
        res = analizar_tramo(nombre, res_prev['extremo_time'], None, direction,
                             cutoff, verbose, symbol)
        if res is None or res.get('extremo') is None:
            break
        grado_ruta = abs(res['origen'] - res['extremo'])
        precio_ref = res.get('precio_ref')
        if precio_ref is None or grado_ruta < precio_ref * GRADO_MIN_OPERABLE_PCT:
            if verbose:
                print(f"   (retroceso {grado_ruta:.2f} < {GRADO_MIN_OPERABLE_PCT:.0%} "
                      f"del precio: fin de las muñecas anidadas)")
            break
        buys_r, sells_r, alerts_r = [], [], []
        for j, c in enumerate(res['ciclos']):
            c['peso'] = peso_base - j
            c['ruta'] = nombre
            c['direction'] = direction
            c['muneca'] = True  # ruta anidada (Secc 2): sus zonas tejen contra la madre
            ciclos_todos.append(c)
            _registrar_ciclo(c, direction, buys_r, sells_r, alerts_r, verbose)
        _acumular_tramo(nombre, direction, res, buys_r, sells_r, alerts_r)
        res_prev, dir_prev, peso_prev = res, direction, peso_base
        n_muneca += 1

    current_price = float(df_1d.iloc[-1]['close'])

    if verbose:
        print("\n--- CONCURRENCIA GLOBAL DE ZONAS ACTIVAS ---")
        print("\n[ZONAS DE COMPRAS]")
    final_buys = resolver_concurrencia(buys, "BUY", current_price, verbose)
    if verbose:
        print("\n[ZONAS DE VENTAS]")
    final_sells = resolver_concurrencia(sells, "SELL", current_price, verbose)

    # Regla 7 jul: el último ciclo del mapa se audita contra las concurrencias
    # de los anteriores (toque = concurrencia, sin excepción de zona-en-trabajo)
    final_buys, final_sells = _auditar_ultimo_ciclo(ciclos_todos, final_buys,
                                                    final_sells, current_price, verbose)

    if verbose:
        print("\n--- ZONAS OPERATIVAS FINALES ---")
        print("ZONAS DE VENTAS:")
        for s in final_sells:
            print(f" -> {s['name']}: {format_z(s['z'])}")
        print("\nZONAS DE COMPRAS:")
        for b in final_buys:
            print(f" -> {b['name']}: {format_z(b['z'])}")
        if alerts:
            print("\n--- ZONAS EN EVOLUCION (ALERTAS NO ACTIVADAS) ---")
            for a in alerts:
                print(f" -> {a['name']}: Si el precio toca {a['activacion']:.2f} (38.2%), "
                      f"se activará Zona de {a['tipo']} en {format_z(a['zona_alerta'])}")
        print(f"\nPRECIO ACTUAL: {current_price:.2f}")

    return {'ciclos': ciclos_todos, 'buys': final_buys, 'sells': final_sells,
            'alerts': alerts, 'precio': current_price, 'tramos': tramos}


def zonas_finales_tramo(t, precio):
    """Zonas finales de UN tramo tras la concurrencia INTERNA (Secc 19 solo
    entre sus ciclos — regla usuario: cada tramo independiente). Copias: la
    resolución muta las zonas y la vista del tramo no debe tocarse."""
    out = []
    for lado, key in (("SELL", 'sells'), ("BUY", 'buys')):
        copias = [{**z} for z in t.get(key, [])]
        for z in resolver_concurrencia(copias, lado, precio, verbose=False):
            out.append((lado, z))
    return out


def reporte_tramos(mapa):
    """Vista de tramos INDEPENDIENTES (Secc 2 + reglas usuario 10 jul: "cada
    tramo sea mirado y operado por separado" / "me interesa saber si hay ciclos
    que tengan zonas operables, omitir los que no").

    Por cada tramo (muñeca): se aplica la concurrencia de zonas (Secc 19) SOLO
    entre los ciclos del tramo y se listan ÚNICAMENTE los ciclos que conservan
    al menos una zona útil (Secc 6: ciclo útil mientras tenga >=1 zona útil),
    con sus zonas debajo. Los vivos que quedaron sin zona útil se omiten (línea
    resumen con el motivo). Cierra con la posición del precio respecto a las
    zonas de ESE tramo (dentro / la más próxima). Devuelve el texto.
    """
    precio = mapa['precio']
    lineas = [f"MAPA POR TRAMOS INDEPENDIENTES | precio {precio:.2f}"]
    for t in mapa.get('tramos', []):
        sentido = "alcista" if t['direction'] == 'BULLISH' else "bajista"
        lineas.append("")
        lineas.append(f"=== {t['nombre'].upper()} ({sentido}): {t['origen']:.2f} -> {t['extremo']:.2f} ===")
        if t.get('reset_618'):
            r = t['reset_618']
            lineas.append(f"  RESET 61.8 DEL TRAMO: el retroceso cruzó {r['nivel']:.2f} — "
                          "los puntos de control internos ya NO son válidos; queda solo "
                          "el macro del tramo trabajando su Media.")
        vivos = [c for c in t['ciclos'] if c.get('eval', {}).get('estado') == 'VIVO']
        muertos = sum(1 for c in t['ciclos'] if c.get('eval', {}).get('estado') == 'MUERTO')
        if not vivos:
            lineas.append(f"  Sin puntos de control vivos ({muertos} muertos): sin estructura vigente.")
            continue

        # Concurrencia de zonas del tramo (Secc 19, solo entre SUS ciclos)
        zonas_t = zonas_finales_tramo(t, precio)
        por_ancla = {}
        for lado, z in zonas_t:
            if z.get('ancla') is not None:
                por_ancla.setdefault(round(z['ancla'], 2), []).append((lado, z))

        def _estado_ciclo(c):
            ev = c['eval']
            if ev.get('en_excursion'):
                return ("TRABAJANDO parte " + ("baja" if t['direction'] == 'BULLISH' else "alta")
                        if ev.get('zona_origen_en_trabajo') else "en indecisión")
            if ev.get('activado'):
                return "ACTIVADO" + (" | EVOLUCIONADO" if ev.get('evolucionado') else "")
            return f"en alerta (38.2 en {ev['nivel_activacion']:.2f})"

        operables, omitidos = [], []
        for c in vivos:
            zonas_c = por_ancla.get(round(c['ancla'], 2), [])
            if zonas_c:
                operables.append((c, zonas_c))
            else:
                ev = c['eval']
                if not c.get('operable', True):
                    motivo = "sub-operable <1%"
                elif not ev.get('activado') and not ev.get('en_excursion'):
                    motivo = f"en alerta (38.2 en {ev['nivel_activacion']:.2f})"
                elif ev.get('en_excursion') and not ev.get('zona_origen_en_trabajo'):
                    motivo = "en indecisión"
                else:
                    motivo = "zonas tejidas por la concurrencia"
                omitidos.append(f"{c['ancla']:.2f} ({motivo})")

        dentro, fuera = [], []
        if operables:
            lineas.append(f"  CICLOS CON ZONAS OPERABLES (concurrencia Secc 19 aplicada; "
                          f"{muertos} CPs muertos):")
            for c, zonas_c in operables:
                grado = f"grado {c['grado']:.2f}" if c['grado'] is not None else "macro del tramo"
                lineas.append(f"   - Ciclo {c['ancla']:.2f} ({c['tf']}, {grado}) {_estado_ciclo(c)}:")
                for lado, z in sorted(zonas_c, key=lambda x: -max(x[1]['z'])):
                    zmax, zmin = max(z['z']), min(z['z'])
                    accion = "VENTAS" if lado == "SELL" else "COMPRAS"
                    banda = z['name'].rsplit('(', 1)[-1].rstrip(')') if '(' in z['name'] else '?'
                    if zmin <= precio <= zmax:
                        dentro.append((lado, z))
                        marca = "  <<< PRECIO DENTRO"
                    else:
                        dist = (zmin - precio) if precio < zmin else (precio - zmax)
                        fuera.append((dist, accion, z))
                        marca = f"  (a {dist:.2f} | {dist / precio:.1%})"
                    lineas.append(f"       [{accion}] {banda}: {zmax:.2f} a {zmin:.2f}{marca}")
        else:
            lineas.append("  Ningún ciclo del tramo conserva zonas operables ahora.")
        if omitidos:
            lineas.append(f"  Omitidos sin zona útil: {', '.join(omitidos)}")
        if dentro:
            lados = sorted({'VENTAS' if l == 'SELL' else 'COMPRAS' for l, _ in dentro})
            lineas.append(f"  >> EL PRECIO ESTÁ EN ZONA de este tramo: buscar patrón de "
                          f"{'/'.join(lados)} (3 Pautas, Secc 9).")
        elif fuera:
            d, accion, z = min(fuera, key=lambda x: x[0])
            lineas.append(f"  >> Próxima zona del tramo: {z['name']} ({accion}) "
                          f"a {d:.2f} ({d / precio:.1%}).")
        for a in t.get('alerts', []):
            lineas.append(f"   [ALERTA 38.2] {a['name']}: si toca {a['activacion']:.2f} "
                          f"activa zona de {a['tipo']}")
    return '\n'.join(lineas)


def ancla_viva(mapa, ancla, tol=1e-6):
    """Regla 3 (candado mapa->escáner): ¿el ancla sigue siendo un ciclo VIVO del mapa?"""
    return any(abs(c['ancla'] - ancla) <= tol and c['eval']['estado'] == 'VIVO'
               for c in mapa['ciclos'])


if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--symbol", default=SYMBOL)
    # parse_known_args: _backtest_mapper.py re-ejecuta este __main__ con su propio
    # argv posicional (el cutoff) — se ignora aquí sin romper la compatibilidad
    _args, _ = _ap.parse_known_args()
    generar_mapa(symbol=_args.symbol.upper())
