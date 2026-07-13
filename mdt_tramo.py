# -*- coding: utf-8 -*-
"""EL MOTOR DEL TRAMO: puntos de control + ciclos vivos.

Aquí viven las dos primeras Reglas de Arquitectura (usuario, 3 jul 2026):

  Regla 1 — La resolución del mapa NO depende de la temporalidad que se opera:
  la cascada de extracción SIEMPRE baja hasta 1m. Un retroceso validado en una
  TF fina es invisible en velas gruesas (caso real: el 561.93 hallado en 3m
  enterró al 559.06 que el 15m daba por vivo).

  Regla 2 — El mapa es VIVO, no una foto: cada ciclo se sigue vela a vela
  (validación 1/3, desgrane, muerte en el 138.2, evolución, activación 38.2)
  desde su nacimiento hasta el instante que se reconstruye.
"""
import pandas as pd

from mdt_config import (SYMBOL, TF_LADDER, TF_MINUTOS, MIN_VELAS_TF,
                        MAX_VELAS_DESCARGA, GRADO_MIN_OPERABLE_PCT, NIVEL_618)
from mdt_feed import ahora, descargar, tf_para_span
from mdt_fractal import extraer_puntos_control
from mdt_math import evaluar_ciclo


def extraer_mapa_tramo(inicio, fin_limite, direction, cutoff=None, verbose=True,
                       symbol=SYMBOL, origen_fijo=None):
    """Cascada de extracción cronológica sobre un tramo (Regla 1).

    Cada TF más fina re-escanea TODO el tramo (hasta donde alcance su presupuesto
    de velas): un punto de control asesino puede esconderse dentro de CUALQUIER
    vela gruesa, no solo al final. Un zoom "desde el CP más profundo" se saltaba
    el escondite del 561.93 y el 559.06 revivía. La deduplicación por ancla y el
    desgrane posicional resuelven el solape entre temporalidades.

    fin_limite es cota EXCLUSIVA (None = hasta el cutoff/presente: el extremo es
    el extremo corrido, se mueve con el precio).

    origen_fijo=(precio, hora): el ANCLA QUE MARCÓ EL OPERADOR manda como origen
    (regla usuario 13 jul). Sin esto el origen se re-deducía del mínimo de la TF
    gruesa, y la vela gruesa que contiene el ancla empieza ANTES de la marca: se
    quedaba fuera y el origen se corría solo (ancla 560.58 -> ciclo 560.85, con
    todos los fibos desplazados casi 0.2).
    """
    bull = direction == "BULLISH"
    mapa, cronologia = [], []
    pendientes_por_trough = {}
    inicio_tramo = pd.Timestamp(inicio)
    limite = pd.Timestamp(fin_limite) if fin_limite is not None else (cutoff or ahora())
    origen_val = origen_time = extremo_val = extremo_time = tf_macro = None

    for tf in TF_LADDER:
        span_min = max((limite - inicio_tramo).total_seconds() / 60.0, 0)
        n_est = span_min / TF_MINUTOS[tf]
        if tf != TF_LADDER[-1] and n_est < MIN_VELAS_TF:
            continue  # tramo demasiado corto para esta TF: bajar a una más fina
        desde = inicio_tramo
        if n_est > MAX_VELAS_DESCARGA:
            desde = limite - pd.Timedelta(minutes=MAX_VELAS_DESCARGA * TF_MINUTOS[tf])
            if verbose:
                print(f"   [!] {tf}: tramo más largo que el presupuesto; se cubre desde {desde}")
        df_tf = descargar(tf, desde, cutoff, symbol)
        if fin_limite is not None:
            df_tf = df_tf[df_tf['open_time'] < pd.Timestamp(fin_limite)].reset_index(drop=True)
        if len(df_tf) < 6:
            continue

        if origen_fijo is not None:
            # El ancla del operador es el origen: la extracción arranca en su vela
            o_idx = int(df_tf['open_time'].searchsorted(pd.Timestamp(origen_fijo[1])))
            o_idx = min(max(o_idx, 0), len(df_tf) - 2)
        elif bull:
            o_idx = int(df_tf['low'].idxmin())
        else:
            o_idx = int(df_tf['high'].idxmax())
        e_idx = (int(df_tf.loc[o_idx:, 'high'].idxmax()) if bull
                 else int(df_tf.loc[o_idx:, 'low'].idxmin()))
        if e_idx <= o_idx:
            continue
        if tf_macro is None:
            tf_macro = tf
            if origen_fijo is not None:
                origen_val, origen_time = float(origen_fijo[0]), pd.Timestamp(origen_fijo[1])
            else:
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

        # Retrocesos pendientes (ruido: sin validar su 1/3) — candidatos a punto
        # de control. Dedupe entre TFs por el extremo; manda la medición con
        # mayor altura (el impulso real más grande visto).
        for p in res['pendientes']:
            p['tf'] = tf
            p['peak_time'] = df_tf.loc[p['peak_idx'], 'open_time']
            p['trough_time'] = df_tf.loc[p['trough_idx'], 'open_time']
            clave = round(p['trough'], 2)
            previo = pendientes_por_trough.get(clave)
            if previo is None or p['altura'] > previo['altura']:
                pendientes_por_trough[clave] = p

        for cpv in res['vivos']:
            cp = {'trough': cpv['trough'], 'grado': cpv['grado'], 'peak': cpv['peak'],
                  'tf': tf,
                  'trough_time': df_tf.loc[cpv['trough_idx'], 'open_time'],
                  'valid_time': df_tf.loc[cpv['valid_idx'], 'open_time']}
            # Las anclas gruesas reaparecen al re-escanear en fina: no duplicar
            if any(abs(x['trough'] - cp['trough']) < 1e-9 for x in mapa):
                continue
            # Un CP del pool con ancla posterior y grado mayor ya lo habría matado
            if any(x['trough_time'] > cp['trough_time'] and x['grado'] > cp['grado']
                   for x in mapa):
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
    # Un pendiente cuyo extremo coincide con un CP validado es la misma estructura
    anclas = {round(c['trough'], 2) for c in mapa}
    pendientes = sorted((p for k, p in pendientes_por_trough.items() if k not in anclas),
                        key=lambda p: p['altura'], reverse=True)
    return {'cps': mapa, 'cronologia': cronologia, 'pendientes': pendientes,
            'origen': origen_val, 'origen_time': origen_time,
            'extremo': extremo_val, 'extremo_time': extremo_time, 'tf_macro': tf_macro}


