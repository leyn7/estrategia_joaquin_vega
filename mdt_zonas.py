# -*- coding: utf-8 -*-
"""ZONAS DE TRABAJO y CONCURRENCIA (Secciones 4, 8, 19 de la biblia).

De un ciclo vivo nacen sus zonas operativas (Alta / Media / Baja), cada una con
su anulación y su TP. Cuando dos zonas de la misma dirección se pisan, manda la
Zona Mayor (concurrencia, Secc 19): la menor se elimina, se acota, o convive.

Reglas del operador integradas aquí:
  - El TP de las zonas del LADO DEL FIN (la Alta de un alcista, la Baja de un
    bajista) es la MEDIA de la medida que se forma — no la zona contraria lejana
    (12 jul: "al ir la operación se activa un ciclo nuevo tocando el 38.2, y de
    ahí la zona contraria sería la zona media").
  - El último ciclo del mapa se audita sin privilegios contra los anteriores
    (7 jul): si sus zonas tejen contra la estructura madre, el ancla no sirve.
"""
from mdt_config import NIVEL_382, ZONA_MAX_OPERABLE_PCT
from mdt_math import apply_concurrency, calc_zones


def registrar_ciclo(c, direction, buys, sells, alerts, verbose=True):
    """Publica las zonas operativas de un ciclo (o su alerta si aún no activó).

    Reparto: BULLISH -> Compras: Baja y Media | Ventas: Alta
             BEARISH -> Compras: Baja | Ventas: Alta y Media
    """
    ev = c['eval']
    nombre = c['nombre']
    etiqueta = f"[{nombre.upper()} ({c['tf'].upper()})] ancla {c['ancla']:.2f}"

    if not c.get('operable', True) and ev['estado'] != 'MUERTO':
        if verbose:
            print(f"{etiqueta} -> SUB-OPERABLE (grado {c['grado']:.2f} < 1% del precio): "
                  f"vive en el motor, sin zonas operativas")
        return
    if ev['estado'] == 'MUERTO':
        if verbose:
            causa = "RESET 61.8 del tramo" if ev.get('reset_tramo_618') else "tocó su 138.2"
            print(f"{etiqueta} -> MUERTO: {causa} ({ev['nivel_muerte']:.2f}) "
                  f"el {ev['hora_muerte']}")
        return
    if ev['estado'] == 'SIN_IMPULSO':
        if verbose:
            print(f"{etiqueta} -> sin impulso medible todavía")
        return

    z = ev['zonas']
    detalle = f"fin {ev['fin_vigente']:.2f}"
    if ev['evolucionado']:
        detalle += f" | EVOLUCIONADO: re-anclado en {ev['origen_vigente']:.2f} (ciclo mayor)"

    if ev['en_excursion']:
        _registrar_excursion(c, ev, z, direction, buys, sells, etiqueta, detalle, verbose)
        return
    if not ev['activado']:
        tipo = "COMPRAS" if direction == "BULLISH" else "VENTAS"
        alerts.append({'name': nombre, 'activacion': ev['nivel_activacion'],
                       'zona_alerta': z['MEDIA'], 'tipo': tipo})
        if verbose:
            print(f"{etiqueta} -> {detalle} | EN ALERTA: se activa al tocar su 38.2 "
                  f"({ev['nivel_activacion']:.2f})")
        return

    _registrar_activado(c, ev, z, direction, buys, sells, alerts, etiqueta, detalle, verbose)


