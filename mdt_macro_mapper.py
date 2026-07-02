from mdt_data import get_binance_klines
from mdt_math import calc_zones, get_active_zones, apply_concurrency, format_z
from mdt_fractal import get_bullish_poc, get_bearish_poc

if __name__ == "__main__":
    print("\n" + "="*70)
    print(" MOTOR ESTRUCTURAL UNIVERSAL MDT (DUAL-TIMEFRAME 1D -> 2H)")
    print("="*70 + "\n")
    
    # ---------------------------------------------------------
    # PASO 1: VISIÓN MACRO (1D)
    # ---------------------------------------------------------
    df_1d = get_binance_klines("BNBUSDT", "1d")
    
    start_bull_idx = df_1d[df_1d['low'] > 182].index[df_1d[df_1d['low'] > 182]['low'] < 183.5].tolist()[-1]
    ath_idx = df_1d['high'].idxmax()
    abs_max = df_1d.loc[ath_idx]['high']
    
    df_post_ath = df_1d.loc[ath_idx:]
    bottom_idx = df_post_ath['low'].idxmin()
    abs_min = df_post_ath.loc[bottom_idx]['low']
    
    print("--- 1. IDENTIFICACIÓN Y ACTIVACIÓN DE CICLOS ---")
    
    buys = []
    sells = []
    alerts = []
    
    # =========================================================================
    # RUTA ALCISTA
    # =========================================================================
    
    macro_bull = calc_zones(df_1d.loc[start_bull_idx]['low'], abs_max, "BULLISH")
    macro_bull_status = get_active_zones(macro_bull, "BULLISH", df_1d, ath_idx)
    print(f"[MACRO ALCISTA (1D)] Origen: {macro_bull['origen']:.2f} | Fin: {abs_max:.2f}")
    
    if not macro_bull_status["CYCLE_DEAD"]:
        if macro_bull_status["ALTA"] or macro_bull_status["MEDIA"] or macro_bull_status["BAJA"]:
            if macro_bull_status["BAJA"]: buys.append({"name": "Macro Alcista (Baja)", "z": macro_bull['BAJA'], "peso": 100})
            if macro_bull_status["MEDIA"]: buys.append({"name": "Macro Alcista (Media)", "z": macro_bull['MEDIA'], "peso": 100})
            if macro_bull_status["ALTA"]: sells.append({"name": "Macro Alcista (Alta)", "z": macro_bull['ALTA'], "peso": 100})
        else:
            alerts.append({"name": "Macro Alcista", "activacion": macro_bull['activacion'], "zona_alerta": macro_bull['MEDIA'], "tipo": "COMPRAS"})

    # Regla 61.8%
    lowest_post_ath = df_1d.loc[ath_idx:, 'low'].min()
    nivel_618_macro = macro_bull['MEDIA'][0]
    
    if lowest_post_ath <= nivel_618_macro:
        print(f"   [!] REGLA 61.8%: El precio cayó a {lowest_post_ath:.2f}, barriendo el 61.8% ({nivel_618_macro:.2f}). Se frena búsqueda recursiva en Nivel 1.")
        stop_bull_recursion_at = 1
    else:
        stop_bull_recursion_at = 999
        
    biggest_bull = get_bullish_poc(df_1d, start_bull_idx, ath_idx)
    if biggest_bull:
        sub_bull = calc_zones(biggest_bull['trough'], abs_max, "BULLISH")
        sub_bull_status = get_active_zones(sub_bull, "BULLISH", df_1d, ath_idx)
        print(f"[SUB-C ALCISTA NIVEL 1 (1D)] Origen: {sub_bull['origen']:.2f} | Fin: {abs_max:.2f}")
        
        if not sub_bull_status["CYCLE_DEAD"]:
            if sub_bull_status["ALTA"] or sub_bull_status["MEDIA"] or sub_bull_status["BAJA"]:
                if sub_bull_status["BAJA"]: buys.append({"name": "Sub-C Alcista Nivel 1 (Baja)", "z": sub_bull['BAJA'], "peso": 99})
                if sub_bull_status["MEDIA"]: buys.append({"name": "Sub-C Alcista Nivel 1 (Media)", "z": sub_bull['MEDIA'], "peso": 99})
                if sub_bull_status["ALTA"]: sells.append({"name": "Sub-C Alcista Nivel 1 (Alta)", "z": sub_bull['ALTA'], "peso": 99})
            else:
                alerts.append({"name": "Sub-C Alcista Nivel 1", "activacion": sub_bull['activacion'], "zona_alerta": sub_bull['MEDIA'], "tipo": "COMPRAS"})
            
        # ZOOM A 2H PARA EL RESTO (Si no se frenó en 1)
        if stop_bull_recursion_at > 1:
            trough_date = df_1d.loc[biggest_bull['trough_idx'], 'open_time']
            print(f"   >>> HACIENDO ZOOM A 2H PARA EXTRACCIÓN ALCISTA (Desde: {trough_date})")
            current_df_bull = get_binance_klines("BNBUSDT", "2h", start_time=trough_date)
            ath_idx_bull = current_df_bull['high'].idxmax()
            current_search_idx_bull = 0
            valid_pocs_bull = []
            current_tf_bull = "2h"
            
            # Recolectar POCs con Stack Monótono
            while current_search_idx_bull < ath_idx_bull:
                poc_count = sum(1 for p in valid_pocs_bull if not p.get('is_boundary'))
                if poc_count >= 2 and current_tf_bull == "2h":
                    switch_time = current_df_bull.loc[current_search_idx_bull, 'open_time']
                    print(f"   >>> HACIENDO ZOOM A 30m PARA EXTRACCIÓN MICRO (A partir del Nivel 4, Desde: {switch_time})")
                    current_df_bull = get_binance_klines("BNBUSDT", "30m", start_time=switch_time)
                    ath_idx_bull = current_df_bull['high'].idxmax()
                    current_search_idx_bull = 0
                    current_tf_bull = "30m"
                    
                biggest_bull = get_bullish_poc(current_df_bull, current_search_idx_bull, ath_idx_bull)
                if biggest_bull is None: break
                
                # Prevent duplication after timeframe swap
                if valid_pocs_bull and biggest_bull['trough'] == valid_pocs_bull[-1].get('trough'):
                    current_search_idx_bull = int(biggest_bull['trough_idx'])
                    continue
                
                biggest_bull['tf'] = current_tf_bull
                
                if biggest_bull.get('type') == 'RESET':
                    # Pop de niveles engullidos
                    while valid_pocs_bull and valid_pocs_bull[-1].get('trough', 0) > biggest_bull['trough']:
                        popped = valid_pocs_bull.pop()
                        print(f"       -> [X] Nivel en {popped['trough']:.2f} invalidado (engullido por el reset).")
                    
                    # Añadir a la lista solo para registro cronológico visual
                    biggest_bull['is_boundary'] = True
                    valid_pocs_bull.append(biggest_bull)
                    
                    current_search_idx_bull = int(biggest_bull['trough_idx'])
                    continue
                
                valid_pocs_bull.append(biggest_bull)
                current_search_idx_bull = int(biggest_bull['trough_idx'])
                
            # Procesar Zonas
            nivel_counter = 2
            for poc in valid_pocs_bull:
                tf_label = poc.get('tf', '2h').upper()
                if poc.get('is_boundary'):
                    print(f"[PISO ESTRUCTURAL (RESET 61.8%)] Origen: {poc['trough']:.2f} | Fin: {abs_max:.2f} -> Límite de fractalidad")
                    continue
                
                sub_bull_2h = calc_zones(poc['trough'], abs_max, "BULLISH")
                sub_bull_status_2h = get_active_zones(sub_bull_2h, "BULLISH", current_df_bull, ath_idx_bull)
                
                name = f"Sub-C Alcista Nivel {nivel_counter}"
                print(f"[{name.upper()} ({tf_label})] Origen: {sub_bull_2h['origen']:.2f} | Fin: {abs_max:.2f}")
                
                if not sub_bull_status_2h["CYCLE_DEAD"]:
                    peso_actual = 100 - nivel_counter
                    if sub_bull_status_2h["ALTA"] or sub_bull_status_2h["MEDIA"] or sub_bull_status_2h["BAJA"]:
                        if sub_bull_status_2h["BAJA"]: buys.append({"name": f"{name} (Baja)", "z": sub_bull_2h['BAJA'], "peso": peso_actual})
                        if sub_bull_status_2h["MEDIA"]: buys.append({"name": f"{name} (Media)", "z": sub_bull_2h['MEDIA'], "peso": peso_actual})
                        if sub_bull_status_2h["ALTA"]: sells.append({"name": f"{name} (Alta)", "z": sub_bull_2h['ALTA'], "peso": peso_actual})
                    else:
                        alerts.append({"name": name, "activacion": sub_bull_2h['activacion'], "zona_alerta": sub_bull_2h['MEDIA'], "tipo": "COMPRAS"})
                    
                nivel_counter += 1
                
    # =========================================================================
    # RUTA BAJISTA
    # =========================================================================
    print("")
    macro_bear = calc_zones(abs_max, abs_min, "BEARISH")
    macro_bear_status = get_active_zones(macro_bear, "BEARISH", df_1d, bottom_idx)
    print(f"[MACRO BAJISTA (1D)] Origen: {abs_max:.2f} | Fin: {abs_min:.2f}")
    
    if not macro_bear_status["CYCLE_DEAD"]:
        if macro_bear_status["ALTA"] or macro_bear_status["MEDIA"] or macro_bear_status["BAJA"]:
            if macro_bear_status["BAJA"]: buys.append({"name": "Macro Bajista (Baja)", "z": macro_bear['BAJA'], "peso": 100})
            if macro_bear_status["ALTA"]: sells.append({"name": "Macro Bajista (Alta)", "z": macro_bear['ALTA'], "peso": 100})
            if macro_bear_status["MEDIA"]: sells.append({"name": "Macro Bajista (Media)", "z": macro_bear['MEDIA'], "peso": 100})
        else:
            alerts.append({"name": "Macro Bajista", "activacion": macro_bear['activacion'], "zona_alerta": macro_bear['MEDIA'], "tipo": "VENTAS"})

    highest_post_bottom = df_1d.loc[bottom_idx:, 'high'].max() if bottom_idx < len(df_1d)-1 else abs_min
    nivel_618_macro_bear = macro_bear['MEDIA'][1]
    
    if highest_post_bottom >= nivel_618_macro_bear:
        print(f"   [!] REGLA 61.8%: El precio subió a {highest_post_bottom:.2f}, barriendo el 61.8% ({nivel_618_macro_bear:.2f}). Se frena búsqueda recursiva en Nivel 1.")
        stop_bear_recursion_at = 1
    else:
        stop_bear_recursion_at = 999
        
    biggest_bear = get_bearish_poc(df_1d, ath_idx, bottom_idx)
    if biggest_bear:
        sub_bear = calc_zones(biggest_bear['peak'], abs_min, "BEARISH")
        sub_bear_status = get_active_zones(sub_bear, "BEARISH", df_1d, bottom_idx)
        print(f"[SUB-C BAJISTA NIVEL 1 (1D)] Origen: {sub_bear['origen']:.2f} | Fin: {abs_min:.2f}")
        
        if not sub_bear_status["CYCLE_DEAD"]:
            if sub_bear_status["ALTA"] or sub_bear_status["MEDIA"] or sub_bear_status["BAJA"]:
                if sub_bear_status["BAJA"]: buys.append({"name": "Sub-C Bajista Nivel 1 (Baja)", "z": sub_bear['BAJA'], "peso": 99})
                if sub_bear_status["ALTA"]: sells.append({"name": "Sub-C Bajista Nivel 1 (Alta)", "z": sub_bear['ALTA'], "peso": 99})
                if sub_bear_status["MEDIA"]: sells.append({"name": "Sub-C Bajista Nivel 1 (Media)", "z": sub_bear['MEDIA'], "peso": 99})
            else:
                alerts.append({"name": "Sub-C Bajista Nivel 1", "activacion": sub_bear['activacion'], "zona_alerta": sub_bear['MEDIA'], "tipo": "VENTAS"})
            
        # ZOOM A 2H PARA EL RESTO
        if stop_bear_recursion_at > 1:
            peak_date = df_1d.loc[biggest_bear['peak_idx'], 'open_time']
            print(f"   >>> HACIENDO ZOOM A 2H PARA EXTRACCIÓN BAJISTA (Desde: {peak_date})")
            current_df_bear = get_binance_klines("BNBUSDT", "2h", start_time=peak_date)
            bottom_idx_bear = current_df_bear['low'].idxmin()
            current_search_idx_bear = 0
            valid_pocs_bear = []
            current_tf_bear = "2h"
            
            # Recolectar POCs con Stack Monótono
            while current_search_idx_bear < bottom_idx_bear:
                # Check hot-swap a 30m
                poc_count = sum(1 for p in valid_pocs_bear if not p.get('is_boundary'))
                if poc_count >= 2 and current_tf_bear == "2h":
                    switch_time = current_df_bear.loc[current_search_idx_bear, 'open_time']
                    print(f"   >>> HACIENDO ZOOM A 30m PARA EXTRACCIÓN MICRO (A partir del Nivel 4, Desde: {switch_time})")
                    current_df_bear = get_binance_klines("BNBUSDT", "30m", start_time=switch_time)
                    bottom_idx_bear = current_df_bear['low'].idxmin()
                    current_search_idx_bear = 0
                    current_tf_bear = "30m"
                
                biggest_bear = get_bearish_poc(current_df_bear, current_search_idx_bear, bottom_idx_bear)
                if biggest_bear is None: break
                
                # Prevent duplication after timeframe swap
                if valid_pocs_bear and biggest_bear['peak'] == valid_pocs_bear[-1].get('peak'):
                    current_search_idx_bear = int(biggest_bear['peak_idx'])
                    continue
                
                biggest_bear['tf'] = current_tf_bear
                
                if biggest_bear.get('type') == 'RESET':
                    # Pop de niveles engullidos
                    while valid_pocs_bear and valid_pocs_bear[-1].get('peak', 0) < biggest_bear['peak']:
                        popped = valid_pocs_bear.pop()
                        print(f"       -> [X] Nivel en {popped['peak']:.2f} invalidado (engullido por el reset).")
                        
                    # Añadir a la lista solo para registro cronológico visual
                    biggest_bear['is_boundary'] = True
                    valid_pocs_bear.append(biggest_bear)
                    
                    current_search_idx_bear = int(biggest_bear['peak_idx'])
                    continue
                
                valid_pocs_bear.append(biggest_bear)
                current_search_idx_bear = int(biggest_bear['peak_idx'])
                
            # Procesar Zonas
            nivel_bajista = 2
            for poc in valid_pocs_bear:
                tf_label = poc.get('tf', '2h').upper()
                if poc.get('is_boundary'):
                    print(f"[TECHO ESTRUCTURAL (RESET 61.8%)] Origen: {poc['peak']:.2f} | Fin: {abs_min:.2f} -> Límite de fractalidad")
                    continue
                    
                sub_bear = calc_zones(poc['peak'], abs_min, "BEARISH")
                sub_bear_status = get_active_zones(sub_bear, "BEARISH", current_df_bear, bottom_idx_bear)
                
                name = f"Sub-C Bajista Nivel {nivel_bajista}"
                print(f"[{name.upper()} ({tf_label})] Origen: {sub_bear['origen']:.2f} | Fin: {abs_min:.2f}")
                
                if not sub_bear_status["CYCLE_DEAD"]:
                    peso_actual = 100 - nivel_bajista
                    if sub_bear_status["ALTA"] or sub_bear_status["MEDIA"] or sub_bear_status["BAJA"]:
                        if sub_bear_status["BAJA"]: buys.append({"name": f"{name} (Baja)", "z": sub_bear['BAJA'], "peso": peso_actual})
                        if sub_bear_status["ALTA"]: sells.append({"name": f"{name} (Alta)", "z": sub_bear['ALTA'], "peso": peso_actual})
                        if sub_bear_status["MEDIA"]: sells.append({"name": f"{name} (Media)", "z": sub_bear['MEDIA'], "peso": peso_actual})
                    else:
                        alerts.append({"name": name, "activacion": sub_bear['activacion'], "zona_alerta": sub_bear['MEDIA'], "tipo": "VENTAS"})
                    
                nivel_bajista += 1
                
    # =========================================================================
    # RUTA ALCISTA POST-FONDO (REBOTE)
    # =========================================================================
    bottom_date = df_1d.loc[bottom_idx, 'open_time']
    print(f"\n   >>> HACIENDO ZOOM A 30m PARA EXTRACCIÓN ALCISTA POST-FONDO (Desde: {bottom_date})")
    
    # We zoom into 30m starting from the 1D bottom date to capture intraday bounces
    df_post = get_binance_klines("BNBUSDT", "30m", start_time=bottom_date)
    bottom_idx_post = df_post['low'].idxmin()
    
    post_bottom_df = df_post.loc[bottom_idx_post:]
    highest_post_bottom_idx = post_bottom_df['high'].idxmax()
    
    if highest_post_bottom_idx > bottom_idx_post:
        abs_max_post = df_post.loc[highest_post_bottom_idx, 'high']
        print(f"--- 1.5. EXTRACCIÓN ALCISTA POST-FONDO (Rebote a {abs_max_post:.2f}) ---")
        
        abs_min_post = df_post.loc[bottom_idx_post, 'low']
        
        # Absolute post-bottom cycle
        macro_pb = calc_zones(abs_min_post, abs_max_post, "BULLISH")
        macro_pb_status = get_active_zones(macro_pb, "BULLISH", df_post, highest_post_bottom_idx)
        print(f"[MACRO ALCISTA POST-FONDO (30M)] Origen: {abs_min_post:.2f} | Fin: {abs_max_post:.2f}")
        
        if not macro_pb_status["CYCLE_DEAD"]:
            if macro_pb_status["ALTA"] or macro_pb_status["MEDIA"] or macro_pb_status["BAJA"]:
                if macro_pb_status["BAJA"]: buys.append({"name": "Macro Alcista Post-F (Baja)", "z": macro_pb['BAJA'], "peso": 96})
                if macro_pb_status["MEDIA"]: buys.append({"name": "Macro Alcista Post-F (Media)", "z": macro_pb['MEDIA'], "peso": 96})
                if macro_pb_status["ALTA"]: sells.append({"name": "Macro Alcista Post-F (Alta)", "z": macro_pb['ALTA'], "peso": 96})
            else:
                alerts.append({"name": "Macro Alcista Post-F", "activacion": macro_pb['activacion'], "zona_alerta": macro_pb['MEDIA'], "tipo": "COMPRAS"})
            
        valid_pocs_post_bull = []
        current_search_idx_pb = highest_post_bottom_idx
        
        while current_search_idx_pb > bottom_idx_post:
            biggest_bull_pb = get_bullish_poc(df_post, bottom_idx_post, current_search_idx_pb)
            if biggest_bull_pb is None: break
            
            if biggest_bull_pb.get('type') == 'RESET':
                while valid_pocs_post_bull and valid_pocs_post_bull[-1].get('trough', 999999) > biggest_bull_pb['trough']:
                    popped = valid_pocs_post_bull.pop()
                    print(f"       -> [X] Nivel en {popped['trough']:.2f} invalidado (engullido por el reset).")
                biggest_bull_pb['is_boundary'] = True
                valid_pocs_post_bull.append(biggest_bull_pb)
                current_search_idx_pb = int(biggest_bull_pb['trough_idx'])
                continue
            
            # Use 'drop' instead of 'impulse' for bullish POCs
            # Nota: si la cima del stack es un RESET (boundary), no tiene 'drop': se trata
            # como límite de fractalidad impenetrable (inf) y no se puede engullir.
            if valid_pocs_post_bull:
                if biggest_bull_pb['drop'] > valid_pocs_post_bull[-1].get('drop', float('inf')):
                    while valid_pocs_post_bull and biggest_bull_pb['drop'] > valid_pocs_post_bull[-1].get('drop', float('inf')):
                        popped = valid_pocs_post_bull.pop()
                        print(f"       -> [X] Nivel en {popped['trough']:.2f} invalidado (engullido por un fractal mayor).")
                    biggest_bull_pb['is_boundary'] = True
                    valid_pocs_post_bull.append(biggest_bull_pb)
                    current_search_idx_pb = int(biggest_bull_pb['trough_idx'])
                    continue
            
            valid_pocs_post_bull.append(biggest_bull_pb)
            current_search_idx_pb = int(biggest_bull_pb['trough_idx'])
            
        nivel_pb = 1
        for poc in reversed(valid_pocs_post_bull):
            if poc.get('is_boundary'):
                print(f"[FONDO ESTRUCTURAL POST (RESET)] Origen: {poc['trough']:.2f} | Fin: {abs_max_post:.2f}")
                continue
                
            pb_bull = calc_zones(poc['trough'], abs_max_post, "BULLISH")
            pb_bull_status = get_active_zones(pb_bull, "BULLISH", df_post, highest_post_bottom_idx)
            
            name = f"Sub-C Alcista Post-F Nivel {nivel_pb}"
            print(f"[{name.upper()} (30M)] Origen: {pb_bull['origen']:.2f} | Fin: {abs_max_post:.2f}")
            
            if not pb_bull_status["CYCLE_DEAD"]:
                peso_actual = 95 - nivel_pb 
                if pb_bull_status["ALTA"] or pb_bull_status["MEDIA"] or pb_bull_status["BAJA"]:
                    if pb_bull_status["BAJA"]: buys.append({"name": f"{name} (Baja)", "z": pb_bull['BAJA'], "peso": peso_actual})
                    if pb_bull_status["MEDIA"]: buys.append({"name": f"{name} (Media)", "z": pb_bull['MEDIA'], "peso": peso_actual})
                    if pb_bull_status["ALTA"]: sells.append({"name": f"{name} (Alta)", "z": pb_bull['ALTA'], "peso": peso_actual})
                else:
                    alerts.append({"name": name, "activacion": pb_bull['activacion'], "zona_alerta": pb_bull['MEDIA'], "tipo": "COMPRAS"})
                
            nivel_pb += 1

    # =========================================================================
    # CONCURRENCIA GLOBAL
    # =========================================================================
    print("\n--- 2. CONCURRENCIA GLOBAL DE ZONAS ACTIVAS ---")
    
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
        
    if alerts:
        print("\n--- 4. ZONAS EN EVOLUCION (ALERTAS NO ACTIVADAS) ---")
        for a in alerts:
            print(f" -> {a['name']}: Si el precio toca {a['activacion']:.2f} (38.2%), se activará Zona de {a['tipo']} en {format_z(a['zona_alerta'])}")
            
    current_price = df_1d.iloc[-1]['close']
    print(f"\nPRECIO ACTUAL: {current_price:.2f}")
