from mdt_data import get_binance_klines

def find_micro_fractals(df):
    peaks = []
    troughs = []
    for i in range(2, len(df) - 2):
        is_peak = (df.loc[i, 'high'] > df.loc[i-1, 'high'] and 
                   df.loc[i, 'high'] > df.loc[i-2, 'high'] and 
                   df.loc[i, 'high'] > df.loc[i+1, 'high'] and 
                   df.loc[i, 'high'] > df.loc[i+2, 'high'])
                   
        is_trough = (df.loc[i, 'low'] < df.loc[i-1, 'low'] and 
                     df.loc[i, 'low'] < df.loc[i-2, 'low'] and 
                     df.loc[i, 'low'] < df.loc[i+1, 'low'] and 
                     df.loc[i, 'low'] < df.loc[i+2, 'low'])
                     
        if is_peak: peaks.append(i)
        if is_trough: troughs.append(i)
    return peaks, troughs

def evaluate_peak_as_p1(df, p1_idx, zona_max, zona_min, direction):
    p1_val = df.loc[p1_idx, 'high'] if direction == "SELL" else df.loc[p1_idx, 'low']
    p2_val = df.loc[p1_idx, 'low'] if direction == "SELL" else df.loc[p1_idx, 'high']
    p2_idx = p1_idx
    p2_locked = False
    start_p3 = None
    
    for i in range(p1_idx + 1, len(df)):
        h = df.loc[i, 'high']
        l = df.loc[i, 'low']
        if direction == "SELL":
            if h > p1_val:
                p2_locked = True
                start_p3 = i
                break
            if l < p2_val:
                p2_val = l; p2_idx = i
        else:
            if l < p1_val:
                p2_locked = True
                start_p3 = i
                break
            if h > p2_val:
                p2_val = h; p2_idx = i
                
    impulso = abs(p1_val - p2_val)
    if impulso == 0: return {"estado": "ANULADO", "mensaje": "Impulso cero."}

    if direction == "SELL":
        fibo_1618 = p2_val + (impulso * 1.618)
        fibo_1382 = p2_val + (impulso * 1.382)
    else:
        fibo_1618 = p2_val - (impulso * 1.618)
        fibo_1382 = p2_val - (impulso * 1.382)

    # Proporcionalidad: al menos UNO de los niveles de la Zona de Engaños (138.2 o 161.8)
    # debe quedar más allá de la mitad de la zona operativa. Como el 161.8 es siempre el
    # más profundo, basta con chequear que el 161.8 cruce la mitad. Si no, NUNCA se opera.
    mitad_zona = (zona_max + zona_min) / 2.0
    if direction == "SELL":
        proporcional = fibo_1618 >= mitad_zona
    else:
        proporcional = fibo_1618 <= mitad_zona

    detalles = {
        "pauta1_time": df.loc[p1_idx, 'open_time'],
        "pauta1_price": p1_val,
        "pauta2_time": df.loc[p2_idx, 'open_time'],
        "pauta2_price": p2_val,
        "impulso": impulso,
        "fibo_1382": fibo_1382,
        "fibo_1618": fibo_1618,
        "mitad_zona": mitad_zona,
        "proporcional": proporcional
    }

    if not p2_locked:
        # Fibo dinámico: la Pauta 2 sigue viva y la Zona de Engaños se mueve con cada nuevo extremo.
        detalles["calidad"] = "PROYECCION PROPORCIONAL" if proporcional else "PROYECCION NO PROPORCIONAL (por ahora)"
        return {"estado": "EN_FORMACION_PAUTA_2",
                "mensaje": f"Formando Pauta 2 (actualmente {p2_val:.2f}). Zona de Engaños proyectada: {fibo_1382:.2f} a {fibo_1618:.2f}",
                "detalles": detalles}

    if direction == "SELL" and fibo_1618 > zona_max:
        return {"estado": "ANULADO_POR_ESCAPE", "mensaje": "El 161.8% se proyecta fuera de la zona (sale por arriba)", "detalles": detalles, "idx_muerte": start_p3}
    if direction == "BUY" and fibo_1618 < zona_min:
        return {"estado": "ANULADO_POR_ESCAPE", "mensaje": "El 161.8% se proyecta fuera de la zona (sale por abajo)", "detalles": detalles, "idx_muerte": start_p3}

    if not proporcional:
        # Patrón NO proporcional: no se opera jamás. Se rastrea su Pauta 3 hasta que el precio
        # deje un extremo y rompa la Pauta 2: ese extremo será el P1 del siguiente engaño (evolución).
        detalles["calidad"] = "NO PROPORCIONAL (Zona de Engaños no llega a la mitad de la zona)"
        pico_evo = p1_val
        idx_pico_evo = p1_idx
        for j in range(start_p3, len(df)):
            h = df.loc[j, 'high']
            l = df.loc[j, 'low']
            if direction == "SELL":
                if h > pico_evo:
                    pico_evo = h; idx_pico_evo = j
                    if pico_evo > zona_max:
                        return {"estado": "ANULADO_POR_ESCAPE", "mensaje": "Escape de zona durante patrón no proporcional", "detalles": detalles, "idx_muerte": j}
                if l < p2_val:
                    detalles["extremo_evolucion"] = pico_evo
                    return {"estado": "ANULADO_POR_PROPORCIONALIDAD",
                            "mensaje": f"Patrón no proporcional roto (nuevo mínimo bajo la Pauta 2). Evoluciona: nuevo P1 en {pico_evo:.2f}",
                            "detalles": detalles, "idx_muerte": idx_pico_evo}
            else: # BUY
                if l < pico_evo:
                    pico_evo = l; idx_pico_evo = j
                    if pico_evo < zona_min:
                        return {"estado": "ANULADO_POR_ESCAPE", "mensaje": "Escape de zona durante patrón no proporcional", "detalles": detalles, "idx_muerte": j}
                if h > p2_val:
                    detalles["extremo_evolucion"] = pico_evo
                    return {"estado": "ANULADO_POR_PROPORCIONALIDAD",
                            "mensaje": f"Patrón no proporcional roto (nuevo máximo sobre la Pauta 2). Evoluciona: nuevo P1 en {pico_evo:.2f}",
                            "detalles": detalles, "idx_muerte": idx_pico_evo}
        return {"estado": "NO_PROPORCIONAL_EN_CURSO",
                "mensaje": "Patrón vivo pero NO operable (no proporcional). Esperando evolución al siguiente engaño.",
                "detalles": detalles}

    calidad = "BUENA"
    detalles["calidad"] = calidad
    
    toco_1618 = False
    pico_engano = p1_val
    gatillo = False
    idx_gatillo = None
    cayo_bajo_1382 = False
    carencia_idx = None  # Gatillo prematuro (con carencia): NO es entrada, es patrón vivo no operable

    for j in range(start_p3, len(df)):
        h = df.loc[j, 'high']
        l = df.loc[j, 'low']
        c = df.loc[j, 'close']

        if direction == "SELL":
            if not toco_1618:
                if h >= fibo_1618:
                    toco_1618 = True; pico_engano = h
                    if carencia_idx is not None:
                        # Era un engaño fraccionado: regresó y consumió el 161.8%. Se completa.
                        carencia_idx = None
                        calidad = "BUENA (Engaño fraccionado completado)"
                        detalles["calidad"] = calidad
                    if l <= p1_val and c <= p1_val: gatillo = True; idx_gatillo = j; break
                else:
                    if h > pico_engano:
                        pico_engano = h
                    if carencia_idx is None and l <= p1_val and c <= p1_val and pico_engano >= fibo_1382:
                        # Carencia (cruzó 138.2 pero no tocó 161.8): gatillo prematuro, NO se opera.
                        # Queda vivo esperando: consumo del 161.8 (fraccionado) o Validación Posterior.
                        calidad = "DEBIL (Carencia)"
                        detalles["calidad"] = calidad
                        carencia_idx = j
                    if carencia_idx is not None and l < p2_val:
                        # VALIDACIÓN POSTERIOR (Sección 12): tras el gatillo con carencia, el precio
                        # rompió con fuerza el origen de la Pauta 3 (extremo de la Pauta 2).
                        # El engaño se valida retroactivamente: SOLO entrada calmada.
                        min_post = df.loc[j:, 'low'].min()  # extremo del impulso confirmado hasta ahora
                        impulso_conf = pico_engano - min_post
                        fibo_618_seg = pico_engano - (impulso_conf * 0.618)
                        detalles["stop_loss"] = pico_engano
                        detalles["extremo_impulso"] = min_post
                        detalles["espera_calmada"] = fibo_618_seg
                        detalles["fibo_seguimiento_618"] = fibo_618_seg
                        detalles["hora_validacion"] = df.loc[j, 'open_time']
                        detalles["calidad"] = "VALIDADO POSTERIOR (solo entrada calmada)"
                        return {"estado": "VALIDADO_POSTERIOR",
                                "mensaje": f"Carencia validada retroactivamente (rompió {p2_val:.2f}). Esperar retroceso calmado a {fibo_618_seg:.2f}",
                                "detalles": detalles}
            else:
                if h > pico_engano:
                    pico_engano = h
                    if pico_engano > zona_max: return {"estado": "ANULADO_POR_ESCAPE", "mensaje": "Escape de zona tras tocar 161.8%", "detalles": detalles, "idx_muerte": j}
                if l < fibo_1382: cayo_bajo_1382 = True
                if cayo_bajo_1382 and h >= (pico_engano - (impulso * 0.1)):
                    return {"estado": "ROTO_POR_DOBLE_TOQUE", "mensaje": "Retesteó nivel engaño", "detalles": detalles, "idx_muerte": j}
                if l <= p1_val and c <= p1_val:
                    gatillo = True; idx_gatillo = j; break
        else: # BUY
            if not toco_1618:
                if l <= fibo_1618:
                    toco_1618 = True; pico_engano = l
                    if carencia_idx is not None:
                        carencia_idx = None
                        calidad = "BUENA (Engaño fraccionado completado)"
                        detalles["calidad"] = calidad
                    if h >= p1_val and c >= p1_val: gatillo = True; idx_gatillo = j; break
                else:
                    if l < pico_engano:
                        pico_engano = l
                    if carencia_idx is None and h >= p1_val and c >= p1_val and pico_engano <= fibo_1382:
                        calidad = "DEBIL (Carencia)"
                        detalles["calidad"] = calidad
                        carencia_idx = j
                    if carencia_idx is not None and h > p2_val:
                        max_post = df.loc[j:, 'high'].max()
                        impulso_conf = max_post - pico_engano
                        fibo_618_seg = pico_engano + (impulso_conf * 0.618)
                        detalles["stop_loss"] = pico_engano
                        detalles["extremo_impulso"] = max_post
                        detalles["espera_calmada"] = fibo_618_seg
                        detalles["fibo_seguimiento_618"] = fibo_618_seg
                        detalles["hora_validacion"] = df.loc[j, 'open_time']
                        detalles["calidad"] = "VALIDADO POSTERIOR (solo entrada calmada)"
                        return {"estado": "VALIDADO_POSTERIOR",
                                "mensaje": f"Carencia validada retroactivamente (rompió {p2_val:.2f}). Esperar retroceso calmado a {fibo_618_seg:.2f}",
                                "detalles": detalles}
            else:
                if l < pico_engano:
                    pico_engano = l
                    if pico_engano < zona_min: return {"estado": "ANULADO_POR_ESCAPE", "mensaje": "Escape de zona tras tocar 161.8%", "detalles": detalles, "idx_muerte": j}
                if h > fibo_1382: cayo_bajo_1382 = True
                if cayo_bajo_1382 and l <= (pico_engano + (impulso * 0.1)):
                    return {"estado": "ROTO_POR_DOBLE_TOQUE", "mensaje": "Retesteó nivel engaño", "detalles": detalles, "idx_muerte": j}
                if h >= p1_val and c >= p1_val:
                    gatillo = True; idx_gatillo = j; break

    if gatillo:
        # Gatillo REAL (consumió el 161.8): verificamos si el precio rompe el Stop Loss (Pico del engaño)
        for k in range(idx_gatillo + 1, len(df)):
            if direction == "SELL" and df.loc[k, 'high'] > pico_engano:
                return {"estado": "ROTO_POR_STOP_LOSS", "mensaje": "El precio saltó el Stop Loss.", "detalles": detalles, "idx_muerte": k}
            if direction == "BUY" and df.loc[k, 'low'] < pico_engano:
                return {"estado": "ROTO_POR_STOP_LOSS", "mensaje": "El precio saltó el Stop Loss.", "detalles": detalles, "idx_muerte": k}

        impulso_seg = abs(pico_engano - p2_val)
        fibo_618_seg = pico_engano - (impulso_seg * 0.618) if direction == "SELL" else pico_engano + (impulso_seg * 0.618)
        detalles["stop_loss"] = pico_engano
        detalles["gatillo_agresivo"] = p1_val
        detalles["espera_calmada"] = fibo_618_seg
        detalles["fibo_seguimiento_618"] = fibo_618_seg
        detalles["hora_gatillo"] = df.loc[idx_gatillo, 'open_time']
        return {"estado": "GATILLO_ACTIVADO", "mensaje": "¡Engaño Completado! Entrada lista.", "detalles": detalles}

    if carencia_idx is not None:
        return {"estado": "ANULADO_POR_CARENCIA",
                "mensaje": "Entrada con Carencia (viva pero no operable). Esperando 161.8% o Validación Posterior.",
                "detalles": detalles}

    if not toco_1618:
        return {"estado": "ESPERANDO_1618", "mensaje": f"Buscando 161.8% en {fibo_1618:.2f}", "detalles": detalles}
    return {"estado": "ENGAÑO_EN_CURSO", "mensaje": "Esperando Gatillo.", "detalles": detalles}