def _registrar_excursion(c, ev, z, direction, buys, sells, etiqueta, detalle, verbose):
    """El precio se fue más allá del origen (Secc 4/8). El primer 19.1% ES la
    zona del origen (Parte Alta en bajista / Parte Baja en alcista): zona
    OPERATIVA en trabajo que borra las internas. Más allá, hasta el 38.2, es
    Zona de Indecisión: inoperable."""
    if not ev.get('zona_origen_en_trabajo'):
        if verbose:
            print(f"{etiqueta} -> {detalle} | EN ZONA DE INDECISIÓN (superó el 19.1% "
                  f"del origen): inoperable | muerte del ciclo en {ev['nivel_muerte']:.2f} "
                  f"| evolución a ciclo mayor si toca {ev['evolucion_38_2']:.2f}")
        return

    # La zona es operativa desde que abrió la excursión (el escáner solo mira ese
    # episodio). Su anulación es la muerte del ciclo. Y su TP (Secc 8) es la Zona
    # del 61.8 del nuevo Fibo Mayor (extremo de la excursión -> fin).
    tp_zona = calc_zones(ev['extremo_excursion'], ev['fin_vigente'], direction)['MEDIA']
    extra = {"tf": c['tf'], "ancla": c['ancla'],
             "ciclo_origen": ev['origen_vigente'], "ciclo_fin": ev['fin_vigente'],
             "operativa_desde": ev.get('hora_excursion'),
             "nivel_anulacion": ev['nivel_muerte'],
             "tp_zona": tp_zona}
    if direction == "BULLISH":
        caja, lado = z['BAJA'], "PARTE BAJA (Compras)"
        buys.append({"name": f"{c['nombre']} (Baja)", "z": caja, "peso": c['peso'], **extra})
    else:
        caja, lado = z['ALTA'], "PARTE ALTA (Ventas)"
        sells.append({"name": f"{c['nombre']} (Alta)", "z": caja, "peso": c['peso'], **extra})
    if verbose:
        print(f"{etiqueta} -> {detalle} | TRABAJANDO {lado}: {min(caja):.2f} a {max(caja):.2f} "
              f"| muerte del ciclo en {ev['nivel_muerte']:.2f} "
              f"| evolución a ciclo mayor si toca {ev['evolucion_38_2']:.2f}")


def _registrar_activado(c, ev, z, direction, buys, sells, alerts, etiqueta, detalle, verbose):
    """Ciclo activado (tocó su 38.2): sus 3 zonas quedan operativas."""
    nombre = c['nombre']
    if verbose:
        media_txt = " | media MUERTA (tocó el 100%)" if ev['media_muerta'] else ""
        cand_txt = (f" | medida candidata hasta {ev['fin_candidato']:.2f} "
                    f"(nace en {ev['activacion_candidata']:.2f})"
                    if ev.get('fin_candidato') is not None else "")
        print(f"{etiqueta} -> {detalle} | ACTIVADO ({ev['hora_activacion']}){media_txt}{cand_txt}")

    if ev.get('fin_candidato') is not None:
        # Extremo nuevo tras la activación (Secc 4/6): la medida vigente sigue
        # mandando (el precio arriba del fin es el TRABAJO de su Alta); la medida
        # candidata solo nace si el precio toca SU 38.2 — va como alerta.
        tipo_cand = "COMPRAS" if direction == "BULLISH" else "VENTAS"
        z_cand = calc_zones(ev['origen_vigente'], ev['fin_candidato'], direction)
        alerts.append({'name': f"{nombre} (nueva medida {ev['fin_candidato']:.2f})",
                       'activacion': ev['activacion_candidata'],
                       'zona_alerta': z_cand['MEDIA'], 'tipo': tipo_cand})

    # Las zonas existen desde la ACTIVACIÓN (Secc 3): el escáner solo mira velas
    # desde entonces — la estructura anterior es historia de otro contexto.
    extra = {"tf": c['tf'], "ancla": c['ancla'],
             "ciclo_origen": ev['origen_vigente'], "ciclo_fin": ev['fin_vigente'],
             "operativa_desde": ev.get('hora_activacion')}
    peso = c['peso']
    origen, fin, imp = z['origen'], z['fin'], z['impulse']

    # TP del LADO DEL FIN (el contra-movimiento): la MEDIA de la medida que se
    # forma —vigente o candidata—, dinámica. La zona contraria lejana es el
    # "máximo potencial" del mapa, no el TP operativo (regla usuario 12 jul).
    fin_tp = ev.get('fin_candidato') if ev.get('fin_candidato') is not None else ev['fin_vigente']
    media_medida_nueva = calc_zones(ev['origen_vigente'], fin_tp, direction)['MEDIA']

    if direction == "BULLISH":
        anul = {"BAJA": origen - imp * NIVEL_382, "MEDIA": origen, "ALTA": fin + imp * NIVEL_382}
        buys.append({"name": f"{nombre} (Baja)", "z": z['BAJA'], "peso": peso,
                     "nivel_anulacion": anul["BAJA"], "tp_zona": z['ALTA'], **extra})
        if not ev['media_muerta']:
            buys.append({"name": f"{nombre} (Media)", "z": z['MEDIA'], "peso": peso,
                         "nivel_anulacion": anul["MEDIA"], "tp_zona": z['ALTA'], **extra})
        sells.append({"name": f"{nombre} (Alta)", "z": z['ALTA'], "peso": peso,
                      "nivel_anulacion": anul["ALTA"], "tp_zona": media_medida_nueva, **extra})
    else:
        anul = {"ALTA": origen + imp * NIVEL_382, "MEDIA": origen, "BAJA": fin - imp * NIVEL_382}
        buys.append({"name": f"{nombre} (Baja)", "z": z['BAJA'], "peso": peso,
                     "nivel_anulacion": anul["BAJA"], "tp_zona": media_medida_nueva, **extra})
        sells.append({"name": f"{nombre} (Alta)", "z": z['ALTA'], "peso": peso,
                      "nivel_anulacion": anul["ALTA"], "tp_zona": z['BAJA'], **extra})
        if not ev['media_muerta']:
            sells.append({"name": f"{nombre} (Media)", "z": z['MEDIA'], "peso": peso,
                          "nivel_anulacion": anul["MEDIA"], "tp_zona": z['BAJA'], **extra})


