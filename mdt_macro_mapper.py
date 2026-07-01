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

def find_bullish_retracements(df, start_idx, end_idx, abs_max_val):
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
                retracements.append({'peak': peak_val, 'trough': lowest_seen, 'drop': drop})
    if not retracements: return []
    df_ret = pd.DataFrame(retracements).sort_values(by='drop', ascending=False).drop_duplicates(subset=['trough'])
    return df_ret.to_dict('records')

def find_bearish_bounces(df, start_idx, current_bottom_idx, abs_min_val):
    df_segment = df.loc[start_idx:current_bottom_idx].copy()
    bounces = []
    for i in range(start_idx, current_bottom_idx):
        trough_val = df_segment.loc[i, 'low']
        highest_seen = trough_val
        for j in range(i + 1, current_bottom_idx + 1):
            curr_high = df_segment.loc[j, 'high']
            if curr_high > highest_seen:
                highest_seen = curr_high
            if df_segment.loc[j, 'low'] < trough_val:
                break
        bounce = highest_seen - trough_val
        if bounce > 0:
            req_break = bounce / 3.0
            actual_break = trough_val - abs_min_val
            if actual_break >= req_break:
                bounces.append({'peak': highest_seen, 'trough': trough_val, 'bounce': bounce})
    if not bounces: return []
    df_b = pd.DataFrame(bounces).sort_values(by='bounce', ascending=False).drop_duplicates(subset=['peak'])
    return df_b.to_dict('records')

def calc_zones(origen, fin, direction="BULLISH"):
    impulse = abs(origen - fin)
    zone_size = impulse * 0.191
    if direction == "BULLISH":
        z_alta = (fin, fin + zone_size)
        z_media = (fin - (impulse*0.618), fin - (impulse*0.618) - zone_size)
        z_baja = (origen, origen - zone_size)
        act = fin - (impulse*0.382)
    else:
        z_alta = (origen, origen + zone_size)
        z_media = (fin + (impulse*0.618), fin + (impulse*0.618) + zone_size)
        z_baja = (fin, fin - zone_size)
        act = fin + (impulse*0.382)
    return {'origen': origen, 'fin': fin, 'impulse': impulse, 'ALTA': z_alta, 'MEDIA': z_media, 'BAJA': z_baja, 'activacion': act}

def is_active(zone_data, direction, df, post_fin_idx):
    if post_fin_idx >= len(df): return False
    df_post = df.loc[post_fin_idx:]
    if direction == "BULLISH":
        min_post = df_post['low'].min()
        return min_post <= zone_data['activacion']
    else:
        max_post = df_post['high'].max()
        return max_post >= zone_data['activacion']

def apply_concurrency(z_mayor, z_menor, buy_or_sell):
    if buy_or_sell == "BUY": # Ataca desde arriba
        imay, fmay = max(z_mayor), min(z_mayor)
        imen, fmen = max(z_menor), min(z_menor)
        
        if imen <= imay and fmen >= fmay: return None, "Caso 1 (Inmersión Total)"
        if imay >= imen: return None, "Caso 3 (Sándwich)"
        if imen > imay:
            if fmen >= imay: return z_menor, "Sin Concurrencia"
            free = imen - imay
            if free >= (imen - fmen)/2.0: return (imen, imay), f"Caso 2 (ACOTADA a {free:.2f})"
            return None, "Caso 2 (ELIMINADA por falta de espacio)"
            
    else: # SELL: Ataca desde abajo
        imay, fmay = min(z_mayor), max(z_mayor)
        imen, fmen = min(z_menor), max(z_menor)
        
        if imen >= imay and fmen <= fmay: return None, "Caso 1 (Inmersión Total)"
        if imay <= imen: return None, "Caso 3 (Sándwich)"
        if imen < imay:
            if fmen <= imay: return z_menor, "Sin Concurrencia"
            free = imay - imen
            if free >= (fmen - imen)/2.0: return (imen, imay), f"Caso 2 (ACOTADA a {free:.2f})"
            return None, "Caso 2 (ELIMINADA por falta de espacio)"

def format_z(z):
    if z is None: return "ELIMINADA"
    return f"{max(z):.2f} a {min(z):.2f}"