def detect_patron_institucional(df, zona_max, zona_min, direction):
    peaks, troughs = find_micro_fractals(df)
    fractals = peaks if direction == "SELL" else troughs
    
    # Solo nos importan los fractales que están dentro de la zona
    fractals_en_zona = [f for f in fractals if zona_min <= (df.loc[f, 'high'] if direction == "SELL" else df.loc[f, 'low']) <= zona_max]
    
    if not fractals_en_zona:
        return {"estado": "NO_INICIADO", "mensaje": "No hay picos en la zona."}
        
    numero_engano = 1
    idx_inicio_busqueda = fractals_en_zona[0]
    ultimo_resultado = {"estado": "NO_INICIADO", "mensaje": "Error desconocido."}
    
    while numero_engano <= 3:
        # Encontrar el primer fractal válido DESPUÉS del idx_inicio_busqueda
        fractales_validos = [f for f in fractals_en_zona if f >= idx_inicio_busqueda]
        if not fractales_validos:
            break
            
        p1_idx = fractales_validos[0]
        res = evaluate_peak_as_p1(df, p1_idx, zona_max, zona_min, direction)
        
        # Añadimos metadatos del nivel de engaño
        nombre_engano = "PRIMER ENGAÑO" if numero_engano == 1 else "SEGUNDO ENGAÑO" if numero_engano == 2 else "TERCER ENGAÑO"
        if "detalles" in res:
            res["detalles"]["nivel_engano"] = nombre_engano
            if numero_engano == 3 and res["estado"] == "GATILLO_ACTIVADO":
                res["detalles"]["sugerencia_volumen"] = "Medio Volumen (Aviso Joaquín)"
            else:
                res["detalles"]["sugerencia_volumen"] = "Volumen Normal"
        
        ultimo_resultado = res
        
        # Si el patrón fracasó por completo (SL, Doble Toque, Escape o No Proporcional roto),
        # el institucional hará uno nuevo: evolucionamos al siguiente engaño.
        if res["estado"] in ["ROTO_POR_STOP_LOSS", "ROTO_POR_DOBLE_TOQUE", "ANULADO_POR_ESCAPE", "ANULADO_POR_PROPORCIONALIDAD"]:
            idx_muerte = res.get("idx_muerte", p1_idx + 1)
            # Buscamos el siguiente fractal DESDE la muerte del patrón (>=): el extremo que
            # dejó el patrón roto es justamente el candidato a P1 del siguiente engaño.
            siguientes_fractales = [f for f in fractals_en_zona if f >= idx_muerte]
            if siguientes_fractales:
                idx_inicio_busqueda = siguientes_fractales[0]
                numero_engano += 1
                continue
            else:
                break # No hay más picos después de la rotura
                
        # Si el patrón está ACTIVO, FORMÁNDOSE, o es una CARENCIA VIVA, nos quedamos aquí
        return res
        
    if numero_engano > 3:
         return {"estado": "ZONA_AGOTADA", "mensaje": "Se rompieron 3 engaños. La zona ya no es válida para un 4to engaño (Descartada)."}
         
    return ultimo_resultado

