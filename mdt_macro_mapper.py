import pandas as pd
import requests

def get_binance_klines(symbol="BNBUSDT", interval="1w", limit=1500):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    response = requests.get(url, params=params)
    data = response.json()
    columns = ["open_time", "open", "high", "low", "close", "volume", "close_time", "qav", "num_trades", "tbbav", "tbqav", "ignore"]
    df = pd.DataFrame(data, columns=columns)
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    return df

def calculate_mdt_zones(start_price, end_price, cycle_type="bullish"):
    """
    Calcula las zonas de trabajo MDT respetando la estructura matemática.
    start_price = Origen (100%)
    end_price = Fin (0%)
    cycle_type = "bullish" (Tendencia al alza) o "bearish" (Tendencia a la baja)
    """
    impulse = abs(start_price - end_price)
    
    level_100 = start_price
    level_0 = end_price
    zone_size = impulse * 0.191
    
    if cycle_type == "bullish":
        level_61 = end_price - (impulse * 0.618)
        level_38 = end_price - (impulse * 0.382)
        level_minus_38 = end_price + (impulse * 0.382)
        level_138 = start_price - (impulse * 0.382)
        
        zona_alta = (level_0, level_0 + zone_size)          # 0% a -19.1%
        zona_media = (level_61, level_61 - zone_size)       # 61.8% a 80.9%
        zona_baja = (level_100, level_100 - zone_size)      # 100% a 119.1%
        
    else:
        level_61 = end_price + (impulse * 0.618)
        level_38 = end_price + (impulse * 0.382)
        level_minus_38 = end_price - (impulse * 0.382)
        level_138 = start_price + (impulse * 0.382)
        
        zona_alta = (level_100, level_100 + zone_size)      # 100% a 119.1%
        zona_media = (level_61, level_61 + zone_size)       # 61.8% a 80.9%
        zona_baja = (level_0, level_0 - zone_size)          # 0% a -19.1%

    print(f"--- CICLO MACRO {cycle_type.upper()} ---")
    print(f"Origen (100%): {level_100:.4f}")
    print(f"Fin (0%): {level_0:.4f}")
    print(f"Tamaño Impulso: {impulse:.4f}")
    print("-" * 40)
    
    if cycle_type == "bullish":
        print(f"ZONA ALTA (Ventas | 0% a -19.1%): {zona_alta[0]:.4f} a {zona_alta[1]:.4f}")
        print(f"ZONA MEDIA (Compras | 61.8% a 80.9%): {zona_media[0]:.4f} a {zona_media[1]:.4f}")
        print(f"ZONA BAJA (Compras | 100% a 119.1%): {zona_baja[0]:.4f} a {zona_baja[1]:.4f}")
        print("-" * 40)
        print(f"Anulación Superior (-38.2%): {level_minus_38:.4f}")
        print(f"Anulación Inferior (138.2%): {level_138:.4f}")
    else:
        print(f"ZONA ALTA (Ventas | 100% a 119.1%): {zona_alta[0]:.4f} a {zona_alta[1]:.4f}")
        print(f"ZONA MEDIA (Ventas | 61.8% a 80.9%): {zona_media[0]:.4f} a {zona_media[1]:.4f}")
        print(f"ZONA BAJA (Compras | 0% a -19.1%): {zona_baja[0]:.4f} a {zona_baja[1]:.4f}")
        print("-" * 40)
        print(f"Anulación Superior (138.2%): {level_138:.4f}")
        print(f"Anulación Inferior (-38.2%): {level_minus_38:.4f}")

    print(f"Activación (38.2%): {level_38:.4f}\n")

if __name__ == "__main__":
    print("Ejecutando Mapeo de Zonas Validadas (MDT) para BNBUSDT:\n")
    
    # 1. Ciclo Alcista Estructuralmente Válido (Bear Market 2022 a ATH 2025)
    calculate_mdt_zones(start_price=182.97, end_price=1374.61, cycle_type="bullish")
    
    # 2. Ciclo Bajista Reciente (ATH a Mínimo de Junio 2026)
    calculate_mdt_zones(start_price=1374.61, end_price=537.31, cycle_type="bearish")
