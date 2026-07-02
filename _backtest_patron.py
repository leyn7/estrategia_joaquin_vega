"""Escaner de patrones como si fuera 30 jun 2026 23:21 COT, zona ventas N6 Alta 554.18-551.91."""
import sys
sys.path.insert(0, r"C:\Users\leyner\Documents\proyectos\trading\estrategia_joaquin_vega")
import requests
import pandas as pd
from datetime import datetime, timezone

from mdt_patrones import detect_patron_institucional, find_micro_fractals

CUTOFF = datetime(2026, 7, 1, 4, 21, tzinfo=timezone.utc)
CUTOFF_MS = int(CUTOFF.timestamp() * 1000)
START_MS = CUTOFF_MS - 10 * 3600 * 1000  # ultimas 10h en 3m

r = requests.get("https://fapi.binance.com/fapi/v1/klines",
                 params={"symbol": "BNBUSDT", "interval": "1m", "limit": 1500,
                         "startTime": START_MS, "endTime": CUTOFF_MS})
data = [k for k in r.json() if k[6] <= CUTOFF_MS]  # solo velas cerradas
cols = ["open_time","open","high","low","close","vol","close_time","qav","n","tbbav","tbqav","i"]
df = pd.DataFrame(data, columns=cols)
for c in ["open","high","low","close"]: df[c] = pd.to_numeric(df[c])
df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_convert("America/Bogota")

zona_max, zona_min = 554.18, 551.91
print(f"Velas 1m: {len(df)} | Ultima cerrada: {df.iloc[-1]['open_time'].strftime('%H:%M')} COT | Close: {df.iloc[-1]['close']:.2f}")
print(f"Zona VENTAS N6 Alta: {zona_max} a {zona_min} | Mitad: {(zona_max+zona_min)/2:.2f}\n")

res = detect_patron_institucional(df, zona_max, zona_min, "SELL")
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
        print(f" GATILLO AGRESIVO: {d['gatillo_agresivo']:.2f} | SL: {d['stop_loss']:.2f} | CALMADA: {d['espera_calmada']:.2f}")
