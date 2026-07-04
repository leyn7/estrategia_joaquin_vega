# -*- coding: utf-8 -*-
"""Backtest walk-forward de la estrategia completa (mapa -> escáner -> 4 Informaciones).

Camina el pasado en cortes de tiempo. En cada corte reconstruye el mapa y escanea
patrones SOLO con la información disponible en ese instante (sin mirar el futuro).
Recolecta cada entrada ejecutada (gatillos de la cadena, incluidas las que luego
murieron) y simula su desenlace con las velas posteriores:
  - SL tocado primero -> pérdida de 1R.
  - Borde cercano de la zona TP tocado primero -> ganancia de (recompensa/riesgo) R.
  - Ambos en la misma vela -> pérdida (conservador).
  - Ninguno en el horizonte -> resultado flotante al cierre del horizonte.

Reporta el desempeño bruto y el filtrado por las reglas de la biblia
(ratio mínimo 1:3, movimiento prioritario/secundario con volumen reducido = 0.5R),
y compara SIN GESTIÓN (todo-o-nada) contra CON GESTIÓN (Secc 20: parcial + breakeven).

Capa de gestión (Secc 20, videos GESTIÓN EN BENEFICIO / PLAN DE NEGOCIO):
  - Si el objetivo final supera 1:3, los parciales son OBLIGATORIOS.
  - El parcial va a la MITAD del objetivo (final "al doble": 1:2->1:4, 1:3->1:6),
    con mínimo 1:2. Al tocarlo: mitad de la posición fuera + stop a BREAKEVEN.
  - La mitad restante: o llega al objetivo final (TP del ciclo) o vuelve al
    breakeven y cierra en 0. Nunca más se pierde tras el parcial.

Uso:
  python _backtest_estrategia.py --desde "2026-06-08" --hasta "2026-07-04" --paso-horas 24
"""
import argparse
import os
import pickle
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd

import mdt_data
from mdt_config import SYMBOL, TF_MINUTOS, RATIO_MINIMO, PARCIAL_R

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cache_klines")
# Horizonte de simulación POR TAMAÑO DEL CICLO (regla usuario 4 jul): cada operación
# vive en el tamaño del ciclo donde nació su patrón — el TP es del mismo ciclo, y el
# tiempo para alcanzarlo escala con ese tamaño. Una operación macro (1d) no se juzga
# en 7 días.
HORIZONTE_POR_TF_CICLO = {"1d": 60, "2h": 14, "30m": 7, "3m": 3, "1m": 2}  # días

# ---------------------------------------------------------------------------
# Caché de velas: una sola descarga por TF (extendida según demanda), servida
# en rebanadas. Sin esto, cada reconstrucción de mapa re-descargaría todo.
# ---------------------------------------------------------------------------
_cache = {}
_descarga_original = mdt_data.get_binance_klines


def _cache_path(symbol, interval):
    return os.path.join(CACHE_DIR, f"{symbol}_{interval}.pkl")


def _cargar_cache(symbol, interval):
    clave = (symbol, interval)
    if clave in _cache:
        return _cache[clave]
    p = _cache_path(symbol, interval)
    if os.path.exists(p):
        with open(p, 'rb') as f:
            _cache[clave] = pickle.load(f)
        return _cache[clave]
    return None


def _guardar_cache(symbol, interval, df):
    os.makedirs(CACHE_DIR, exist_ok=True)
    _cache[(symbol, interval)] = df
    with open(_cache_path(symbol, interval), 'wb') as f:
        pickle.dump(df, f)


def get_klines_cacheado(symbol=SYMBOL, interval="1d", start_time=None):
    df = _cargar_cache(symbol, interval)
    inicio = pd.Timestamp(start_time).tz_localize(None) if start_time is not None and getattr(start_time, 'tzinfo', None) is None \
        else (pd.Timestamp(start_time).tz_convert('UTC').tz_localize(None) if start_time is not None else None)
    if df is None or (inicio is not None and df['open_time'].iloc[0] > inicio):
        df = _descarga_original(symbol, interval, start_time)
        _guardar_cache(symbol, interval, df)
    if inicio is not None:
        return df[df['open_time'] >= inicio].reset_index(drop=True)
    return df.copy()


mdt_data.get_binance_klines = get_klines_cacheado
# Los módulos ya importados referencian el nombre importado: re-vincular
import mdt_macro_mapper
mdt_macro_mapper.get_binance_klines = get_klines_cacheado

from mdt_escaner import escanear_mapa, ESTADOS_OPERABLES  # noqa: E402 (tras el parche)

