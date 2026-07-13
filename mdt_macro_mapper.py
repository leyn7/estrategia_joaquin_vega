# -*- coding: utf-8 -*-
"""MOTOR ESTRUCTURAL MDT — ensamblaje del mapa completo.

Este archivo solo ORQUESTA; cada pieza vive en su módulo:
  mdt_feed.py        acceso a las velas (con time-travel)
  mdt_estructura.py  dónde empieza el mapa: muñecas rusas (Secc 2)
  mdt_tramo.py       puntos de control + ciclos vivos de un tramo (Reglas 1 y 2)
  mdt_zonas.py       zonas de trabajo + concurrencia (Secc 4, 8, 19)
  mdt_reportes.py    los textos para el operador

Las tres Reglas de Arquitectura (usuario, 3 jul 2026):
  1. La cascada de extracción SIEMPRE baja hasta 1m (fractalidad infinita).
  2. Mapa VIVO: generar_mapa(cutoff) lo reconstruye en cualquier instante,
     siguiendo cada ciclo vela a vela — nunca contra una foto fija.
  3. El mapa es la ÚNICA fuente de anclas: el escáner solo opera ciclos VIVOS
     de esta estructura (candado ancla_viva).
"""
import pandas as pd

from mdt_config import SYMBOL, GRADO_MIN_OPERABLE_PCT
from mdt_math import format_z

# --- Re-exportes: el escáner, el bot y los backtests importan desde aquí ---
from mdt_feed import ahora as _ahora, descargar as _descargar  # noqa: F401
from mdt_estructura import (derivar_estructura_macro, localizar_ancla)  # noqa: F401
from mdt_tramo import analizar_tramo, extraer_mapa_tramo  # noqa: F401
from mdt_zonas import (auditar_ultimo_ciclo, registrar_ciclo,  # noqa: F401
                       resolver_concurrencia, zonas_de_tramo, zonas_finales_tramo)
from mdt_reportes import reporte_ancla, reporte_tramos  # noqa: F401

MAX_MUNECAS = 8   # tope de muñecas anidadas (evita una cascada infinita)


def _rutas_del_grafico(df_1d, est):
    """Las 3 muñecas del diario: el impulso mayor hasta el ATH, su retroceso, y
    el retroceso de ese retroceso. Los tramos que no existen (moneda en su ATH,
    ATH al inicio del histórico) se omiten solos."""
    ath_idx, origen_idx, fondo_idx = est['ath_idx'], est['origen_idx'], est['fondo_idx']
    un_dia = pd.Timedelta(days=1)
    rutas = []
    if origen_idx is not None and ath_idx > origen_idx:
        rutas.append(("Alcista", df_1d.loc[origen_idx, 'open_time'],
                      df_1d.loc[ath_idx, 'open_time'] + un_dia, "BULLISH", 100))
    if fondo_idx is not None and fondo_idx > ath_idx:
        rutas.append(("Bajista", df_1d.loc[ath_idx, 'open_time'],
                      df_1d.loc[fondo_idx, 'open_time'] + un_dia, "BEARISH", 100))
        rutas.append(("Alcista Post-F", df_1d.loc[fondo_idx, 'open_time'],
                      None, "BULLISH", 96))
    return rutas


class _Acumulador:
    """Junta las zonas de todas las rutas y, en paralelo, guarda la vista
    INDEPENDIENTE de cada tramo (Secc 2: cada muñeca es un mapa correcto por sí
    misma). Las vistas se copian: la concurrencia GLOBAL muta las zonas del mapa
    unificado y no debe tocar la vista del tramo."""

    def __init__(self):
        self.buys, self.sells, self.alerts = [], [], []
        self.ciclos, self.tramos = [], []

    def agregar_ruta(self, nombre, direction, res, peso_base, verbose, muneca=False):
        buys_r, sells_r, alerts_r = [], [], []
        for j, c in enumerate(res['ciclos']):
            c['peso'] = peso_base - j
            c['ruta'] = nombre
            c['direction'] = direction
            if muneca:
                c['muneca'] = True   # sus zonas tejen contra la estructura madre
            self.ciclos.append(c)
            registrar_ciclo(c, direction, buys_r, sells_r, alerts_r, verbose)
        self.buys.extend(buys_r)
        self.sells.extend(sells_r)
        self.alerts.extend(alerts_r)
        self.tramos.append({
            'nombre': nombre, 'direction': direction,
            'origen': res['origen'], 'extremo': res['extremo'],
            'origen_time': res['origen_time'], 'ciclos': res['ciclos'],
            'reset_618': res.get('reset_618'),
            'buys': [{**z} for z in buys_r], 'sells': [{**z} for z in sells_r],
            'alerts': list(alerts_r)})


