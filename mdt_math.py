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

def get_active_zones(zone_data, direction, df, post_fin_idx):
    if post_fin_idx >= len(df): 
        return {"ALTA": False, "MEDIA": False, "BAJA": False, "CYCLE_DEAD": False}
        
    df_post = df.loc[post_fin_idx:]
    status = {"ALTA": False, "MEDIA": False, "BAJA": False, "CYCLE_DEAD": False}
    
    if direction == "BULLISH":
        min_post = df_post['low'].min()
        if min_post <= zone_data['activacion']: # Tocó el 38.2%
            status["ALTA"] = True
            status["MEDIA"] = True
            status["BAJA"] = True
            
            # Muerte por tocar Parte Baja (100% / Origen)
            if min_post <= zone_data['origen']:
                status["MEDIA"] = False
                status["ALTA"] = False
                
            # Muerte del Ciclo Completo (Tocó el -38.2% / Extensión Extrema)
            extrema_muerte = zone_data['origen'] - (zone_data['impulse'] * 0.382)
            if min_post <= extrema_muerte:
                status["CYCLE_DEAD"] = True
                status["ALTA"] = False
                status["MEDIA"] = False
                status["BAJA"] = False
                
    else: # BEARISH
        max_post = df_post['high'].max()
        if max_post >= zone_data['activacion']: # Tocó el 38.2%
            status["ALTA"] = True
            status["MEDIA"] = True
            status["BAJA"] = True
            
            # Muerte por tocar Parte Alta (100% / Origen)
            if max_post >= zone_data['origen']:
                status["MEDIA"] = False
                status["BAJA"] = False
                
            # Muerte del Ciclo Completo (Tocó el 138.2% / Extensión Extrema)
            extrema_muerte = zone_data['origen'] + (zone_data['impulse'] * 0.382)
            if max_post >= extrema_muerte:
                status["CYCLE_DEAD"] = True
                status["ALTA"] = False
                status["MEDIA"] = False
                status["BAJA"] = False
                
    return status

def apply_concurrency(z_mayor, z_menor, buy_or_sell):
    if buy_or_sell == "BUY": # Ataca desde arriba
        imay, fmay = max(z_mayor), min(z_mayor)
        imen, fmen = max(z_menor), min(z_menor)
        
        if imen <= imay and fmen >= fmay: return None, "Caso 1 (Inmersión Total)"
        if imay >= imen: return None, "Caso 3 (Sándwich)"
        # Aquí siempre imen > imay (complemento del Caso 3)
        if fmen >= imay: return z_menor, "Sin Concurrencia"
        free = imen - imay
        if free >= (imen - fmen)/2.0: return (imen, imay), f"Caso 2 (ACOTADA a {free:.2f})"
        return None, "Caso 2 (ELIMINADA por falta de espacio)"
            
    else: # SELL: Ataca desde abajo
        imay, fmay = min(z_mayor), max(z_mayor)
        imen, fmen = min(z_menor), max(z_menor)
        
        if imen >= imay and fmen <= fmay: return None, "Caso 1 (Inmersión Total)"
        if imay <= imen: return None, "Caso 3 (Sándwich)"
        # Aquí siempre imen < imay (complemento del Caso 3)
        if fmen <= imay: return z_menor, "Sin Concurrencia"
        free = imay - imen
        if free >= (fmen - imen)/2.0: return (imen, imay), f"Caso 2 (ACOTADA a {free:.2f})"
        return None, "Caso 2 (ELIMINADA por falta de espacio)"

def format_z(z):
    if z is None: return "ELIMINADA"
    return f"{max(z):.2f} a {min(z):.2f}"