# La caché se congela: el walk-forward corta con `cutoff`, nunca ve el futuro del corte
_AHORA_REAL = pd.Timestamp.now(tz='UTC').tz_localize(None)


# ---------------------------------------------------------------------------
# Extracción de entradas ejecutadas de un escaneo
# ---------------------------------------------------------------------------
def _entradas_de(res, escaneo):
    """Devuelve las operaciones EJECUTADAS de una cadena (entrada a mercado real):
    gatillos agresivos (vivos o muertos después) y gatillos de toque 61.8."""
    cadena = res.get('historial', [res]) or [res]
    if res not in cadena:
        cadena = list(cadena) + [res]
    entradas = []
    for r_ in cadena:
        d = r_.get('detalles', {})
        hora = d.get('hora_gatillo')
        if hora is None:
            continue
        entrada = (d.get('gatillo_agresivo') if r_['estado'] in
                   ("GATILLO_ACTIVADO", "ROTO_POR_STOP_LOSS", "ROTO_POR_DOBLE_TOQUE", "EE_GATILLO")
                   else d.get('entrada_p3_corta') or d.get('entrada_dt_618'))
        sl = d.get('stop_loss')
        if entrada is None or sl is None:
            continue
        entradas.append({'hora': hora, 'entrada': entrada, 'sl': sl,
                         'estado': r_['estado'], 'patron': d.get('calidad', r_['estado']),
                         'nivel_engano': d.get('nivel_engano', '?')})
    return entradas


def simular(trade, lado, tp_nivel, df_sim, tf_ciclo="30m"):
    """Camina las velas posteriores a la entrada: ¿SL o TP primero?
    El horizonte escala con el tamaño del ciclo operado (el TP es de ese tamaño)."""
    entrada, sl = trade['entrada'], trade['sl']
    riesgo = abs(sl - entrada)
    recompensa = abs(entrada - tp_nivel)
    if riesgo <= 0:
        return None
    ratio = recompensa / riesgo
    hora = trade['hora']
    hora_naive = hora.tz_convert('UTC').tz_localize(None) if getattr(hora, 'tzinfo', None) else hora
    fin_h = hora_naive + pd.Timedelta(days=HORIZONTE_POR_TF_CICLO.get(tf_ciclo, 7))
    velas = df_sim[(df_sim['open_time'] > hora_naive) & (df_sim['open_time'] <= fin_h)]
    for _, v in velas.iterrows():
        sl_hit = v['high'] >= sl if lado == "SELL" else v['low'] <= sl
        tp_hit = v['low'] <= tp_nivel if lado == "SELL" else v['high'] >= tp_nivel
        if sl_hit:  # conservador: si ambos en la misma vela, cuenta la pérdida
            return {'resultado': 'SL', 'r': -1.0, 'ratio': ratio, 'cierre': v['open_time']}
        if tp_hit:
            return {'resultado': 'TP', 'r': ratio, 'ratio': ratio, 'cierre': v['open_time']}
    if len(velas):
        ult = velas.iloc[-1]['close']
        r_flot = (entrada - ult) / riesgo if lado == "SELL" else (ult - entrada) / riesgo
        return {'resultado': 'ABIERTA', 'r': float(r_flot), 'ratio': ratio, 'cierre': velas.iloc[-1]['open_time']}
    return {'resultado': 'SIN_DATOS', 'r': 0.0, 'ratio': ratio, 'cierre': None}


