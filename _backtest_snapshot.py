import sys
sys.path.insert(0, r"C:\Users\leyner\Documents\proyectos\trading\estrategia_joaquin_vega")
import requests
import pandas as pd
from datetime import datetime, timezone

CUTOFF = datetime(2026, 7, 1, 4, 21, tzinfo=timezone.utc)  # 30 jun 23:21 COT
CUTOFF_MS = int(CUTOFF.timestamp() * 1000)

def klines(symbol, interval, start_ms, end_ms):
    url = "https://fapi.binance.com/fapi/v1/klines"
    out = []
    cur = start_ms
    while cur < end_ms:
        r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": 1500,
                                      "startTime": cur, "endTime": end_ms})
        data = r.json()
        if not data: break
        out.extend(data)
        cur = data[-1][0] + 1
        if len(data) < 1500: break
    cols = ["open_time","open","high","low","close","vol","close_time","qav","n","tbbav","tbqav","i"]
    df = pd.DataFrame(out, columns=cols)
    for c in ["open","high","low","close"]: df[c] = pd.to_numeric(df[c])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    # Solo velas completamente cerradas antes del cutoff
    return df[df["close_time"] <= CUTOFF].reset_index(drop=True)

# 1. Dailies de la ultima semana antes del cutoff (cerradas)
start = int(datetime(2026, 6, 20, tzinfo=timezone.utc).timestamp() * 1000)
d1 = klines("BNBUSDT", "1d", start, CUTOFF_MS)
print("=== VELAS 1D CERRADAS (UTC) ===")
for _, r in d1.iterrows():
    print(f"  {r['open_time'].strftime('%m-%d')}  O:{r['open']:.2f} H:{r['high']:.2f} L:{r['low']:.2f} C:{r['close']:.2f}")

# 2. Velas 15m de las ultimas 12h antes del cutoff
start12 = CUTOFF_MS - 12*3600*1000
m15 = klines("BNBUSDT", "15m", start12, CUTOFF_MS)
m15["cot"] = m15["open_time"].dt.tz_convert("America/Bogota")
print("\n=== ULTIMAS 12H EN 15m (hora COT) ===")
print(f"  Max 12h: {m15['high'].max():.2f} | Min 12h: {m15['low'].min():.2f}")
for _, r in m15.tail(16).iterrows():
    print(f"  {r['cot'].strftime('%m-%d %H:%M')}  O:{r['open']:.2f} H:{r['high']:.2f} L:{r['low']:.2f} C:{r['close']:.2f}")

# 3. Precio exacto en el cutoff (vela 1m cerrada a las 04:20-04:21 UTC)
m1 = klines("BNBUSDT", "1m", CUTOFF_MS - 10*60*1000, CUTOFF_MS)
last = m1.iloc[-1]
print(f"\n=== PRECIO EN EL INSTANTE (23:21 COT) ===")
print(f"  Ultima vela 1m cerrada: {last['open_time'].tz_convert('America/Bogota').strftime('%H:%M')} COT -> close {last['close']:.2f}")
print(f"  Low del dia (1 jul UTC en curso, hasta cutoff): {klines('BNBUSDT','5m', int(datetime(2026,7,1,tzinfo=timezone.utc).timestamp()*1000), CUTOFF_MS)['low'].min():.2f}")
