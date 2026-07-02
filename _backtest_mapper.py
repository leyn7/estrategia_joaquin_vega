"""Corre mdt_macro_mapper.py como si fuera el 30 jun 2026 23:21 COT (time-travel).
Trunca toda descarga al cutoff y reconstruye la vela parcial en curso desde 1m."""
import sys
sys.path.insert(0, r"C:\Users\leyner\Documents\proyectos\trading\estrategia_joaquin_vega")
import runpy
import requests
import time as _time
import pandas as pd
from datetime import datetime, timezone

import mdt_data

CUTOFF = datetime(2026, 7, 1, 4, 21, tzinfo=timezone.utc)  # 30 jun 23:21 COT
CUTOFF_MS = int(CUTOFF.timestamp() * 1000)

_orig = mdt_data.get_binance_klines

# El mapper usa time.time() para paginar "hasta ahora": lo anclamos al cutoff
mdt_data.time = type(_time)("time_patched")
mdt_data.time.time = lambda: CUTOFF_MS / 1000.0
mdt_data.time.sleep = _time.sleep

def _partial_candle(symbol, from_ms):
    """Agrega velas 1m entre from_ms y el cutoff para simular la vela en curso."""
    r = requests.get("https://fapi.binance.com/fapi/v1/klines",
                     params={"symbol": symbol, "interval": "1m", "limit": 1500,
                             "startTime": from_ms, "endTime": CUTOFF_MS})
    data = r.json()
    if not data: return None
    df = pd.DataFrame(data)
    return {
        "open_time": pd.to_datetime(int(data[0][0]), unit="ms"),
        "open": float(data[0][1]),
        "high": pd.to_numeric(df[2]).max(),
        "low": pd.to_numeric(df[3]).min(),
        "close": float(data[-1][4]),
        "vol": 0, "close_time": CUTOFF_MS, "qav": 0, "n": 0, "tbbav": 0, "tbqav": 0, "i": 0,
    }

def patched(symbol="BNBUSDT", interval="1d", start_time=None):
    df = _orig(symbol, interval, start_time)
    # close_time viene en ms crudos: descartar velas que cierran despues del cutoff
    closed = df[pd.to_numeric(df["close_time"]) <= CUTOFF_MS].reset_index(drop=True)
    if len(closed) < len(df):
        last_close = int(closed.iloc[-1]["close_time"]) if len(closed) else 0
        pc = _partial_candle(symbol, last_close + 1)
        if pc is not None:
            closed = pd.concat([closed, pd.DataFrame([pc])], ignore_index=True)
            closed["open_time"] = pd.to_datetime(closed["open_time"])
    return closed

mdt_data.get_binance_klines = patched

runpy.run_path(r"C:\Users\leyner\Documents\proyectos\trading\estrategia_joaquin_vega\mdt_macro_mapper.py",
               run_name="__main__")
