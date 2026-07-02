import pandas as pd
import requests
import time

REQUEST_TIMEOUT = 15  # segundos: el bot nunca debe quedarse colgado esperando a Binance

def _fetch_klines(url, params):
    """GET con timeout y validación: Binance devuelve un dict (no lista) en errores/rate-limit."""
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise RuntimeError(f"Respuesta inesperada de Binance para {params.get('symbol')}: {data}")
    return data

def get_binance_klines(symbol="BNBUSDT", interval="1d", start_time=None):
    url = "https://fapi.binance.com/fapi/v1/klines"
    all_klines = []

    if start_time:
        # Descargar hacia adelante (desde start_time hasta el presente)
        current_start = int(start_time.timestamp() * 1000)
        now = int(time.time() * 1000)
        while current_start < now:
            params = {"symbol": symbol, "interval": interval, "limit": 1500, "startTime": current_start}
            data = _fetch_klines(url, params)
            if not data: break
            all_klines.extend(data)
            current_start = data[-1][0] + 1
            if len(data) < 1500: break
    else:
        # Descargar hacia atrás (desde el presente)
        end_time = int(time.time() * 1000)
        for _ in range(4): # 6000 velas máximo
            params = {"symbol": symbol, "interval": interval, "limit": 1500, "endTime": end_time}
            data = _fetch_klines(url, params)
            if not data: break
            all_klines = data + all_klines
            end_time = data[0][0] - 1
            if len(data) < 1500: break
            
    cols = ["open_time", "open", "high", "low", "close", "vol", "close_time", "qav", "n", "tbbav", "tbqav", "i"]
    df = pd.DataFrame(all_klines, columns=cols)
    for c in ["open", "high", "low", "close"]: df[c] = pd.to_numeric(df[c])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    return df
