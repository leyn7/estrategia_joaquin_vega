import sys
sys.path.insert(0, r"C:\Users\leyner\Documents\proyectos\trading\estrategia_joaquin_vega")
from mdt_data import get_binance_klines
from mdt_patrones import detect_patron_institucional

df = get_binance_klines("BNBUSDT", "4h").tail(500).reset_index(drop=True)
df['open_time'] = df['open_time'].dt.tz_localize('UTC').dt.tz_convert('America/Bogota')

zona_max, zona_min = 638.18, 410.57  # Macro Alcista (Media) - COMPRAS - patron en 4H (una TF bajo 1D)
print(f"Zona COMPRAS Macro Alcista (Media): {zona_max} a {zona_min} | Mitad: {(zona_max+zona_min)/2:.2f}")
print(f"Precio actual: {df.iloc[-1]['close']:.2f} | Min ultimas 10h: {df['low'].min():.2f}\n")

res = detect_patron_institucional(df, zona_max, zona_min, "BUY")
print(f"Estado: {res['estado']}")
print(f"Mensaje: {res['mensaje']}")
if 'detalles' in res:
    d = res['detalles']
    print(f"P1: {d.get('pauta1_price', 0):.2f} | P2: {d.get('pauta2_price', 0):.2f} | Engaños: {d.get('fibo_1382', 0):.2f} a {d.get('fibo_1618', 0):.2f} | Proporcional: {d.get('proporcional', '?')}")