def resolver_concurrencia(zonas, buy_or_sell, current_price=None, verbose=True):
    """Concurrencia de zonas (Secc 19): la Zona Mayor siempre manda.

    Excepción de la Zona en Trabajo (Secc 3, Caso 2): la zona mayor que CONTIENE
    ahora mismo al precio es el campo de trabajo — no tritura a los sub-ciclos que
    nacen dentro de ella, porque esos sub-ciclos SON la vía operativa de su trabajo.
    """
    if buy_or_sell == "BUY":
        zonas = sorted(zonas, key=lambda x: max(x['z']), reverse=True)
    else:
        zonas = sorted(zonas, key=lambda x: min(x['z']))

    finales = []
    for i in range(len(zonas)):
        current = zonas[i]
        if current['z'] is None:
            continue
        for j in range(len(zonas)):
            if i == j:
                continue
            otro = zonas[j]
            if otro['z'] is None:
                continue
            if current_price is not None and min(otro['z']) <= current_price <= max(otro['z']):
                continue  # la mayor está en trabajo: no tritura sub-ciclos
            if otro['peso'] > current['peso']:
                new_z, razon = apply_concurrency(otro['z'], current['z'], buy_or_sell)
                if verbose and new_z != current['z']:
                    print(f"[{current['name']} vs {otro['name']}] -> {razon}")
                current['z'] = new_z
                if current['z'] is None:
                    break
        if current['z'] is not None:
            finales.append(current)
    return finales


