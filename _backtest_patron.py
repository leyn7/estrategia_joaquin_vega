"""Escaner de patrones con time-travel (usa el feed oficial de mdt_data).
Uso: python _backtest_patron.py [intervalo] [cutoff_utc_iso] [zona_max] [zona_min] [direccion] [symbol]
Defaults: 1m 2026-07-01T04:21 554.18 551.91 SELL BNBUSDT (golden: 30 jun 23:21 COT)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from datetime import datetime, timezone

from mdt_data import get_binance_klines, to_cot
from mdt_patrones import detect_patron_institucional

INTERVAL = sys.argv[1] if len(sys.argv) > 1 else "1m"
CUTOFF_STR = sys.argv[2] if len(sys.argv) > 2 else "2026-07-01T04:21"
ZMAX = float(sys.argv[3]) if len(sys.argv) > 3 else 554.18
ZMIN = float(sys.argv[4]) if len(sys.argv) > 4 else 551.91
DIRECTION = sys.argv[5].upper() if len(sys.argv) > 5 else "SELL"
SYMBOL = sys.argv[6] if len(sys.argv) > 6 else "BNBUSDT"
ANULACION = float(sys.argv[7]) if len(sys.argv) > 7 else None  # nivel que mata la zona (Secc 17)

CUTOFF = datetime.fromisoformat(CUTOFF_STR).replace(tzinfo=timezone.utc)
CUTOFF_MS = int(CUTOFF.timestamp() * 1000)
START = pd.Timestamp(CUTOFF_MS - 10 * 3600 * 1000, unit="ms", tz="UTC")  # ultimas 10h

df = get_binance_klines(SYMBOL, INTERVAL, start_time=START)
df = df[pd.to_numeric(df["close_time"]) <= CUTOFF_MS].reset_index(drop=True)  # solo velas cerradas
df["open_time"] = to_cot(df["open_time"])

zona_max, zona_min = ZMAX, ZMIN
print(f"Velas {INTERVAL}: {len(df)} | Cutoff: {CUTOFF_STR} UTC | Ultima cerrada: {df.iloc[-1]['open_time'].strftime('%m-%d %H:%M')} COT | Close: {df.iloc[-1]['close']:.2f}")
print(f"Zona: {zona_max} a {zona_min} | Mitad: {(zona_max+zona_min)/2:.2f}\n")

res = detect_patron_institucional(df, zona_max, zona_min, DIRECTION, nivel_anulacion=ANULACION)
print(f"Estado: {res['estado']}")
print(f"Mensaje: {res['mensaje']}")
if "detalles" in res:
    d = res["detalles"]
    print(f"\n--- {d.get('nivel_engano','PATRON')} ---")
    print(f" P1: {d.get('pauta1_price',0):.2f} ({d.get('pauta1_time','')})")
    print(f" P2: {d.get('pauta2_price',0):.2f} ({d.get('pauta2_time','')})")
    print(f" Impulso: {d.get('impulso',0):.2f}")
    print(f" Zona de Engaños: {d.get('fibo_1382',0):.2f} a {d.get('fibo_1618',0):.2f}")
    print(f" Mitad de zona: {d.get('mitad_zona',0):.2f} | Proporcional: {d.get('proporcional','?')}")
    print(f" Calidad: {d.get('calidad','N/A')}")
    if "stop_loss" in d:
        if "gatillo_agresivo" in d:
            print(f" GATILLO AGRESIVO: {d['gatillo_agresivo']:.2f} | SL: {d['stop_loss']:.2f} | CALMADA: {d['espera_calmada']:.2f}")
        elif "entrada_p3_corta" in d:
            print(f" ENTRADA P3 CORTA (61.8): {d['entrada_p3_corta']:.2f} (zona hasta {d['limite_gestion_809']:.2f}) | SL: {d['stop_loss']:.2f} | Gatillo: {d.get('hora_gatillo', 'esperando')}")
        elif "entrada_dt_618" in d:
            print(f" ENTRADA DOBLE TECHO/SUELO (61.8): {d['entrada_dt_618']:.2f} (zona hasta {d['limite_gestion_809']:.2f}) | SL: {d['stop_loss']:.2f} | Gatillo: {d.get('hora_gatillo', 'esperando')}")
        else:
            print(f" SL: {d['stop_loss']:.2f} | ENTRADA CALMADA: {d.get('espera_calmada', 0):.2f} | Extremo impulso: {d.get('extremo_impulso', 0):.2f} | Validado: {d.get('hora_validacion', '')}")
