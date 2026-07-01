import pandas as pd
import requests
import time

def get_binance_klines(symbol="BNBUSDT", interval="1d"):
    url = "https://fapi.binance.com/fapi/v1/klines"
    all_klines = []
    end_time = int(time.time() * 1000)
    
    for _ in range(4):
        params = {"symbol": symbol, "interval": interval, "limit": 1500, "endTime": end_time}
        response = requests.get(url, params=params)
        data = response.json()
        if not data: break
        all_klines = data + all_klines
        end_time = data[0][0] - 1
        if len(data) < 1500: break
            
    cols = ["open_time", "open", "high", "low", "close", "vol", "close_time", "qav", "n", "tbbav", "tbqav", "i"]
    df = pd.DataFrame(all_klines, columns=cols)
    for c in ["open", "high", "low", "close"]: df[c] = pd.to_numeric(df[c])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df = df.drop_duplicates(subset=['open_time']).reset_index(drop=True)
    return df

def get_valid_retracements(df, start_idx, end_idx, abs_max_val):
    df_segment = df.loc[start_idx:end_idx].copy()
    retracements = []
    
    for i in range(start_idx, end_idx):
        peak_val = df_segment.loc[i, 'high']
        lowest_seen = peak_val
        for j in range(i + 1, end_idx + 1):
            curr_low = df_segment.loc[j, 'low']
            if curr_low < lowest_seen:
                lowest_seen = curr_low
            if df_segment.loc[j, 'high'] > peak_val:
                break
                
        drop = peak_val - lowest_seen
        if drop > 0:
            req_break = drop / 3.0
            actual_break = abs_max_val - peak_val
            if actual_break >= req_break:
                retracements.append({
                    'peak': peak_val, 'trough': lowest_seen, 'drop': drop
                })
                
    if not retracements:
        return []
    
    df_ret = pd.DataFrame(retracements)
    df_ret = df_ret.sort_values(by='drop', ascending=False).drop_duplicates(subset=['trough'])
    return df_ret.to_dict('records')

def calculate_mdt_zones(origen, fin):
    impulse = abs(origen - fin)
    zone_size = impulse * 0.191
    
    # Suponiendo ciclo BULLISH (Origen Abajo, Fin Arriba)
    zona_alta = (fin, fin + zone_size)
    zona_media = (fin - (impulse*0.618), fin - (impulse*0.618) - zone_size)
    zona_baja = (origen, origen - zone_size)
    
    return {
        'origen': origen, 'fin': fin, 'impulse': impulse,
        'ALTA_VENTAS': zona_alta,
        'MEDIA_COMPRAS': zona_media,
        'BAJA_COMPRAS': zona_baja
    }

def apply_concurrency(z_mayor, z_menor, zone_type):
    if zone_type in ["MEDIA_COMPRAS", "BAJA_COMPRAS"]:
        # El precio cae, ataca desde el número mayor hacia abajo
        inicio_mayor = max(z_mayor)
        fin_mayor = min(z_mayor)
        inicio_menor = max(z_menor)
        fin_menor = min(z_menor)
        
        # Caso 1: Inmersión Total
        if inicio_menor <= inicio_mayor and fin_menor >= fin_mayor:
            return None, "Caso 1 (Inmersión Total): Zona Menor ELIMINADA."
            
        # Caso 3: Sándwich (Mayor primero)
        if inicio_mayor >= inicio_menor:
            return None, "Caso 3 (Sándwich): Zona Menor ELIMINADA."
            
        # Caso 2: Ataque a Menor primero
        if inicio_menor > inicio_mayor:
            if fin_menor >= inicio_mayor: # Sin solape
                return z_menor, "Sin concurrencia: Zonas separadas."
                
            tam_menor = inicio_menor - fin_menor
            espacio_libre = inicio_menor - inicio_mayor
            if espacio_libre >= (tam_menor / 2.0):
                return (inicio_menor, inicio_mayor), f"Caso 2 (Ataque Menor): Válida, ACOTADA a {espacio_libre:.2f} USDT libres."
            else:
                return None, f"Caso 2 (Ataque Menor): ELIMINADA (Espacio libre {espacio_libre:.2f} < Mitad {tam_menor/2:.2f})."
                
    elif zone_type == "ALTA_VENTAS":
        # Precio sube, ataca desde abajo (numero menor)
        inicio_mayor = min(z_mayor)
        fin_mayor = max(z_mayor)
        inicio_menor = min(z_menor)
        fin_menor = max(z_menor)
        
        # Caso 1: Inmersión Total (Empiezan igual)
        if inicio_menor >= inicio_mayor and fin_menor <= fin_mayor:
            return None, "Caso 1 (Inmersión Total): Zona Menor ELIMINADA."
            
        # Caso 3: Sandwich
        if inicio_mayor <= inicio_menor:
            return None, "Caso 3 (Sándwich): Zona Menor ELIMINADA."
            
        # Caso 2: Ataque Menor
        if inicio_menor < inicio_mayor:
            if fin_menor <= inicio_mayor:
                return z_menor, "Sin concurrencia: Zonas separadas."
            tam_menor = fin_menor - inicio_menor
            espacio_libre = inicio_mayor - inicio_menor
            if espacio_libre >= (tam_menor / 2.0):
                return (inicio_menor, inicio_mayor), f"Caso 2: Válida y ACOTADA."
            else:
                return None, "Caso 2: ELIMINADA por falta de espacio."

