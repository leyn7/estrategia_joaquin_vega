import pandas as pd

def extraer_puntos_control(df, start_idx, end_idx, direction="BULLISH"):
    """Extracción CRONOLÓGICA de puntos de control (Sección 2 de la biblia).

    Camina las velas una sola vez y aplica las reglas en el orden en que ocurren:
      - Fractal: un extremo de impulso solo existe con confirmación 2+2 velas cerradas
        (estricto). El punto de control (trough) se confirma con 2 velas cerradas a su
        derecha (la izquierda la garantiza ser el mínimo más profundo desde el pico).
      - Retroceso vivo (pendiente): del extremo al mínimo más profundo posterior. Si el
        precio profundiza, la altura crece y el requisito del 1/3 se recalcula.
      - Validación 1/3: el punto de control nace en el INSTANTE en que el precio rompe
        el extremo por >= 1/3 de la altura del retroceso (la rotura pudo darse en las
        velas de confirmación: se mide con el máximo alcanzado desde el trough).
      - Desgrane (evolución, regla del usuario 3 jul 2026): al validarse un punto de
        control, mueren los puntos de control menores cuyo trough está ANTES en el
        gráfico (posición). Los menores posteriores conviven como muñecas rusas.
        Ej.: el 556.22->550.34 (5.88, trough 1 jul 15:15) muere al validarse el
        560.01->546.52 (13.49, trough 1 jul 19:30); el 549.05 (10.65, trough 2 jul
        02:00, posterior) convive con el 546.52.
      - Fusión de retrocesos: dos pendientes con el mismo mínimo son el mismo retroceso
        medido desde extremos distintos; manda el extremo mayor (el impulso real). Esto
        evita "validar" un retroceso profundo desde un rebote intermedio menor.
      - RESET 61.8%: retroceso >= 61.8% del impulso medido desde el ORIGEN del tramo
        (no desde el cursor): engulle los niveles por encima y frena el desgrane.

    Un retroceso que nunca rompe su 1/3 es RUIDO: queda en 'pendientes' y jamás ancla
    ciclos. La dirección BEARISH se procesa reflejando precios (espacio alcista).

    Devuelve {'vivos', 'muertos', 'pendientes', 'resets', 'eventos'} en precio real.
    """
    m = 1.0 if direction == "BULLISH" else -1.0
    col_imp = 'high' if direction == "BULLISH" else 'low'   # extremos del impulso
    col_ret = 'low' if direction == "BULLISH" else 'high'   # extremos del retroceso
    imp = (m * df[col_imp]).to_numpy()
    ret = (m * df[col_ret]).to_numpy()
    start_idx, end_idx = int(start_idx), int(end_idx)
    o_ret = ret[start_idx]

    def real(v):
        return m * v

    pendings, validados, resets, eventos = [], [], [], []

    for i in range(start_idx + 1, end_idx + 1):
        hi = imp[i]
        lo = ret[i]

        # 1) Nace un extremo de impulso: el fractal de i-2 se confirma al cierre de i (2+2)
        pk = i - 2
        if pk > start_idx and pk >= 2 and imp[pk] > imp[pk - 1] and imp[pk] > imp[pk - 2] \
                and imp[pk] > imp[pk + 1] and imp[pk] > imp[pk + 2]:
            tramo = ret[pk + 1:i + 1]
            off = int(tramo.argmin())
            t_idx = pk + 1 + off
            pendings.append({'peak': imp[pk], 'peak_idx': pk,
                             'trough': float(tramo[off]), 'trough_idx': t_idx,
                             'rotura_max': float(imp[t_idx + 1:i + 1].max()) if t_idx < i else float('-inf'),
                             'es_reset': False})

        # 2) Dilatación: el retroceso crece y el 1/3 se recalcula. La rotura se rastrea
        # incrementalmente desde el mínimo vigente (se reinicia si el retroceso profundiza)
        for p in pendings:
            if lo < p['trough']:
                p['trough'] = lo
                p['trough_idx'] = i
                p['rotura_max'] = float('-inf')
            elif p['trough_idx'] < i and hi > p['rotura_max']:
                p['rotura_max'] = hi

        # 3) Fusión: mismo mínimo = mismo retroceso; manda el extremo mayor
        por_trough = {}
        for p in pendings:
            q = por_trough.get(p['trough_idx'])
            if q is None or p['peak'] > q['peak']:
                por_trough[p['trough_idx']] = p
        pendings = sorted(por_trough.values(), key=lambda p: p['peak_idx'])

        # 4) RESET 61.8% medido desde el origen del tramo
        for p in pendings:
            if p['es_reset']:
                continue
            altura = p['peak'] - p['trough']
            subida = p['peak'] - o_ret
            if subida > 0 and altura >= 0.618 * subida:
                p['es_reset'] = True
                resets.append({'trough': real(p['trough']), 'trough_idx': p['trough_idx'], 'idx': i})
                for cp in validados:
                    if cp['vivo'] and cp['_trough_t'] > p['trough']:
                        cp['vivo'] = False
                        cp['causa_muerte'] = 'ENGULLIDO_POR_RESET'
                        eventos.append({'tipo': 'MUERE', 'idx': i, 'trough': cp['trough'],
                                        'grado': cp['grado'], 'causa': 'ENGULLIDO_POR_RESET'})
                for cp in validados:
                    if cp['vivo']:
                        cp['pre_reset'] = True  # el desgrane futuro no cruza el reset
                eventos.append({'tipo': 'RESET', 'idx': i, 'trough': real(p['trough']),
                                'trough_idx': p['trough_idx']})

        # 5) Validación 1/3: el trough necesita 2 velas cerradas de confirmación (que por
        # construcción dejan mínimos superiores: uno menor habría dilatado el retroceso).
        # La rotura se mide con el máximo alcanzado desde el trough, porque el rompimiento
        # pudo ocurrir en la propia vela de confirmación.
        for p in list(pendings):
            if p['es_reset']:
                continue
            altura = p['peak'] - p['trough']
            if altura <= 0:
                continue
            t = p['trough_idx']
            if t + 2 > i:
                continue  # trough aún sin las 2 velas de confirmación: se reintenta
            if p['rotura_max'] >= p['peak'] + altura / 3.0:
                cp = {'trough': real(p['trough']), '_trough_t': p['trough'], 'trough_idx': t,
                      'peak': real(p['peak']), 'peak_idx': p['peak_idx'],
                      'grado': altura, 'valid_idx': i, 'vivo': True, 'pre_reset': False}
                # dedupe: mismo trough ya validado -> conserva el de mayor grado
                repetido = next((v for v in validados if v['vivo'] and v['trough_idx'] == t), None)
                if repetido is not None:
                    if repetido['grado'] >= cp['grado']:
                        pendings.remove(p)
                        continue
                    repetido['vivo'] = False
                    repetido['causa_muerte'] = 'REEMPLAZADO'
                # DESGRANE (evolución): mata a los menores con trough anterior en el gráfico
                for old in validados:
                    if old['vivo'] and not old['pre_reset'] \
                            and old['trough_idx'] < t and old['grado'] < cp['grado']:
                        old['vivo'] = False
                        old['causa_muerte'] = 'DESGRANE'
                        eventos.append({'tipo': 'MUERE', 'idx': i, 'trough': old['trough'],
                                        'grado': old['grado'], 'causa': 'DESGRANE',
                                        'asesino': cp['trough'], 'grado_asesino': cp['grado']})
                validados.append(cp)
                eventos.append({'tipo': 'VALIDA', 'idx': i, 'trough': cp['trough'],
                                'peak': cp['peak'], 'grado': cp['grado'],
                                'trough_idx': t, 'nivel_roto': real(p['peak'] + altura / 3.0)})
                pendings.remove(p)

    pendientes = []
    for p in pendings:
        altura = p['peak'] - p['trough']
        pendientes.append({'peak': real(p['peak']), 'peak_idx': p['peak_idx'],
                           'trough': real(p['trough']), 'trough_idx': p['trough_idx'],
                           'altura': altura, 'nivel_validacion': real(p['peak'] + altura / 3.0),
                           'es_reset': p['es_reset']})
    return {'vivos': [c for c in validados if c['vivo']],
            'muertos': [c for c in validados if not c['vivo']],
            'pendientes': pendientes, 'resets': resets, 'eventos': eventos}


