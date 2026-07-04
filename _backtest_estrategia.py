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
(ratio 1:4, movimiento prioritario/secundario con volumen reducido = 0.5R).

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
from mdt_config import SYMBOL, TF_MINUTOS, RATIO_MINIMO

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cache_klines")
HORIZONTE_DIAS = 7  # máximo de días para que una operación resuelva

# ---------------------------------------------------------------------------
# Caché de velas: una sola descarga por TF (extendida según demanda), servida
# en rebanadas. Sin esto, cada reconstrucción de mapa re-descargaría todo.
# ---------------------------------------------------------------------------
_cache = {}
_descarga_original = mdt_data.get_binance_klines


def _cache_path(interval):
    return os.path.join(CACHE_DIR, f"{SYMBOL}_{interval}.pkl")


def _cargar_cache(interval):
    if interval in _cache:
        return _cache[interval]
    p = _cache_path(interval)
    if os.path.exists(p):
        with open(p, 'rb') as f:
            _cache[interval] = pickle.load(f)
        return _cache[interval]
    return None


def _guardar_cache(interval, df):
    os.makedirs(CACHE_DIR, exist_ok=True)
    _cache[interval] = df
    with open(_cache_path(interval), 'wb') as f:
        pickle.dump(df, f)


def get_klines_cacheado(symbol=SYMBOL, interval="1d", start_time=None):
    if symbol != SYMBOL:
        return _descarga_original(symbol, interval, start_time)
    df = _cargar_cache(interval)
    inicio = pd.Timestamp(start_time).tz_localize(None) if start_time is not None and getattr(start_time, 'tzinfo', None) is None \
        else (pd.Timestamp(start_time).tz_convert('UTC').tz_localize(None) if start_time is not None else None)
    necesita = (df is None or (inicio is not None and df['open_time'].iloc[0] > inicio)
                or df is None)
    if df is None or (inicio is not None and df['open_time'].iloc[0] > inicio):
        df = _descarga_original(symbol, interval, start_time)
        _guardar_cache(interval, df)
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


def simular(trade, lado, tp_nivel, df_sim):
    """Camina las velas posteriores a la entrada: ¿SL o TP primero?"""
    entrada, sl = trade['entrada'], trade['sl']
    riesgo = abs(sl - entrada)
    recompensa = abs(entrada - tp_nivel)
    if riesgo <= 0:
        return None
    ratio = recompensa / riesgo
    hora = trade['hora']
    hora_naive = hora.tz_convert('UTC').tz_localize(None) if getattr(hora, 'tzinfo', None) else hora
    fin_h = hora_naive + pd.Timedelta(days=HORIZONTE_DIAS)
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


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default="2026-06-08")
    ap.add_argument("--hasta", default="2026-07-04")
    ap.add_argument("--paso-horas", type=int, default=24)
    args = ap.parse_args()

    cortes = pd.date_range(args.desde, args.hasta, freq=f"{args.paso_horas}h")
    paso = pd.Timedelta(hours=args.paso_horas)
    print(f"Walk-forward {args.desde} -> {args.hasta} | {len(cortes)} cortes cada {args.paso_horas}h\n")

    trades = {}
    df_sim_cache = {}
    for n, cutoff in enumerate(cortes, 1):
        cutoff = pd.Timestamp(cutoff)
        try:
            resultado = escanear_mapa(cutoff=cutoff, verbose=False)
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
                    df_sim_cache[tf_p] = get_klines_cacheado(SYMBOL, tf_p,
                                                             pd.Timestamp(args.desde) - pd.Timedelta(days=2))
                sim = simular(t, lado, tp_nivel, df_sim_cache[tf_p])
                if sim is None:
                    continue
                riesgo = abs(t['sl'] - t['entrada'])
                prioridad = "PRIORITARIO" if (prioritaria is None or lado == prioritaria) else "SECUNDARIO"
                trades[clave] = {**t, 'zona': e['zona'], 'lado': lado, 'tf': tf_p,
                                 'tp_nivel': tp_nivel, 'riesgo': riesgo,
                                 'prioridad': prioridad, **sim}
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
              f"R:B 1:{o['ratio']:.1f} {o['prioridad'][:4]} -> {o['resultado']} ({o['r']:+.2f}R)")

    def resumen(nombre, subset, pesos=None):
        if not subset:
            print(f"\n{nombre}: sin operaciones")
            return
        cerradas = [o for o in subset if o['resultado'] in ('SL', 'TP')]
        wins = [o for o in cerradas if o['resultado'] == 'TP']
        total_r = sum((o['r'] * (pesos(o) if pesos else 1.0)) for o in subset)
        print(f"\n{nombre}: {len(subset)} ops | cerradas {len(cerradas)} "
              f"(TP {len(wins)} / SL {len(cerradas) - len(wins)}"
              f"{f' | winrate {len(wins)/len(cerradas):.0%}' if cerradas else ''}) "
              f"| abiertas {sum(1 for o in subset if o['resultado'] == 'ABIERTA')} "
              f"| R total {total_r:+.2f}")

    resumen("BRUTO (todas las entradas ejecutadas)", ops)
    con_ratio = [o for o in ops if o['ratio'] >= RATIO_MINIMO]
    resumen(f"FILTRO RATIO 1:{RATIO_MINIMO:.0f} (Secc 1)", con_ratio)
    resumen("FILTRO RATIO + volumen (secundarios a 0.5R, Secc 1)", con_ratio,
            pesos=lambda o: 0.5 if o['prioridad'] == 'SECUNDARIO' else 1.0)
    prio = [o for o in con_ratio if o['prioridad'] == 'PRIORITARIO']
    resumen("SOLO PRIORITARIAS con ratio", prio)


if __name__ == "__main__":
    main()