def _munecas_anidadas(acc, res_prev, dir_prev, peso_prev, n_ruta, cutoff, verbose, symbol):
    """Muñecas anidadas (Secc 2, regla usuario 6 jul): "el retroceso de este gran
    fractal se convierte en el impulso del siguiente". El desgrane no termina en
    las 3 muñecas del diario: el retroceso corrido de la última ruta abierta es la
    muñeca siguiente. Se corta cuando el retroceso baja del 1% del precio (la
    escala mínima operable) o al tope de MAX_MUNECAS."""
    n = n_ruta
    while (res_prev is not None and n <= MAX_MUNECAS
           and res_prev.get('extremo_time') is not None):
        direction = "BEARISH" if dir_prev == "BULLISH" else "BULLISH"
        nombre = f"{'Bajista' if direction == 'BEARISH' else 'Alcista'} M{n}"
        peso_base = peso_prev - 4
        if verbose:
            print(f"\n--- RUTA {nombre.upper()} ({direction}, muñeca anidada) ---")

        res = analizar_tramo(nombre, res_prev['extremo_time'], None, direction,
                             cutoff, verbose, symbol)
        if res is None or res.get('extremo') is None:
            return
        grado_ruta = abs(res['origen'] - res['extremo'])
        precio_ref = res.get('precio_ref')
        if precio_ref is None or grado_ruta < precio_ref * GRADO_MIN_OPERABLE_PCT:
            if verbose:
                print(f"   (retroceso {grado_ruta:.2f} < {GRADO_MIN_OPERABLE_PCT:.0%} "
                      f"del precio: fin de las muñecas anidadas)")
            return

        acc.agregar_ruta(nombre, direction, res, peso_base, verbose, muneca=True)
        res_prev, dir_prev, peso_prev = res, direction, peso_base
        n += 1


def generar_mapa(cutoff=None, verbose=True, symbol=SYMBOL):
    """Reconstruye el mapa completo en el instante `cutoff` (None = ahora).

    Devuelve {'ciclos', 'buys', 'sells', 'alerts', 'precio', 'tramos'}: los ciclos
    traen su estado (VIVO/MUERTO, activación, evolución) — el escáner solo debe
    operar anclas VIVAS de esta estructura (Regla 3).
    """
    if verbose:
        print("\n" + "=" * 70)
        print(f" MOTOR ESTRUCTURAL UNIVERSAL MDT — {symbol} (MAPA CRONOLÓGICO, CASCADA A 1M)")
        print("=" * 70 + "\n")

    df_1d = _descargar("1d", None, cutoff, symbol)
    if len(df_1d) < 2:
        raise RuntimeError(f"Sin histórico diario suficiente para {symbol}.")

    est = derivar_estructura_macro(df_1d, symbol, verbose)
    rutas = _rutas_del_grafico(df_1d, est)

    acc = _Acumulador()
    res_prev = fin_prev = dir_prev = peso_prev = None
    for nombre, ini, fin, direction, peso_base in rutas:
        if verbose:
            print(f"\n--- RUTA {nombre.upper()} ({direction}) ---")
        res = analizar_tramo(nombre, ini, fin, direction, cutoff, verbose, symbol)
        if res is None:
            continue
        acc.agregar_ruta(nombre, direction, res, peso_base, verbose)
        res_prev, fin_prev, dir_prev, peso_prev = res, fin, direction, peso_base

    # Las muñecas anidadas solo siguen a una ruta ABIERTA (fin_limite None): es
    # la única cuyo extremo se mueve con el precio.
    if fin_prev is None:
        _munecas_anidadas(acc, res_prev, dir_prev, peso_prev, len(rutas) + 1,
                          cutoff, verbose, symbol)

    precio = float(df_1d.iloc[-1]['close'])

    if verbose:
        print("\n--- CONCURRENCIA GLOBAL DE ZONAS ACTIVAS ---")
        print("\n[ZONAS DE COMPRAS]")
    final_buys = resolver_concurrencia(acc.buys, "BUY", precio, verbose)
    if verbose:
        print("\n[ZONAS DE VENTAS]")
    final_sells = resolver_concurrencia(acc.sells, "SELL", precio, verbose)

    # El último ciclo del mapa se audita contra los anteriores sin privilegios
    final_buys, final_sells = auditar_ultimo_ciclo(acc.ciclos, final_buys, final_sells,
                                                   precio, verbose)
    if verbose:
        _imprimir_zonas(final_buys, final_sells, acc.alerts, precio)

    return {'ciclos': acc.ciclos, 'buys': final_buys, 'sells': final_sells,
            'alerts': acc.alerts, 'precio': precio, 'tramos': acc.tramos}