def simular_gestionado(trade, lado, tp_nivel, df_sim, tf_ciclo="30m"):
    """Gestión de la Secc 20: parcial obligatorio si el objetivo supera 1:3.

    Parcial a la MITAD del objetivo (mínimo 1:2). Al tocarlo: mitad fuera y
    stop a breakeven — de ahí en adelante la operación ya no puede perder.
    Si el objetivo NO supera 1:3 no hay obligación de parcial: todo-o-nada.
    Conservador vela a vela: si SL (o breakeven) y objetivo caen en la misma
    vela, cuenta el lado malo.
    """
    entrada, sl = trade['entrada'], trade['sl']
    riesgo = abs(sl - entrada)
    if riesgo <= 0:
        return None
    ratio = abs(entrada - tp_nivel) / riesgo
    if ratio <= RATIO_MINIMO:
        # sin obligación de parcial -> mismo desenlace que la simulación simple
        sim = simular(trade, lado, tp_nivel, df_sim, tf_ciclo)
        return {**sim, 'gestion': 'SIN_PARCIAL'} if sim else None

    ratio_parcial = max(PARCIAL_R, ratio / 2.0)   # parcial = mitad del final, mínimo 1:2
    signo = -1.0 if lado == "SELL" else 1.0
    nivel_parcial = entrada + signo * ratio_parcial * riesgo

    hora = trade['hora']
    hora_naive = hora.tz_convert('UTC').tz_localize(None) if getattr(hora, 'tzinfo', None) else hora
    fin_h = hora_naive + pd.Timedelta(days=HORIZONTE_POR_TF_CICLO.get(tf_ciclo, 7))
    velas = df_sim[(df_sim['open_time'] > hora_naive) & (df_sim['open_time'] <= fin_h)]

    parcial_hecho = False
    r_asegurada = 0.0
    for _, v in velas.iterrows():
        if not parcial_hecho:
            sl_hit = v['high'] >= sl if lado == "SELL" else v['low'] <= sl
            p_hit = v['low'] <= nivel_parcial if lado == "SELL" else v['high'] >= nivel_parcial
            if sl_hit:
                return {'resultado': 'SL', 'r': -1.0, 'ratio': ratio, 'gestion': 'SL_ANTES_DE_PARCIAL',
                        'cierre': v['open_time']}
            if p_hit:
                parcial_hecho = True
                r_asegurada = 0.5 * ratio_parcial   # mitad fuera; stop -> breakeven
                # misma vela: ¿también tocó el objetivo final? (conservador: aún no)
        else:
            be_hit = v['high'] >= entrada if lado == "SELL" else v['low'] <= entrada
            tp_hit = v['low'] <= tp_nivel if lado == "SELL" else v['high'] >= tp_nivel
            if be_hit:
                return {'resultado': 'PARCIAL+BE', 'r': r_asegurada, 'ratio': ratio,
                        'gestion': 'PARCIAL_Y_BREAKEVEN', 'cierre': v['open_time']}
            if tp_hit:
                return {'resultado': 'PARCIAL+TP', 'r': r_asegurada + 0.5 * ratio, 'ratio': ratio,
                        'gestion': 'PARCIAL_Y_FINAL', 'cierre': v['open_time']}
    if len(velas):
        ult = velas.iloc[-1]['close']
        r_flot = (entrada - ult) / riesgo if lado == "SELL" else (ult - entrada) / riesgo
        if parcial_hecho:
            return {'resultado': 'PARCIAL+ABIERTA', 'r': r_asegurada + 0.5 * float(r_flot),
                    'ratio': ratio, 'gestion': 'PARCIAL_Y_FLOTANTE', 'cierre': velas.iloc[-1]['open_time']}
        return {'resultado': 'ABIERTA', 'r': float(r_flot), 'ratio': ratio,
                'gestion': 'SIN_PARCIAL_AUN', 'cierre': velas.iloc[-1]['open_time']}
    return {'resultado': 'SIN_DATOS', 'r': 0.0, 'ratio': ratio, 'gestion': 'SIN_DATOS', 'cierre': None}


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default="2026-06-08")
    ap.add_argument("--hasta", default="2026-07-04")
    ap.add_argument("--paso-horas", type=int, default=24)
    ap.add_argument("--symbol", default=SYMBOL)
    args = ap.parse_args()
    symbol = args.symbol.upper()

    cortes = pd.date_range(args.desde, args.hasta, freq=f"{args.paso_horas}h")
    paso = pd.Timedelta(hours=args.paso_horas)
    print(f"Walk-forward {symbol} {args.desde} -> {args.hasta} | {len(cortes)} cortes cada {args.paso_horas}h\n")

    trades = {}
    df_sim_cache = {}
    for n, cutoff in enumerate(cortes, 1):
        cutoff = pd.Timestamp(cutoff)
        try:
            resultado = escanear_mapa(cutoff=cutoff, verbose=False, symbol=symbol)
        except Exception as exc:
            print(f"[{n}/{len(cortes)}] {cutoff} ERROR: {exc}")
            continue
        prioritaria = resultado['prioritaria']
        nuevos = 0
        for e in resultado['escaneos']:
            res = e['resultado']
            tp_zona = e.get('tp_zona')
            if tp_zona is None:
                continue
            if e.get('contexto'):
                continue  # zona macro: contexto, no se opera (preferencia usuario)
            lado = e['lado']
            tp_nivel = max(tp_zona) if lado == "SELL" else min(tp_zona)
            for t in _entradas_de(res, e):
                hora = t['hora']
                hora_naive = hora.tz_convert('UTC').tz_localize(None) if getattr(hora, 'tzinfo', None) else hora
                # atribuir la señal al corte en el que NACIÓ (evitar duplicados)
                if not (cutoff - paso < hora_naive <= cutoff):
                    continue
                clave = (e['zona'], lado, round(t['entrada'], 2), str(hora_naive)[:16])
                if clave in trades:
                    continue
                tf_p = e['tf_patron']
                if tf_p not in df_sim_cache:
                    df_sim_cache[tf_p] = get_klines_cacheado(symbol, tf_p,
                                                             pd.Timestamp(args.desde) - pd.Timedelta(days=2))
                sim = simular(t, lado, tp_nivel, df_sim_cache[tf_p], e['tf_ciclo'])
                if sim is None:
                    continue
                gest = simular_gestionado(t, lado, tp_nivel, df_sim_cache[tf_p], e['tf_ciclo'])
                riesgo = abs(t['sl'] - t['entrada'])
                prioridad = "PRIORITARIO" if (prioritaria is None or lado == prioritaria) else "SECUNDARIO"
                trades[clave] = {**t, 'zona': e['zona'], 'lado': lado, 'tf': tf_p,
                                 'tp_nivel': tp_nivel, 'riesgo': riesgo,
                                 'prioridad': prioridad, **sim,
                                 'g_resultado': gest['resultado'], 'g_r': gest['r'],
                                 'g_gestion': gest['gestion']}
                nuevos += 1
        print(f"[{n}/{len(cortes)}] {cutoff}  señales nuevas: {nuevos}  (acumuladas: {len(trades)})")

    # -----------------------------------------------------------------------
    # Reporte
    # -----------------------------------------------------------------------
    ops = list(trades.values())
    print("\n" + "=" * 100)
    print(f" OPERACIONES DETECTADAS: {len(ops)}")
    print("=" * 100)
    for o in sorted(ops, key=lambda x: str(x['hora'])):
        print(f"{str(o['hora'])[:16]} [{o['lado']}] {o['zona'][:38]:<38} {o['estado'][:22]:<22} "
              f"E {o['entrada']:.2f} SL {o['sl']:.2f} TP {o['tp_nivel']:.2f} "
              f"R:B 1:{o['ratio']:.1f} {o['prioridad'][:4]} -> {o['resultado']} ({o['r']:+.2f}R) "
              f"| gestión: {o['g_resultado']} ({o['g_r']:+.2f}R)")

    def resumen(nombre, subset, pesos=None, campo_r='r', campo_res='resultado'):
        if not subset:
            print(f"\n{nombre}: sin operaciones")
            return
        perdidas = [o for o in subset if o[campo_res] == 'SL']
        ganadas = [o for o in subset if o[campo_res] in ('TP', 'PARCIAL+TP', 'PARCIAL+BE')]
        abiertas = [o for o in subset if 'ABIERTA' in o[campo_res]]
        cerradas = len(perdidas) + len(ganadas)
        total_r = sum((o[campo_r] * (pesos(o) if pesos else 1.0)) for o in subset)
        print(f"\n{nombre}: {len(subset)} ops | cerradas {cerradas} "
              f"(a favor {len(ganadas)} / SL {len(perdidas)}"
              f"{f' | winrate {len(ganadas)/cerradas:.0%}' if cerradas else ''}) "
              f"| abiertas {len(abiertas)} | R total {total_r:+.2f}")

    print("\n--- SIN GESTIÓN (todo-o-nada al TP del ciclo) ---")
    resumen("BRUTO (todas las entradas ejecutadas)", ops)
    con_ratio = [o for o in ops if o['ratio'] >= RATIO_MINIMO]
    resumen(f"FILTRO RATIO 1:{RATIO_MINIMO:.0f} (Secc 1)", con_ratio)
    resumen("FILTRO RATIO + volumen (secundarios a 0.5R, Secc 1)", con_ratio,
            pesos=lambda o: 0.5 if o['prioridad'] == 'SECUNDARIO' else 1.0)
    prio = [o for o in con_ratio if o['prioridad'] == 'PRIORITARIO']
    resumen("SOLO PRIORITARIAS con ratio", prio)

    print("\n--- CON GESTIÓN (Secc 20: parcial a mitad de objetivo + stop a breakeven) ---")
    resumen("BRUTO gestionado", ops, campo_r='g_r', campo_res='g_resultado')
    resumen(f"FILTRO RATIO 1:{RATIO_MINIMO:.0f} gestionado", con_ratio,
            campo_r='g_r', campo_res='g_resultado')
    resumen("FILTRO RATIO + volumen gestionado", con_ratio,
            pesos=lambda o: 0.5 if o['prioridad'] == 'SECUNDARIO' else 1.0,
            campo_r='g_r', campo_res='g_resultado')
    resumen("SOLO PRIORITARIAS con ratio gestionado", prio,
            campo_r='g_r', campo_res='g_resultado')


if __name__ == "__main__":
    main()
