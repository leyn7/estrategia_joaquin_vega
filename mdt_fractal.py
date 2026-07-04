def find_micro_fractals(df):
    """Fractales 2+2 estrictos (Sección 2): extremo con 2 velas cerradas a cada lado.
    Devuelve (picos, valles) como índices — candidatos a P1 del escáner de patrones."""
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
