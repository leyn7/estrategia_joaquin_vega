# -*- coding: utf-8 -*-
"""Backtest determinista (time-travel) de un tramo usando el MISMO pipeline del mapper
(analizar_tramo: cascada de TFs hasta 1m + seguimiento cronológico de cada ciclo).

Uso:
  python _backtest_puntos_control.py --start "2026-07-01 06:00" --extremo "2026-07-02 08:30"
  python _backtest_puntos_control.py --start "..." [--extremo "..."] [--cutoff "..."]

start/extremo/cutoff en hora Bogotá (COT). Sin --extremo, el tramo corre hasta el
extremo corrido (cutoff/presente), igual que la ruta post-fondo del mapper.
"""
import argparse
import pandas as pd
from mdt_macro_mapper import analizar_tramo

parser = argparse.ArgumentParser()
parser.add_argument("--start", required=True, help="Hora Bogotá del inicio del tramo")
parser.add_argument("--extremo", default=None, help="Hora Bogotá de la vela del extremo del tramo")
parser.add_argument("--cutoff", default=None, help="Hora Bogotá: ignora todo lo posterior")
parser.add_argument("--direction", default="BULLISH", choices=["BULLISH", "BEARISH"])
args = parser.parse_args()

BOG = 'America/Bogota'

def a_utc(s):
    return pd.Timestamp(s, tz=BOG).tz_convert('UTC').tz_localize(None)

def cot(ts):
    return str(pd.Timestamp(ts).tz_localize('UTC').tz_convert(BOG))[:16]

inicio = a_utc(args.start)
fin_limite = a_utc(args.extremo) + pd.Timedelta(minutes=15) if args.extremo else None
cutoff = a_utc(args.cutoff) if args.cutoff else None

res = analizar_tramo("Tramo", inicio, fin_limite, args.direction, cutoff, verbose=True)
if res is None:
    raise SystemExit("Tramo sin datos suficientes.")

print(f"\nMACRO DEL TRAMO: {res['origen']:.2f} ({cot(res['origen_time'])}) -> {res['extremo']:.2f}")

print("\n--- CRONOLOGÍA (todas las temporalidades) ---")
for ev in sorted(res['cronologia'], key=lambda e: (e['time'], 0 if e['tipo'] == 'MUERE' else 1)):
    ts = cot(ev['time'])
    if ev['tipo'] == 'VALIDA':
        print(f"[OK {ev['tf']:>3}] {ts}  CP VALIDADO {ev['trough']:.2f} ({cot(ev['trough_time'])}) | "
              f"extremo {ev['peak']:.2f} | grado {ev['grado']:.2f} | rompió {ev['nivel_roto']:.2f}")
    elif ev['tipo'] == 'MUERE':
        extra = f" por {ev['asesino']:.2f} (grado {ev['grado_asesino']:.2f})" if 'asesino' in ev else ""
        print(f"[X  {ev['tf']:>3}] {ts}  CP {ev['trough']:.2f} (grado {ev['grado']:.2f}) MUERE: {ev['causa']}{extra}")
    elif ev['tipo'] == 'RESET':
        print(f"[R  {ev['tf']:>3}] {ts}  RESET 61.8% en {ev['trough']:.2f}")

print("\n--- CICLOS Y SU SEGUIMIENTO CRONOLÓGICO HASTA EL CUTOFF ---")
for c in res['ciclos']:
    ev = c['eval']
    grado = f"grado {c['grado']:.2f}" if c['grado'] is not None else "macro"
    etiqueta = f"{c['nombre']} ({c['tf']}, {grado}) ancla {c['ancla']:.2f}"
    if ev['estado'] == 'MUERTO':
        print(f" [MUERTO] {etiqueta}: tocó su 138.2 ({ev['nivel_muerte']:.2f}) el {cot(ev['hora_muerte'])}")
    elif ev['estado'] == 'SIN_IMPULSO':
        print(f" [--]     {etiqueta}: sin impulso medible")
    else:
        if ev['en_excursion']:
            estado = "EN EXCURSIÓN bajo el origen (inoperable)"
        elif ev['activado']:
            estado = f"ACTIVADO (tocó su 38.2 el {cot(ev['hora_activacion'])})"
        else:
            estado = f"EN ALERTA (se activa al tocar su 38.2 en {ev['nivel_activacion']:.2f})"
        extra = f" | origen dilatado a {ev['origen_vigente']:.2f}" if ev['dilatado'] else ""
        print(f" [VIVO]   {etiqueta} -> fin {ev['fin_vigente']:.2f}: {estado}{extra}")

print("\n--- MAPA ACTUAL DEL TRAMO (anclas vivas) ---")
for c in res['ciclos']:
    if c['eval']['estado'] == 'VIVO':
        grado = f"grado {c['grado']:.2f}, " if c['grado'] is not None else ""
        print(f" -> {c['nombre']} ({grado}{c['tf']}) | ciclo {c['ancla']:.2f} -> {c['eval']['fin_vigente']:.2f}")