def print_zone(name, z):
    if z is None:
        return "ELIMINADA"
    return f"{max(z):.2f} a {min(z):.2f}"

if __name__ == "__main__":
    print("\n" + "="*60)
    print(" MOTOR MDT: MAPEO ESTRUCTURAL Y CONCURRENCIA DE ZONAS")
    print("="*60 + "\n")
    
    df = get_binance_klines()
    # Filtramos para empezar exactamente en el origen Macro validado de 182.97 (junio 2022)
    start_idx = df[df['low'] > 182].index[df[df['low'] > 182]['low'] < 183.5].tolist()[-1] 
    ath_idx = df['high'].idxmax()
    abs_max_val = df.loc[ath_idx]['high']
    
    # Buscar el pico fallido
    df_to_ath = df.loc[start_idx:ath_idx]
    failed_peak_idx = df_to_ath[df_to_ath['high'] >= 1362].index[0]
    
    # 1. Obtener todos los retrocesos válidos
    valid_cycles = get_valid_retracements(df, start_idx, failed_peak_idx, abs_max_val)
    
    if len(valid_cycles) >= 1:
        # El sub-ciclo operable es el más grande validado después del origen
        origen_macro = df.loc[start_idx]['low']
        origen_subciclo = valid_cycles[0]['trough']
        
        print(f"--- 1. IDENTIFICACIÓN DE CICLOS ---")
        print(f"[MACRO] Origen: {origen_macro:.2f} | Techo Arrastrado: {abs_max_val:.2f}")
        print(f"[SUB-CICLO] Origen: {origen_subciclo:.2f} | Techo Arrastrado: {abs_max_val:.2f} (Validado por caída de {valid_cycles[0]['drop']:.2f})\n")
        
        # 2. Calcular Zonas
        z_macro = calculate_mdt_zones(origen_macro, abs_max_val)
        z_sub = calculate_mdt_zones(origen_subciclo, abs_max_val)
        
        print(f"--- 2. ZONAS BRUTAS (Sin Filtro) ---")
        print(f"MACRO ZONA MEDIA: {z_macro['MEDIA_COMPRAS'][0]:.2f} a {z_macro['MEDIA_COMPRAS'][1]:.2f}")
        print(f"SUB-C ZONA MEDIA: {z_sub['MEDIA_COMPRAS'][0]:.2f} a {z_sub['MEDIA_COMPRAS'][1]:.2f}\n")
        
        # 3. Aplicar Concurrencia
        print(f"--- 3. RESOLUCIÓN DE CONCURRENCIA (REGLAS J. VEGA) ---")
        
        alta_final, alta_razon = apply_concurrency(z_macro['ALTA_VENTAS'], z_sub['ALTA_VENTAS'], "ALTA_VENTAS")
        print(f"[ZONA ALTA - Ventas]")
        print(f"  Analisis: {alta_razon}")
        
        media_final, media_razon = apply_concurrency(z_macro['MEDIA_COMPRAS'], z_sub['MEDIA_COMPRAS'], "MEDIA_COMPRAS")
        print(f"\n[ZONA MEDIA - Compras]")
        print(f"  Analisis: {media_razon}")
        
        baja_final, baja_razon = apply_concurrency(z_macro['BAJA_COMPRAS'], z_sub['BAJA_COMPRAS'], "BAJA_COMPRAS")
        print(f"\n[ZONA BAJA - Compras]")
        print(f"  Analisis: {baja_razon}\n")
        
        print(f"--- 4. ZONAS OPERATIVAS FINALES LIMPIAS ---")
        print(f"ZONA ALTA (Macro): {print_zone('ALTA', z_macro['ALTA_VENTAS'])}")
        print(f"ZONA ALTA (Sub):   {print_zone('ALTA', alta_final)}")
        print("-" * 40)
        print(f"ZONA MEDIA (Sub):  {print_zone('MEDIA', media_final)}  <-- Ataca Primero")
        print(f"ZONA MEDIA (Macro):{print_zone('MEDIA', z_macro['MEDIA_COMPRAS'])}")
        print("-" * 40)
        print(f"ZONA BAJA (Sub):   {print_zone('BAJA', baja_final)}")
        print(f"ZONA BAJA (Macro): {print_zone('BAJA', z_macro['BAJA_COMPRAS'])}")
        