def _seguir_ciclos(ciclos, direction, cutoff, symbol):
    """Sigue cada ciclo vela a vela desde su ancla (Regla 2). Devuelve el precio
    de referencia (el cierre más reciente visto)."""
    por_tf = {}
    for c in ciclos:
        limite = cutoff or ahora()
        span_min = (limite - c['ancla_time']).total_seconds() / 60.0
        tf_eval = c['tf']
        if span_min / TF_MINUTOS[tf_eval] > MAX_VELAS_DESCARGA:
            tf_eval = tf_para_span(span_min)
        por_tf.setdefault(tf_eval, []).append(c)

    precio_ref = t_ref = None
    for tf_eval, lista in por_tf.items():
        desde = min(c['ancla_time'] for c in lista)
        df_eval = descargar(tf_eval, desde, cutoff, symbol)
        if len(df_eval) and (t_ref is None or df_eval['open_time'].iloc[-1] > t_ref):
            t_ref = df_eval['open_time'].iloc[-1]
            precio_ref = float(df_eval['close'].iloc[-1])
        for c in lista:
            idx0 = int(df_eval['open_time'].searchsorted(c['ancla_time']))
            c['eval'] = evaluar_ciclo(c['ancla'], df_eval, idx0, direction)
    return precio_ref


def _reset_618_del_tramo(ext, ciclos, direction, cutoff, symbol):
    """RESET 61.8 DEL TRAMO (regla usuario 10 jul; Secc 2).

    "Si el precio de algún tramo llega al 0.618 ya no hay puntos de control
    válidos": cuando el retroceso POSTERIOR al extremo cruza el 61.8 del impulso
    completo, los puntos de control internos mueren — queda solo el macro del
    tramo trabajando su Media (que empieza justo en ese 61.8).

    La extracción no puede verlo: el tramo se corta en su extremo. Por eso se
    comprueba aquí, con las velas posteriores.
    """
    ext['reset_618'] = None
    if (ext.get('extremo_time') is None or ext['extremo'] is None
            or ext['origen'] is None):
        return
    bull = direction == "BULLISH"
    imp = abs(ext['extremo'] - ext['origen'])
    if imp <= 0:
        return

    nivel618 = ext['extremo'] + imp * NIVEL_618 * (-1 if bull else 1)
    t_extremo = pd.Timestamp(ext['extremo_time'])
    limite = cutoff or ahora()
    span_min = max((limite - t_extremo).total_seconds() / 60.0, 1)
    tf_post = ext['tf_macro']
    if span_min / TF_MINUTOS[tf_post] > MAX_VELAS_DESCARGA:
        tf_post = tf_para_span(span_min)

    df_post = descargar(tf_post, t_extremo, cutoff, symbol)
    df_post = df_post[df_post['open_time'] > t_extremo]
    cruce = (df_post[df_post['low'] <= nivel618] if bull
             else df_post[df_post['high'] >= nivel618])
    if not len(cruce):
        return

    hora_reset = cruce['open_time'].iloc[0]
    ext['reset_618'] = {'nivel': nivel618, 'hora': hora_reset}
    for c in ciclos:
        ev = c.get('eval') or {}
        if not c['es_macro'] and ev.get('estado') == 'VIVO':
            c['eval'] = {**ev, 'estado': 'MUERTO', 'nivel_muerte': nivel618,
                         'hora_muerte': hora_reset, 'reset_tramo_618': True}