def get_bullish_poc(df, start_idx, end_idx):
    start_idx = int(start_idx)
    current_end = int(end_idx)
    origin_low = df.loc[start_idx, 'low']
    
    while current_end > start_idx:
        swings = []
        df_segment = df.loc[start_idx:current_end]
        
        max_seen = df_segment.loc[start_idx, 'high']
        peak_idx = start_idx
        
        min_low_since_max = float('inf')
        min_low_idx = -1
        
        for j in range(start_idx + 1, current_end):
            curr_high = df_segment.loc[j, 'high']
            if curr_high > max_seen:
                max_seen = curr_high
                peak_idx = j
                
                min_low_since_max = float('inf')
                min_low_idx = -1
            else:
                curr_low = df_segment.loc[j, 'low']
                if curr_low < min_low_since_max:
                    min_low_since_max = curr_low
                    min_low_idx = j
                    
                drop = max_seen - min_low_since_max
                if drop > 0:
                    swings.append({
                        'peak': max_seen,
                        'trough': min_low_since_max,
                        'drop': drop,
                        'peak_idx': peak_idx,
                        'trough_idx': min_low_idx
                    })
                
        if not swings: return None
        
        swings_df = pd.DataFrame(swings).sort_values(by='drop', ascending=False)
        biggest = swings_df.iloc[0]
        
        abs_max_val = df.loc[current_end, 'high']
        req_break = biggest['drop'] / 3.0
        actual_break = abs_max_val - biggest['peak']
        
        if actual_break >= req_break:
            res = biggest.to_dict()
            res['type'] = 'POC'
            return res
        else:
            total_rise = biggest['peak'] - origin_low
            if total_rise > 0 and biggest['drop'] >= total_rise * 0.618:
                return {
                    'type': 'RESET',
                    'trough': biggest['trough'],
                    'trough_idx': biggest['trough_idx']
                }
            
            current_end = int(biggest['peak_idx'])
            if current_end <= start_idx: break
            
    return None

