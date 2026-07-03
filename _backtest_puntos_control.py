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
            if ev.get('zona_origen_en_trabajo'):
                lado = "PARTE BAJA" if args.direction == "BULLISH" else "PARTE ALTA"
                caja = ev['zonas']['BAJA'] if args.direction == "BULLISH" else ev['zonas']['ALTA']
                estado = (f"TRABAJANDO {lado}: {min(caja):.2f} a {max(caja):.2f} "
                          f"| muerte del ciclo en {ev['nivel_muerte']:.2f}")
            else:
                estado = f"EN ZONA DE INDECISIÓN (inoperable) | muerte del ciclo en {ev['nivel_muerte']:.2f}"
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

if res.get('pendientes'):
    print("\n--- RETROCESOS PENDIENTES DENTRO DEL TRAMO (ruido: sin validar su 1/3) ---")
    for p in res['pendientes']:
        print(f" {p['peak']:.2f} -> {p['trough']:.2f} ({cot(p['trough_time'])}, {p['tf']}) | "
              f"altura {p['altura']:.2f} | valida como punto de control si rompe {p['nivel_validacion']:.2f}")

# Retroceso post-extremo: el movimiento corrido desde el extremo del tramo es el
# candidato dominante a próximo punto de control (dilata mientras deje nuevos extremos)
from mdt_data import get_binance_klines

df_post = get_binance_klines("BNBUSDT", res['tf_macro'],
                             start_time=pd.Timestamp(res['origen_time']).tz_localize('UTC'))
if cutoff is not None:
    df_post = df_post[df_post['open_time'] <= cutoff].reset_index(drop=True)
bull = args.direction == "BULLISH"
e_idx = int(df_post['high'].idxmax()) if bull else int(df_post['low'].idxmin())
tramo_post = df_post.loc[e_idx:]
if len(tramo_post) > 1:
    if bull:
        r_idx = int(tramo_post['low'].idxmin())
        r_val = df_post.loc[r_idx, 'low']
    else:
        r_idx = int(tramo_post['high'].idxmax())
        r_val = df_post.loc[r_idx, 'high']
    altura = abs(res['extremo'] - r_val)
    if altura > 0:
        nivel = res['extremo'] + altura / 3.0 if bull else res['extremo'] - altura / 3.0
        print(f"\n--- RETROCESO POST-EXTREMO (candidato dominante a punto de control) ---")
        print(f" {res['extremo']:.2f} -> {r_val:.2f} ({cot(df_post.loc[r_idx, 'open_time'])}) | "
              f"altura {altura:.2f} | valida si el precio rompe {nivel:.2f} "
              f"(sigue dilatando mientras deje nuevos extremos)")
