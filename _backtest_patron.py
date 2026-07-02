"""Escaner de patrones con time-travel.
Uso: python _backtest_patron.py [intervalo] [cutoff_utc_iso] [zona_max] [zona_min]
Defaults: 1m 2026-07-01T04:21 554.18 551.91 (30 jun 23:21 COT, zona ventas N6 Alta)."""
import sys
sys.path.insert(0, r"C:\Users\leyner\Documents\proyectos\trading\estrategia_joaquin_vega")
import requests
import pandas as pd
from datetime import datetime, timezone

from mdt_patrones import detect_patron_institucional, find_micro_fractals

INTERVAL = sys.argv[1] if len(sys.argv) > 1 else "1m"
CUTOFF_STR = sys.argv[2] if len(sys.argv) > 2 else "2026-07-01T04:21"
ZMAX = float(sys.argv[3]) if len(sys.argv) > 3 else 554.18
ZMIN = float(sys.argv[4]) if len(sys.argv) > 4 else 551.91

CUTOFF = datetime.fromisoformat(CUTOFF_STR).replace(tzinfo=timezone.utc)
CUTOFF_MS = int(CUTOFF.timestamp() * 1000)
START_MS = CUTOFF_MS - 10 * 3600 * 1000  # ultimas 10h

r = requests.get("https://fapi.binance.com/fapi/v1/klines",
                 params={"symbol": "BNBUSDT", "interval": INTERVAL, "limit": 1500,
                         "startTime": START_MS, "endTime": CUTOFF_MS})
data = [k for k in r.json() if k[6] <= CUTOFF_MS]  # solo velas cerradas
cols = ["open_time","open","high","low","close","vol","close_time","qav","n","tbbav","tbqav","i"]
df = pd.DataFrame(data, columns=cols)
for c in ["open","high","low","close"]: df[c] = pd.to_numeric(df[c])
df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_convert("America/Bogota")

zona_max, zona_min = ZMAX, ZMIN
print(f"Velas {INTERVAL}: {len(df)} | Cutoff: {CUTOFF_STR} UTC | Ultima cerrada: {df.iloc[-1]['open_time'].strftime('%m-%d %H:%M')} COT | Close: {df.iloc[-1]['close']:.2f}")
print(f"Zona: {zona_max} a {zona_min} | Mitad: {(zona_max+zona_min)/2:.2f}\n")

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
        if "gatillo_agresivo" in d:
            print(f" GATILLO AGRESIVO: {d['gatillo_agresivo']:.2f} | SL: {d['stop_loss']:.2f} | CALMADA: {d['espera_calmada']:.2f}")
        else:
            print(f" SL: {d['stop_loss']:.2f} | ENTRADA CALMADA: {d['espera_calmada']:.2f} | Extremo impulso: {d.get('extremo_impulso', 0):.2f} | Validado: {d.get('hora_validacion', '')}")
