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

def evaluar_ciclo(origen, df, desde_idx=0, direction="BULLISH"):
    """Seguimiento CRONOLÓGICO de un ciclo desde su nacimiento (reglas usuario 3 jul 2026).

    El fibo vigente evoluciona vela a vela: el fin es el extremo corrido desde el ancla.
      - Muerte del ciclo: el precio toca la extensión 138.2 del fibo VIGENTE en ese
        instante (origen_v -/+ 0.382*impulso). La muerte es DEFINITIVA aunque después
        haya nuevos extremos (caso 561.93: murió el 2 jul con extremo 567.77; el nuevo
        máximo 568.33 del 3 jul no lo revive).
      - Excursión más allá del origen sin tocar la muerte: el ciclo sigue vivo. El
        primer 19.1% del impulso más allá del origen ES la zona del origen (Parte
        Alta en bajista / Parte Baja en alcista, Sección 4): zona OPERATIVA en
        trabajo, que además borra las zonas internas (Sección 8). Entre el 19.1% y
        el 38.2% está la Zona de Indecisión (inoperable, Sección 17). Al tocar el
        38.2 más allá del origen, el ciclo muere. Cuando el precio regresa por
        completo dentro del impulso, el origen se DILATA al extremo de la excursión
        y las zonas se RE-MIDEN. La activación se re-arma: exige tocar nuevamente
        el 38.2 del fibo re-medido (desde abajo).
      - Activación: tocar el 38.2 del fibo vigente. Un nuevo extremo re-dibuja el fibo
        y exige tocar el nuevo 38.2 (el ciclo vuelve a alerta).
      - Zona media: muere si el precio toca el 100% (origen vigente); una re-medición
        la restaura fresca.

    df debe empezar en (o antes de) el ancla del ciclo; desde_idx = vela del ancla.
    La dirección BEARISH se procesa reflejando precios. Devuelve dict con estado.
    """
    m = 1.0 if direction == "BULLISH" else -1.0
    col_imp = 'high' if direction == "BULLISH" else 'low'
    col_ret = 'low' if direction == "BULLISH" else 'high'
    imp = (m * df[col_imp]).to_numpy()
    ret = (m * df[col_ret]).to_numpy()
    times = df['open_time'].to_numpy()

    origen_v = m * origen
    fin_v = float('-inf')
    exc_min = None
    activado = False
    hora_act = None
    dilatado = False
    media_muerta = False

    for i in range(int(desde_idx) + 1, len(df)):
        hi = imp[i]
        lo = ret[i]

        if fin_v > origen_v:
            impulso = fin_v - origen_v
            muerte = origen_v - impulso * 0.382
            act = fin_v - impulso * 0.382

            if lo <= muerte:
                return {'estado': 'MUERTO', 'hora_muerte': times[i], 'nivel_muerte': m * muerte,
                        'origen_vigente': m * origen_v, 'fin_vigente': m * fin_v,
                        'activado': False, 'zonas': None}

            if exc_min is not None:
                # Excursión abierta más allá del origen (zona baja dilatándose)
                if lo < exc_min:
                    exc_min = lo
                if lo >= origen_v:
                    # El precio regresó por completo: re-medición con el origen dilatado
                    origen_v = exc_min
                    exc_min = None
                    dilatado = True
                    activado = False
                    hora_act = None
                    media_muerta = False
                continue

            if lo < origen_v:
                exc_min = lo
                media_muerta = True  # tocó el 100% al salir (la re-medición la restaura)
                continue

            if not activado:
                if (not dilatado and lo <= act) or (dilatado and hi >= act):
                    activado = True
                    hora_act = times[i]
            elif lo <= origen_v:
                media_muerta = True

        if hi > fin_v:
            if fin_v > origen_v:
                # Nuevo extremo: el fibo se re-dibuja y exige tocar el nuevo 38.2
                activado = False
                hora_act = None
                media_muerta = False
            fin_v = hi

    if fin_v <= origen_v:
        return {'estado': 'SIN_IMPULSO', 'activado': False, 'zonas': None,
                'origen_vigente': m * origen_v, 'fin_vigente': None}

    zonas = calc_zones(m * origen_v, m * fin_v, direction)
    res = {'estado': 'VIVO', 'activado': activado, 'hora_activacion': hora_act,
           'dilatado': dilatado, 'en_excursion': exc_min is not None,
           'media_muerta': media_muerta, 'origen_vigente': m * origen_v,
           'fin_vigente': m * fin_v, 'zonas': zonas,
           'nivel_activacion': zonas['activacion']}
    if exc_min is not None:
        # Clasificación de la excursión por la posición ACTUAL del precio:
        # dentro del 19.1% = trabajando la zona del origen (operativa);
        # más allá (hasta el 38.2) = Zona de Indecisión (inoperable).
        impulso = fin_v - origen_v
        limite_zona = origen_v - impulso * 0.191
        close_v = m * float(df['close'].iloc[-1])
        res['zona_origen_en_trabajo'] = close_v >= limite_zona
        res['limite_zona_origen'] = m * limite_zona
        res['nivel_muerte'] = m * (origen_v - impulso * 0.382)
        res['extremo_excursion'] = m * exc_min
    return res


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
        if imay >= imen:
            # Menor por detrás de la mayor: solo hay concurrencia si se superponen (o se tocan).
            # Zonas completamente separadas de la misma dirección conviven (no es sándwich).
            if imen >= fmay: return None, "Caso 3 (Sándwich)"
            return z_menor, "Sin Concurrencia (zonas separadas)"
        # Aquí siempre imen > imay (complemento del Caso 3)
        if fmen >= imay: return z_menor, "Sin Concurrencia"
        free = imen - imay
        if free >= (imen - fmen)/2.0: return (imen, imay), f"Caso 2 (ACOTADA a {free:.2f})"
        return None, "Caso 2 (ELIMINADA por falta de espacio)"
            
    else: # SELL: Ataca desde abajo
        imay, fmay = min(z_mayor), max(z_mayor)
        imen, fmen = min(z_menor), max(z_menor)
        
        if imen >= imay and fmen <= fmay: return None, "Caso 1 (Inmersión Total)"
        if imay <= imen:
            # Menor por detrás de la mayor: solo hay concurrencia si se superponen (o se tocan).
            if imen <= fmay: return None, "Caso 3 (Sándwich)"
            return z_menor, "Sin Concurrencia (zonas separadas)"
        # Aquí siempre imen < imay (complemento del Caso 3)
        if fmen <= imay: return z_menor, "Sin Concurrencia"
        free = imay - imen
        if free >= (fmen - imen)/2.0: return (imen, imay), f"Caso 2 (ACOTADA a {free:.2f})"
        return None, "Caso 2 (ELIMINADA por falta de espacio)"

def format_z(z):
    if z is None: return "ELIMINADA"
    return f"{max(z):.2f} a {min(z):.2f}"
