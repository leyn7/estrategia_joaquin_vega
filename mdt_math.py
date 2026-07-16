# -*- coding: utf-8 -*-
"""Matemática pura de la estrategia: zonas, seguimiento de ciclo, concurrencia.

Los números de la biblia viven en mdt_config con nombre (auditoría 16 jul: antes
este módulo usaba los literales 0.191/0.382/0.618 y la config definía constantes
que nadie importaba — dos fuentes para el mismo número).
"""
from mdt_config import ZONA_191, NIVEL_382, NIVEL_618


def calc_zones(origen, fin, direction="BULLISH"):
    impulse = abs(origen - fin)
    zone_size = impulse * ZONA_191
    if direction == "BULLISH":
        z_alta = (fin, fin + zone_size)
        z_media = (fin - (impulse*NIVEL_618), fin - (impulse*NIVEL_618) - zone_size)
        z_baja = (origen, origen - zone_size)
        act = fin - (impulse*NIVEL_382)
    else:
        z_alta = (origen, origen + zone_size)
        z_media = (fin + (impulse*NIVEL_618), fin + (impulse*NIVEL_618) + zone_size)
        z_baja = (fin, fin - zone_size)
        act = fin + (impulse*NIVEL_382)
    return {'origen': origen, 'fin': fin, 'impulse': impulse, 'ALTA': z_alta, 'MEDIA': z_media, 'BAJA': z_baja, 'activacion': act}


def banda_de(nombre):
    """La banda (Alta/Media/Baja) del nombre de una zona: "Sub-C X Nivel 2 (Media)"
    -> "Media". Estaba escrito 3 veces (formato, reportes, eventos)."""
    return nombre.rsplit('(', 1)[-1].rstrip(')') if '(' in nombre else '?'