def auditar_ultimo_ciclo(ciclos, buys, sells, precio, verbose=True):
    """Auditoría del último ciclo del mapa (regla usuario 7 jul 2026).

    El ancla más reciente es siempre el ciclo más pequeño: sus zonas se auditan
    contra las de los ciclos anteriores SIN privilegios (aquí no aplica la
    excepción de zona-en-trabajo). Si sus zonas tejen contra la estructura madre,
    el ancla no aporta nada y se queda sin zonas.

    Calibrado con datos reales (7 jul): el TOQUE exacto en el borde solo mata a
    las MUÑECAS ANIDADAS —sus zonas tejen contra la madre por construcción—. Un
    CP normal que apenas toca convive (la Parte Alta del 572.71 tocaba la Media
    del 602.79 y fue una venta ganadora): para él solo cuenta el solape real.
    """
    t_por_ciclo = {}
    for c in ciclos:
        if c.get('ancla') is not None and c.get('ancla_time') is not None:
            k = (round(c['ancla'], 2), c.get('tf'))
            if k not in t_por_ciclo or c['ancla_time'] > t_por_ciclo[k][0]:
                t_por_ciclo[k] = (c['ancla_time'], bool(c.get('muneca')))

    def info_de(z):
        if z.get('ancla') is None:
            return None
        return t_por_ciclo.get((round(z['ancla'], 2), z.get('tf')))

    def t_de(z):
        i = info_de(z)
        return i[0] if i else None

    tiempos = [t for t in (t_de(z) for z in buys + sells) if t is not None]
    if not tiempos:
        return buys, sells
    t_ultimo = max(tiempos)

    quedan_del_ultimo = 0
    ancla_ultimo = None
    resultado = []
    for lista in (sells, buys):
        finales = []
        for z in lista:
            if t_de(z) != t_ultimo:
                finales.append(z)
                continue
            ancla_ultimo = z['ancla']
            zmax, zmin = max(z['z']), min(z['z'])
            es_muneca = (info_de(z) or (None, False))[1]
            # Muñeca anidada: el toque en el borde cuenta (<=). CP normal: solo el
            # solape real (<) — el toque exacto convive (espíritu del Caso 2).
            if es_muneca:
                def toca(o):
                    return min(o['z']) <= zmax and zmin <= max(o['z'])
            else:
                def toca(o):
                    return min(o['z']) < zmax and zmin < max(o['z'])
            # Choca solo contra zonas OPERATIVAS anteriores: las macro de contexto
            # cubren medio gráfico y no son "la concurrencia del ciclo anterior".
            choque = next((o for o in lista
                           if o is not z and t_de(o) is not None and t_de(o) < t_ultimo
                           and (max(o['z']) - min(o['z'])) <= precio * ZONA_MAX_OPERABLE_PCT
                           and toca(o)), None)
            if choque is not None:
                if verbose:
                    print(f"[AUDITORÍA ÚLTIMO CICLO] {z['name']} {zmax:.2f}-{zmin:.2f} "
                          f"ELIMINADA: toca/solapa {choque['name']} "
                          f"{max(choque['z']):.2f}-{min(choque['z']):.2f} (la mayor manda)")
                continue
            quedan_del_ultimo += 1
            finales.append(z)
        resultado.append(finales)

    if verbose and ancla_ultimo is not None and quedan_del_ultimo == 0:
        print(f"[AUDITORÍA ÚLTIMO CICLO] el ancla {ancla_ultimo:.2f} queda SIN zonas: no sirve")
    return resultado[1], resultado[0]   # (buys, sells)


def zonas_de_tramo(res, direction, precio, peso_base=100):
    """Zonas de UN tramo con su concurrencia INTERNA (Secc 19 solo entre SUS
    ciclos — cada tramo es independiente). Devuelve (zonas [(lado, zona)], alertas)."""
    buys, sells, alerts = [], [], []
    for j, c in enumerate(res['ciclos']):
        c['peso'] = peso_base - j
        c['direction'] = direction
        registrar_ciclo(c, direction, buys, sells, alerts, verbose=False)
    zonas = []
    for lado, lista in (("SELL", sells), ("BUY", buys)):
        for z in resolver_concurrencia([{**x} for x in lista], lado, precio, verbose=False):
            zonas.append((lado, z))
    return zonas, alerts


def zonas_finales_tramo(t, precio):
    """Zonas finales de un tramo ya construido (vista de mapa['tramos']) tras su
    concurrencia interna. Se trabaja sobre COPIAS: la resolución muta las zonas y
    la vista del tramo no debe tocarse."""
    out = []
    for lado, key in (("SELL", 'sells'), ("BUY", 'buys')):
        copias = [{**z} for z in t.get(key, [])]
        for z in resolver_concurrencia(copias, lado, precio, verbose=False):
            out.append((lado, z))
    return out