if __name__ == "__main__":
    print("\n" + "="*70)
    print(" MOTOR ESTRUCTURAL UNIVERSAL MDT (ALCISTA Y BAJISTA)")
    print("="*70 + "\n")
    
    df = get_binance_klines()
    
    # 1. ENCONTRAR EXTREMOS
    start_bull_idx = df[df['low'] > 182].index[df[df['low'] > 182]['low'] < 183.5].tolist()[-1] 
    ath_idx = df['high'].idxmax()
    abs_max = df.loc[ath_idx]['high']
    
    df_bear = df.loc[ath_idx:]
    bottom_idx = df_bear['low'].idxmin()
    abs_min = df_bear.loc[bottom_idx]['low']
    
    # 2. BUSCAR CICLOS
    bull_cycles = find_bullish_retracements(df, start_bull_idx, ath_idx, abs_max)
    bear_cycles = find_bearish_bounces(df, ath_idx, bottom_idx, abs_min)
    
    print("--- 1. IDENTIFICACIÓN Y ACTIVACIÓN DE CICLOS ---")
    
    # MACRO ALCISTA
    macro_bull = calc_zones(df.loc[start_bull_idx]['low'], abs_max, "BULLISH")
    macro_bull_act = is_active(macro_bull, "BULLISH", df, ath_idx)
    print(f"[MACRO ALCISTA] Origen: {macro_bull['origen']:.2f} | Fin: {abs_max:.2f}")
    print(f"   > Estado: {'ACTIVO' if macro_bull_act else 'INACTIVO'} (Activación: {macro_bull['activacion']:.2f})")
    
    # SUB-CICLO ALCISTA
    sub_bull = None
    sub_bull_act = False
    if bull_cycles:
        sub_bull = calc_zones(bull_cycles[0]['trough'], abs_max, "BULLISH")
        sub_bull_act = is_active(sub_bull, "BULLISH", df, ath_idx)
        print(f"[SUB-CICLO ALCISTA] Origen: {sub_bull['origen']:.2f} | Fin: {abs_max:.2f}")
        print(f"   > Estado: {'ACTIVO' if sub_bull_act else 'INACTIVO'} (Activación: {sub_bull['activacion']:.2f})")
        
    # MACRO BAJISTA
    macro_bear = calc_zones(abs_max, abs_min, "BEARISH")
    macro_bear_act = is_active(macro_bear, "BEARISH", df, bottom_idx)
    print(f"[MACRO BAJISTA] Origen: {abs_max:.2f} | Fin: {abs_min:.2f}")
    print(f"   > Estado: {'ACTIVO' if macro_bear_act else 'INACTIVO'} (Activación: {macro_bear['activacion']:.2f})")
    
    # SUB-CICLO BAJISTA
    sub_bear = None
    sub_bear_act = False
    if bear_cycles:
        sub_bear = calc_zones(bear_cycles[0]['peak'], abs_min, "BEARISH")
        sub_bear_act = is_active(sub_bear, "BEARISH", df, bottom_idx)
        print(f"[SUB-CICLO BAJISTA] Origen: {sub_bear['origen']:.2f} | Fin: {abs_min:.2f}")
        print(f"   > Estado: {'ACTIVO' if sub_bear_act else 'INACTIVO'} (Activación: {sub_bear['activacion']:.2f})")
        
    print("\n--- 2. CONCURRENCIA GLOBAL DE ZONAS ACTIVAS ---")
    
    # Recopilamos todas las zonas de COMPRAS activas (Bajas bajistas, Medias/Bajas alcistas)
    buys = []
    if macro_bull_act:
        buys.append({"name": "Macro Alcista (Media)", "z": macro_bull['MEDIA'], "peso": 4})
        buys.append({"name": "Macro Alcista (Baja)", "z": macro_bull['BAJA'], "peso": 4})
    if sub_bull_act:
        buys.append({"name": "Sub-C Alcista (Media)", "z": sub_bull['MEDIA'], "peso": 3})
        buys.append({"name": "Sub-C Alcista (Baja)", "z": sub_bull['BAJA'], "peso": 3})
    if macro_bear_act:
        buys.append({"name": "Macro Bajista (Baja)", "z": macro_bear['BAJA'], "peso": 2})
    if sub_bear_act:
        buys.append({"name": "Sub-C Bajista (Baja)", "z": sub_bear['BAJA'], "peso": 1})
        
    buys = sorted(buys, key=lambda x: max(x['z']), reverse=True)
    
    print("\n[ZONAS DE COMPRAS]")
    final_buys = []
    for i in range(len(buys)):
        current = buys[i]
        if current['z'] is None: continue
        
        for j in range(len(buys)):
            if i == j: continue
            mayor = buys[j]
            if mayor['z'] is None: continue
            
            if mayor['peso'] > current['peso']:
                new_z, razon = apply_concurrency(mayor['z'], current['z'], "BUY")
                if new_z != current['z']:
                    print(f"[{current['name']} vs {mayor['name']}] -> {razon}")
                current['z'] = new_z
                if current['z'] is None:
                    break
                
        if current['z'] is not None:
            final_buys.append(current)
            
    # ZONAS DE VENTAS
    sells = []
    if macro_bull_act:
        sells.append({"name": "Macro Alcista (Alta)", "z": macro_bull['ALTA'], "peso": 4})
    if sub_bull_act:
        sells.append({"name": "Sub-C Alcista (Alta)", "z": sub_bull['ALTA'], "peso": 3})
    if macro_bear_act:
        sells.append({"name": "Macro Bajista (Alta)", "z": macro_bear['ALTA'], "peso": 2})
        sells.append({"name": "Macro Bajista (Media)", "z": macro_bear['MEDIA'], "peso": 2})
    if sub_bear_act:
        sells.append({"name": "Sub-C Bajista (Alta)", "z": sub_bear['ALTA'], "peso": 1})
        sells.append({"name": "Sub-C Bajista (Media)", "z": sub_bear['MEDIA'], "peso": 1})
        
    sells = sorted(sells, key=lambda x: min(x['z']))
    
    print("\n[ZONAS DE VENTAS]")
    final_sells = []
    for i in range(len(sells)):
        current = sells[i]
        if current['z'] is None: continue
        for j in range(len(sells)):
            if i == j: continue
            otro = sells[j]
            if otro['z'] is None: continue
            
            # Solo aplicamos concurrencia si el otro es de MAYOR peso estructural
            if otro['peso'] > current['peso']:
                new_z, razon = apply_concurrency(otro['z'], current['z'], "SELL")
                if new_z != current['z']:
                    print(f"[{current['name']} vs {otro['name']}] -> {razon}")
                current['z'] = new_z
                if current['z'] is None: break
                
        if current['z'] is not None:
            final_sells.append(current)
            
    print("\n--- 3. ZONAS OPERATIVAS FINALES ---")
    print("ZONAS DE VENTAS:")
    for s in final_sells:
        print(f" -> {s['name']}: {format_z(s['z'])}")
    print("\nZONAS DE COMPRAS:")
    for b in final_buys:
        print(f" -> {b['name']}: {format_z(b['z'])}")
        
    current_price = df.iloc[-1]['close']
    print(f"\nPRECIO ACTUAL: {current_price:.2f}")