def evaluar_ciclo(origen, df, desde_idx=0, direction="BULLISH"):
    """Seguimiento CRONOLÓGICO de un ciclo desde su nacimiento (reglas usuario 3 jul 2026).

    El origen del fibo es FIJO (la dilatación del origen NO existe en el curso —
    zombis del 3 jul 2026). El fin sí se extiende con nuevos extremos del impulso.
      - Muerte del ciclo: el precio toca la extensión 138.2/-38.2 del fibo
        (origen ± 0.382*impulso). DEFINITIVA (caso 561.93; caso zombi 548.59:
        murió el 30 jun al tocar 552.90, no persigue al precio).
      - Excursión más allá del origen sin tocar la muerte: el primer 19.1% del
        impulso más allá del origen ES la zona del origen (Parte Alta en bajista /
        Parte Baja en alcista, Sección 4): zona OPERATIVA en trabajo, que además
        borra las zonas internas (Sección 8). Entre el 19.1% y el 38.2% está la
        Zona de Indecisión (Sección 17). Al tocar el 38.2 más allá, muere.
      - EVOLUCIÓN A CICLO MAYOR (Sección 8, video ZONA ALTA): el extremo de la
        excursión es el nuevo origen de una medida mayor (extremo -> fin). Si el
        precio se aleja del extremo el 38.2% de esa nueva medida, el ciclo viejo
        muere y el mayor toma su lugar: re-ancla en el extremo, zonas nuevas,
        ACTIVADO ("el ciclo azul se muere y pasamos a tener un ciclo mayor").
      - Activación: tocar el 38.2 del fibo vigente. ANTES de la activación, un
        nuevo extremo re-dibuja el fibo y desliza el 38.2 objetivo.
      - TRABAJO DE LA ZONA ALTA (Secc 4/6, regla usuario 11 jul): DESPUÉS de la
        activación la medida del episodio queda FIJA (fin_act). El precio por
        encima del fin ES el trabajo de la Zona Alta (Baja en bajista) — la
        manipulación que esa zona existe para capturar (caso real: la mechita
        578.81 del 10 jul desactivaba el ciclo y la Alta era intrabajable). Un
        extremo nuevo abre una MEDIDA CANDIDATA (fin corrido) que solo nace al
        tocar SU 38.2 ("si llegaba al 38.2 se activaba el ciclo con sus nuevas
        zonas"); la medida vigente solo muere si el precio toca la anulación de
        su Alta (fin_act + 38.2% del impulso — el mismo nivel del mapa).
      - Zona media: muere si el precio toca el 100% (origen); la evolución la
        restaura fresca.

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
    fin_act = None   # medida FIJA del episodio activado (None = sin activar)
    exc_min = None
    hora_exc = None
    activado = False
    hora_act = None
    evolucionado = False
    media_muerta = False

    for i in range(int(desde_idx) + 1, len(df)):
        hi = imp[i]
        lo = ret[i]

        if fin_v > origen_v:
            impulso = fin_v - origen_v
            # MUERTE del fibo VIGENTE (Secc 4+6, auditoría 12 jul): el 138.2 que
            # mata el ciclo es el mismo nivel del fibo de las cajas — la medida
            # activada. La candidata (fin corrido sin nacer) NO aleja la muerte;
            # re-mide todo solo cuando nace tocando su 38.2. Sin activar, el
            # fibo corrido manda (aún no hay medida fijada).
            imp_vigente = (fin_act - origen_v) if (activado and fin_act is not None) else impulso
            muerte = origen_v - imp_vigente * NIVEL_382
            act = fin_v - impulso * NIVEL_382

            if lo <= muerte:
                return {'estado': 'MUERTO', 'hora_muerte': times[i], 'nivel_muerte': m * muerte,
                        'origen_vigente': m * origen_v, 'fin_vigente': m * fin_v,
                        'activado': False, 'zonas': None}

            if exc_min is not None:
                # Excursión abierta más allá del origen. El origen NO se mueve:
                # el ciclo muere en su 38.2 fijo (chequeo de arriba) o EVOLUCIONA.
                if lo < exc_min:
                    exc_min = lo
                # Evolución (Secc 8): el precio se alejó del extremo de la excursión
                # el 38.2% de la medida mayor (extremo -> fin): el ciclo viejo muere
                # y el mayor toma su lugar, re-anclado en el extremo y ACTIVADO.
                act_evo = exc_min + (fin_v - exc_min) * NIVEL_382
                if hi >= act_evo:
                    origen_v = exc_min
                    exc_min = None
                    hora_exc = None
                    evolucionado = True
                    activado = True
                    fin_act = fin_v
                    hora_act = times[i]
                    media_muerta = False
                continue

            if lo < origen_v:
                exc_min = lo
                hora_exc = times[i]  # apertura de la excursión: la zona del origen entra en trabajo
                media_muerta = True  # tocó el 100% al salir (la evolución la restaura)
                continue

            if not activado:
                if (lo <= act) or (evolucionado and hi >= act):
                    activado = True
                    fin_act = fin_v
                    hora_act = times[i]
            else:
                if lo <= origen_v:
                    media_muerta = True
                # Medida candidata mayor (extremo nuevo tras la activación): nace
                # al tocar SU 38.2 — "se activa el ciclo con sus nuevas zonas"
                # (regla usuario 11 jul). Hasta entonces, la medida vigente manda.
                if fin_v > fin_act and lo <= act:
                    fin_act = fin_v
                    hora_act = times[i]
                    media_muerta = False

        if hi > fin_v:
            if fin_v > origen_v:
                if not activado:
                    # Pre-activación: el fibo se re-dibuja (misma ancla, medida
                    # mayor) y el 38.2 objetivo se desliza
                    hora_act = None
                    media_muerta = False
                else:
                    # Post-activación (Secc 4/6): el precio por encima del fin es
                    # el TRABAJO DE LA ZONA ALTA de la medida vigente — no re-mide
                    # ni desactiva. El episodio solo muere si toca la anulación de
                    # la Alta (fin_act + 38.2% del impulso vigente).
                    imp_act = fin_act - origen_v
                    if hi >= fin_act + imp_act * NIVEL_382:
                        activado = False
                        fin_act = None
                        hora_act = None
                        media_muerta = False
            fin_v = hi

    if fin_v <= origen_v:
        return {'estado': 'SIN_IMPULSO', 'activado': False, 'zonas': None,
                'origen_vigente': m * origen_v, 'fin_vigente': None}

    # Zonas de la medida VIGENTE: la del episodio activado (fija) o, sin activar,
    # la del fibo corrido (cuyo 38.2 es el objetivo de activación).
    fin_zonas = fin_act if (activado and fin_act is not None) else fin_v
    zonas = calc_zones(m * origen_v, m * fin_zonas, direction)
    res = {'estado': 'VIVO', 'activado': activado, 'hora_activacion': hora_act,
           'evolucionado': evolucionado, 'en_excursion': exc_min is not None,
           'media_muerta': media_muerta, 'origen_vigente': m * origen_v,
           'fin_vigente': m * fin_zonas, 'zonas': zonas,
           'nivel_activacion': zonas['activacion']}
    if activado and fin_act is not None and fin_v > fin_act:
        # Extremo nuevo tras la activación: medida candidata pendiente de nacer
        res['fin_candidato'] = m * fin_v
        res['activacion_candidata'] = m * (fin_v - (fin_v - origen_v) * NIVEL_382)
    if exc_min is not None:
        # Clasificación de la excursión por la posición ACTUAL del precio:
        # dentro del 19.1% = trabajando la zona del origen (operativa);
        # más allá (hasta el 38.2) = Zona de Indecisión (inoperable).
        # Medida VIGENTE (Secc 4+6): la zona del origen y la muerte son del
        # fibo de las cajas, no del candidato corrido.
        impulso = fin_zonas - origen_v
        limite_zona = origen_v - impulso * ZONA_191
        close_v = m * float(df['close'].iloc[-1])
        res['zona_origen_en_trabajo'] = close_v >= limite_zona
        res['limite_zona_origen'] = m * limite_zona
        res['nivel_muerte'] = m * (origen_v - impulso * NIVEL_382)
        res['extremo_excursion'] = m * exc_min
        res['hora_excursion'] = hora_exc
        # Fibo de alerta de la evolución (Secc 8): medida mayor extremo -> fin
        res['evolucion_38_2'] = m * (exc_min + (fin_v - exc_min) * NIVEL_382)
    return res


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
