"""Exploración de puntos de control post-fondo (migrado al motor cronológico).
Uso: python _find_poc.py [intervalo] [fecha_inicio_utc]"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from mdt_data import get_binance_klines, to_cot
from mdt_fractal import extraer_puntos_control

INTERVAL = sys.argv[1] if len(sys.argv) > 1 else "30m"
START = sys.argv[2] if len(sys.argv) > 2 else "2026-07-01 00:00:00"

start_date = pd.to_datetime(START, utc=True)
df = get_binance_klines("BNBUSDT", INTERVAL, start_time=start_date)
df['cot'] = to_cot(df['open_time'])

origen_idx = int(df['low'].idxmin())
extremo_idx = int(df.loc[origen_idx:, 'high'].idxmax())
print(f"Tramo: {df.loc[origen_idx,'low']:.2f} ({str(df.loc[origen_idx,'cot'])[:16]}) -> "
      f"{df.loc[extremo_idx,'high']:.2f} ({str(df.loc[extremo_idx,'cot'])[:16]})\n")

res = extraer_puntos_control(df, origen_idx, extremo_idx, "BULLISH")

print("--- PUNTOS DE CONTROL VIVOS ---")
for c in res['vivos']:
    print(f" CP {c['trough']:.2f} ({str(df.loc[c['trough_idx'],'cot'])[:16]}) | grado {c['grado']:.2f} | "
          f"validado {str(df.loc[c['valid_idx'],'cot'])[:16]}")

print("\n--- RETROCESOS PENDIENTES (ruido, sin validar el 1/3) ---")
for p in res['pendientes']:
    print(f" {p['peak']:.2f} -> {p['trough']:.2f} ({str(df.loc[p['trough_idx'],'cot'])[:16]}) | "
          f"altura {p['altura']:.2f} | valida si rompe {p['nivel_validacion']:.2f}")
