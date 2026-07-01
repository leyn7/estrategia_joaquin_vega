import pandas as pd
import requests

def get_binance_klines():
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": "BNBUSDT", "interval": "1d", "limit": 1500}
    response = requests.get(url, params=params)
    cols = ["open_time", "open", "high", "low", "close", "v", "close_time", "qav", "n", "tbbav", "tbqav", "i"]
    df = pd.DataFrame(response.json(), columns=cols)
    for c in ["open", "high", "low", "close"]: df[c] = pd.to_numeric(df[c])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    return df

def calculate_bearish_zones(origen, fin):
    impulse = abs(origen - fin)
    zone_size = impulse * 0.191
    
    # Ciclo BEARISH (Origen Arriba, Fin Abajo)
    # ZONA ALTA (Ventas): en el origen (100%) -> de 100% a 119.1%
    zona_alta = (origen, origen + zone_size)
    
    # ZONA MEDIA (Ventas): en el 61.8% -> de 61.8% a 80.9%
    # Si origen es 1300 y fin es 500, el impulso es 800.
    # El 61.8% se mide desde el Fin hacia arriba: Fin + (Impulso * 0.618)
    nivel_618 = fin + (impulse * 0.618)
    zona_media = (nivel_618, nivel_618 + zone_size)
    
    # ZONA BAJA (Compras): en el fin (0%) -> de 0% a -19.1%
    zona_baja = (fin, fin - zone_size)
    
    return zona_alta, zona_media, zona_baja, fin + (impulse * 0.382)

if __name__ == "__main__":
    df = get_binance_klines()
    
    # 1. Encontrar el ATH absoluto
    ath_idx = df['high'].idxmax()
    abs_max = df.loc[ath_idx]['high']
    
    # 2. Cortar el gráfico desde el ATH hasta HOY
    df_bear = df.loc[ath_idx:].copy()
    
    # 3. Encontrar el fondo actual (el mínimo más bajo desde el ATH)
    current_bottom_idx = df_bear['low'].idxmin()
    current_bottom = df_bear.loc[current_bottom_idx]['low']
    
    current_price = df.iloc[-1]['close']
    
    print(f"--- MACRO BAJISTA ---")
    print(f"Origen (100%): {abs_max:.2f}")
    print(f"Fondo Actual (0%): {current_bottom:.2f}")
    print(f"Impulso: {abs_max - current_bottom:.2f} USDT")
    print("-" * 40)
    
    z_alta, z_media, z_baja, act_38 = calculate_bearish_zones(abs_max, current_bottom)
    
    print(f"ZONA ALTA (Ventas): {z_alta[0]:.2f} a {z_alta[1]:.2f}")
    print(f"ZONA MEDIA (Ventas): {z_media[0]:.2f} a {z_media[1]:.2f}")
    print(f"ZONA BAJA (Compras): {z_baja[0]:.2f} a {z_baja[1]:.2f}")
    print("-" * 40)
    print(f"Activación (38.2%): {act_38:.2f}")
    
    print(f"\n[ESTADO ACTUAL]")
    print(f"Precio Actual: {current_price:.2f}")
    
    if current_price <= z_alta[1] and current_price >= z_alta[0]:
        print("El precio está tocando la ZONA ALTA del Macro Bajista.")
    elif current_price <= z_media[1] and current_price >= z_media[0]:
        print("El precio está tocando la ZONA MEDIA del Macro Bajista.")
    elif current_price <= z_baja[0] and current_price >= z_baja[1]:
        print("El precio está tocando la ZONA BAJA del Macro Bajista.")
    else:
        print("El precio está FLOTANDO en el aire. ¡Caso 2!")
        print(">> El algoritmo debe BAJAR de temporalidad para buscar el Segundo Ciclo (Sub-ciclo).")