def _imprimir_zonas(buys, sells, alerts, precio):
    print("\n--- ZONAS OPERATIVAS FINALES ---")
    print("ZONAS DE VENTAS:")
    for s in sells:
        print(f" -> {s['name']}: {format_z(s['z'])}")
    print("\nZONAS DE COMPRAS:")
    for b in buys:
        print(f" -> {b['name']}: {format_z(b['z'])}")
    if alerts:
        print("\n--- ZONAS EN EVOLUCION (ALERTAS NO ACTIVADAS) ---")
        for a in alerts:
            print(f" -> {a['name']}: Si el precio toca {a['activacion']:.2f} (38.2%), "
                  f"se activará Zona de {a['tipo']} en {format_z(a['zona_alerta'])}")
    print(f"\nPRECIO ACTUAL: {precio:.2f}")


def analizar_ancla(precio_ancla, symbol=SYMBOL, cutoff=None, direction=None,
                   tf_busqueda="30m", fecha=None):
    """Mapa del tramo que marcó el OPERADOR: desde su ancla hasta el extremo
    vigente (regla usuario 13 jul: "si le envío un ancla es desde ahí hasta el
    precio máximo o mínimo"). Los ciclos traen su estado y las zonas ya llevan
    aplicada la concurrencia interna del tramo.

    `tf_busqueda` y `fecha` solo acotan DÓNDE se busca el punto del ancla; el
    análisis que sale de ahí es fractal como siempre (cascada 1d -> 1m)."""
    loc = localizar_ancla(precio_ancla, symbol, cutoff, direction,
                          tf=tf_busqueda, fecha=fecha)
    if loc is None:
        return None
    t_ancla, direction, precio_real, alternativas = loc

    res = analizar_tramo(f"Ancla {precio_real:.2f}", t_ancla, None, direction,
                         cutoff, verbose=False, symbol=symbol)
    if res is None or res.get('extremo') is None:
        return None

    precio = res.get('precio_ref')
    if precio is None:
        df = _descargar("1m", None, cutoff, symbol)
        precio = float(df['close'].iloc[-1]) if len(df) else precio_real

    zonas, alerts = zonas_de_tramo(res, direction, precio)
    return {'ancla': precio_real, 'ancla_time': t_ancla, 'direction': direction,
            'origen': res['origen'], 'extremo': res['extremo'],
            'ciclos': res['ciclos'], 'zonas': zonas, 'alerts': alerts,
            'reset_618': res.get('reset_618'), 'precio': precio,
            'alternativas': alternativas, 'tf_busqueda': tf_busqueda}


def ancla_viva(mapa, ancla, tol=1e-6):
    """Candado mapa->escáner (Regla 3): ¿el ancla sigue siendo un ciclo VIVO?"""
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