def get_bearish_poc(df, start_idx, end_idx):
    start_idx = int(start_idx)
    current_end = int(end_idx)
    origin_high = df.loc[start_idx, 'high']
    
    while current_end > start_idx:
        swings = []
        df_segment = df.loc[start_idx:current_end]
        
        min_seen = df_segment.loc[start_idx, 'low']
        trough_idx = start_idx
        
        max_high_since_min = -float('inf')
        max_high_idx = -1
        
        for j in range(start_idx + 1, current_end):
            curr_low = df_segment.loc[j, 'low']
            if curr_low < min_seen:
                min_seen = curr_low
                trough_idx = j
                
                max_high_since_min = -float('inf')
                max_high_idx = -1
            else:
                curr_high = df_segment.loc[j, 'high']
                if curr_high > max_high_since_min:
                    max_high_since_min = curr_high
                    max_high_idx = j
                    
                bounce = max_high_since_min - min_seen
                if bounce > 0:
                    swings.append({
                        'peak': max_high_since_min,
                        'trough': min_seen,
                        'bounce': bounce,
                        'peak_idx': max_high_idx,
                        'trough_idx': trough_idx
                    })
                
        if not swings: return None
        
        swings_df = pd.DataFrame(swings).sort_values(by='bounce', ascending=False)
        biggest = swings_df.iloc[0]
        
        abs_min_val = df.loc[current_end, 'low']
        req_break = biggest['bounce'] / 3.0
        actual_break = biggest['trough'] - abs_min_val
        
        if actual_break >= req_break:
            res = biggest.to_dict()
            res['type'] = 'POC'
            return res
        else:
            total_drop = origin_high - biggest['trough']
            if total_drop > 0 and biggest['bounce'] >= total_drop * 0.618:
                return {
                    'type': 'RESET',
                    'peak': biggest['peak'],
                    'peak_idx': biggest['peak_idx']
                }
                
            current_end = int(biggest['trough_idx'])
            if current_end <= start_idx: break
            
    return None