if __name__ == "__main__":
    print("Descargando velas M3 de BNBUSDT para prueba (Últimas 10 horas)...")
    df_m3 = get_binance_klines("BNBUSDT", "3m").tail(200).reset_index(drop=True)
    df_m3['open_time'] = df_m3['open_time'].dt.tz_localize('UTC').dt.tz_convert('America/Bogota')
    
    zona_max = 573.74
    zona_min = 565.14
    
    print("--- FRACTALES DETECTADOS (ÚLTIMAS VELAS) ---")
    peaks, troughs = find_micro_fractals(df_m3)
    print("Picos (Candidatos a P1):")
    for p in peaks[-5:]:
        print(f"  [{p}] {df_m3.loc[p, 'open_time']} -> {df_m3.loc[p, 'high']:.2f}")
    print("\nValles (Candidatos a P2):")
    for t in troughs[-5:]:
        print(f"  [{t}] {df_m3.loc[t, 'open_time']} -> {df_m3.loc[t, 'low']:.2f}")
    print("------------------------------------------\n")
    
    print(f"Buscando Patrones en Zona REAL DE VENTAS (Nivel 5 Media): {zona_max:.2f} a {zona_min:.2f}...\n")
    resultado = detect_patron_institucional(df_m3, zona_max, zona_min, "SELL")
    
    print("RESULTADO DEL ESCÁNER:")
    print(f"Estado: {resultado['estado']}")
    print(f"Mensaje: {resultado['mensaje']}")
    
    if 'detalles' in resultado:
        d = resultado['detalles']
        print(f"\n--- DETALLES DEL {d.get('nivel_engano', 'PATRÓN')} ---")
        print(f" PAUTA 1 (Llegada/Stop Anterior): Pico en {d.get('pauta1_price', 0):.2f} (Vela de las {d.get('pauta1_time', '')})")
        print(f" PAUTA 2 (Rechazo Actual): Valle en {d.get('pauta2_price', 0):.2f} (Vela de las {d.get('pauta2_time', '')})")
        print(f" Impulso (P1 - P2): {d.get('impulso', 0):.2f} USDT")
        print(f" Zona de Engaños (138.2% a 161.8%): {d.get('fibo_1382', 0):.2f} a {d.get('fibo_1618', 0):.2f}")
        print(f" Mitad de la zona operativa: {d.get('mitad_zona', 0):.2f} | Proporcional: {'SÍ' if d.get('proporcional') else 'NO'}")
        print(f" Calidad: {d.get('calidad', 'N/A')}")
        print(f" Volumen Recomendado: {d.get('sugerencia_volumen', 'N/A')}")
        
    if "GATILLO" in resultado['estado']:
        d = resultado['detalles']
        print("\n--- ZONAS DE OPERACIÓN ---")
        print(f" 🔥 GATILLO AGRESIVO (Market): {d['gatillo_agresivo']:.2f}")
        if 'hora_gatillo' in d: print(f" ⏱️ HORA DEL GATILLO: {d['hora_gatillo']}")
        print(f" 🛑 STOP LOSS ESTRUCTURAL: {d['stop_loss']:.2f}")
        print(f" 🧘 ENTRADA CALMADA (Límite): {d['espera_calmada']:.2f}")
        print(f" 🛡️ NIVEL DE PROTECCIÓN (50% OUT): {d['fibo_seguimiento_618']:.2f}")