def analizar_tramo(nombre, inicio, fin_limite, direction, cutoff=None, verbose=True,
                   symbol=SYMBOL, origen_fijo=None):
    """Extrae los puntos de control del tramo (Regla 1) y sigue cada ciclo vela a
    vela hasta el cutoff/presente (Regla 2). Los ciclos que devuelve, con su
    estado, son la fuente ÚNICA de anclas para el escáner (Regla 3).

    origen_fijo=(precio, hora): el ancla que marcó el operador manda como origen
    del tramo (no se re-deduce del mínimo/máximo de la TF gruesa)."""
    ext = extraer_mapa_tramo(inicio, fin_limite, direction, cutoff, verbose, symbol,
                             origen_fijo)
    if ext['origen'] is None:
        return None

    ciclos = [{'nombre': f"Macro {nombre}", 'ancla': ext['origen'], 'grado': None,
               'tf': ext['tf_macro'], 'ancla_time': ext['origen_time'], 'es_macro': True}]
    for k, cp in enumerate(ext['cps'], start=1):
        ciclos.append({'nombre': f"Sub-C {nombre} Nivel {k}", 'ancla': cp['trough'],
                       'grado': cp['grado'], 'tf': cp['tf'],
                       'ancla_time': cp['trough_time'], 'es_macro': False})

    precio_ref = _seguir_ciclos(ciclos, direction, cutoff, symbol)
    _reset_618_del_tramo(ext, ciclos, direction, cutoff, symbol)

    # Capa operativa: solo son operables los ciclos con grado >= 1% del precio
    # ("no vamos a estar pendientes de esos miniciclos"). El macro siempre lo es.
    for c in ciclos:
        c['operable'] = c['es_macro'] or (
            precio_ref is not None and c['grado'] >= precio_ref * GRADO_MIN_OPERABLE_PCT)

    ext['ciclos'] = ciclos
    ext['precio_ref'] = precio_ref
    return ext
