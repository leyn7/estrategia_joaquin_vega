# -*- coding: utf-8 -*-
"""Integración mapa -> escáner (Regla 3: el mapa es la ÚNICA fuente de zonas).

Para cada zona operativa final del mapa (tras concurrencia), busca patrones de
giro (Secciones 9-18) en la TF DEL PATRÓN: una temporalidad por debajo de la TF
del ciclo (Secc 10: "bajar una temporalidad por debajo del tamaño del ciclo que
se está trabajando"). Cada resultado lleva el ancla de su ciclo: un bucle en
vivo debe re-validar con ancla_viva(mapa_fresco, ancla) antes de armar o
disparar cualquier entrada (candado mapa->escáner).
"""
import pandas as pd
from mdt_config import SYMBOL, TF_PATRON, TF_MINUTOS, RATIO_MINIMO, ZONA_MAX_OPERABLE_PCT
from mdt_data import to_cot
from mdt_gestion import entrada_de_resultado
from mdt_macro_mapper import generar_mapa, reporte_tramos, _descargar, _ahora, ancla_viva

VELAS_ESCANEO = 1500  # ventana máxima de velas de la TF del patrón

# Estados que representan un setup accionable o vivo (para resaltar en el reporte)
ESTADOS_OPERABLES = ("GATILLO_ACTIVADO", "P3_CORTA_GATILLO", "DT_IMPULSO_GATILLO",
                     "EE_GATILLO", "EE_ARMADO", "VALIDADO_POSTERIOR",
                     "ENTRADA_PROFUNDA_ESPERANDO", "DT_IMPULSO_ESPERANDO",
                     "ENGAÑO_EN_CURSO", "ESPERANDO_1618")


def direccion_prioritaria(mapa):
    """Regla del usuario (4 jul): "el que manda es el ciclo cuya zona se está
    trabajando ACTIVAMENTE" — la zona MÁS ESPECÍFICA (la más angosta) que contiene
    al precio, no la más grande que lo envuelva.

    Refinada (10 jul): las zonas macro de CONTEXTO no mandan — si no se operan,
    tampoco dictan la prioridad (caso real: la Media del Macro Alcista 638-410
    dictaba COMPRAS y marcaba Secundaria una venta nacida de un trabajo real).
    Esta dirección global queda como contexto del mapa; la prioridad de cada
    señal la hereda de SU propia zona en trabajo (_operacion)."""
    precio = mapa['precio']
    candidatos = [("SELL", z) for z in mapa['sells']] + [("BUY", z) for z in mapa['buys']]
    contienen = [(lado, z) for lado, z in candidatos
                 if z.get('z') and min(z['z']) <= precio <= max(z['z'])
                 and (max(z['z']) - min(z['z'])) <= precio * ZONA_MAX_OPERABLE_PCT]
    if not contienen:
        return None, None
    lado, z = min(contienen, key=lambda t: max(t[1]['z']) - min(t[1]['z']))
    return lado, z['name']


def _operacion(escaneo, prioritaria):
    """Construye las 4 Informaciones (Secc 7) de una señal accionable:
    entrada, SL estructural, TP (zona contraria / 61.8 de alerta), ratio mínimo
    1:3 (Secc 1, al borde cercano de la zona objetivo — conservador) y la
    etiqueta Prioritario/Secundario con su volumen."""
    res = escaneo['resultado']
    d = res.get('detalles', {})
    lado = escaneo['lado']
    hechos = entrada_de_resultado(res, lado, escaneo['rango'])
    if hechos is not None:
        # Gatillo EJECUTADO: extracción unificada (mdt_gestion, misma que
        # usan el registro de operaciones reales y el backtest)
        entrada, sl, _ = hechos
    else:
        # Patrón sin gatillo aún: VISTA PREVIA de la operación (entrada
        # calmada esperada / cruce del límite en el EE armado)
        entrada = (d.get('gatillo_agresivo') or d.get('entrada_p3_corta')
                   or d.get('entrada_dt_618') or d.get('espera_calmada'))
        if entrada is None and res['estado'].startswith('EE_'):
            entrada = escaneo['rango'][0] if lado == "SELL" else escaneo['rango'][1]
        sl = d.get('stop_loss', d.get('extremo_escape'))
    tp_zona = escaneo.get('tp_zona')
    if entrada is None or sl is None or tp_zona is None:
        return None
    tp = max(tp_zona) if lado == "SELL" else min(tp_zona)  # borde cercano (conservador)
    riesgo = abs(sl - entrada)
    if riesgo <= 0:
        return None
    recompensa = abs(entrada - tp)
    ratio = recompensa / riesgo
    # Regla del usuario (10 jul): la señal HEREDA la prioridad de SU zona — si
    # una zona en trabajo te da la entrada, esa operación es el Movimiento
    # Prioritario de ese trabajo, con sus propios TP ("en el trading nada es
    # seguro: cada oportunidad que se opere tendrá sus propios TP"). La
    # dirección global (zona más angosta no-contexto con el precio dentro) ya
    # no degrada la señal a Secundaria; si hay trabajo vivo en contra, se avisa.
    aviso = None
    if prioritaria is not None and lado != prioritaria:
        aviso = ("hay trabajo vivo en contra: el precio está dentro de una zona de "
                 + ("VENTAS" if prioritaria == "SELL" else "COMPRAS"))
    return {"entrada": entrada, "stop_loss": sl,
            "tp_zona": (max(tp_zona), min(tp_zona)), "tp_nivel": tp,
            "riesgo": riesgo, "recompensa": recompensa, "ratio": ratio,
            "cumple_ratio": ratio >= RATIO_MINIMO,
            "movimiento": "PRIORITARIO (su zona en trabajo)", "aviso": aviso,
            "volumen": "Normal"}


def _escanear_zona(zona, lado, limite, cutoff, symbol, cache_df, precio):
    """Escanea la cadena de patrones de UNA zona (episodio operativo recortado).

    Secc 13 (checklist 1): el patrón solo vale dentro de una zona ACTIVA — la
    ventana arranca en operativa_desde (activación del ciclo o apertura de la
    excursión); la estructura anterior es historia de otro contexto.
    """
    from mdt_patrones import detect_patron_institucional
    tf_patron = TF_PATRON.get(zona['tf'], zona['tf'])
    if tf_patron not in cache_df:
        desde = limite - pd.Timedelta(minutes=VELAS_ESCANEO * TF_MINUTOS[tf_patron])
        df = _descargar(tf_patron, desde, cutoff, symbol)
        df['open_time'] = to_cot(df['open_time'])
        cache_df[tf_patron] = df
    df = cache_df[tf_patron]
    df_z = df
    desde_op = zona.get('operativa_desde')
    if desde_op is not None:
        pos = int(df['open_time'].searchsorted(to_cot(pd.Timestamp(desde_op))))
        df_z = df.iloc[max(0, pos - 2):].reset_index(drop=True)
    zmax, zmin = max(zona['z']), min(zona['z'])
    res = detect_patron_institucional(df_z, zmax, zmin, lado,
                                      nivel_anulacion=zona.get('nivel_anulacion'))
    # Zonas macro (más anchas que el % del precio) = CONTEXTO, no se operan
    es_contexto = (zmax - zmin) > precio * ZONA_MAX_OPERABLE_PCT
    return {'zona': zona['name'], 'rango': (zmax, zmin), 'lado': lado,
            'tf_ciclo': zona['tf'], 'tf_patron': tf_patron,
            'ancla': zona.get('ancla'), 'tp_zona': zona.get('tp_zona'),
            'ciclo_origen': zona.get('ciclo_origen'), 'ciclo_fin': zona.get('ciclo_fin'),
            'contexto': es_contexto, 'operativa_desde': desde_op, 'resultado': res}


def escanear_mapa(cutoff=None, mapa=None, verbose=True, symbol=SYMBOL):
    """Genera (o recibe) el mapa y escanea patrones en cada zona operativa final.

    Devuelve {'mapa': ..., 'escaneos': [{zona, rango, lado, tf_ciclo, tf_patron,
    ancla, resultado}, ...]}. El escáner NO decide entradas: reporta el estado del
    patrón de cada zona; la gestión/el candado ancla_viva son de quien lo llama.
    """
    if mapa is None:
        mapa = generar_mapa(cutoff, verbose=False, symbol=symbol)

    limite = cutoff if cutoff is not None else _ahora()
    cache_df = {}
    escaneos = []
    for lado, zonas in (("SELL", mapa['sells']), ("BUY", mapa['buys'])):
        for zona in zonas:
            if zona.get('z') is None or zona.get('tf') is None:
                continue  # alertas o zonas sin ciclo rastreable
            escaneos.append(_escanear_zona(zona, lado, limite, cutoff, symbol,
                                           cache_df, mapa['precio']))

    # Las 4 Informaciones (Secc 7) para cada señal accionable (no-contexto)
    prioritaria, zona_que_manda = direccion_prioritaria(mapa)
    for e in escaneos:
        if e['resultado']['estado'] in ESTADOS_OPERABLES and not e['contexto']:
            e['operacion'] = _operacion(e, prioritaria)

    if verbose:
        if zona_que_manda:
            print(f"\nTRABAJO ACTUAL DEL PRECIO: dentro de '{zona_que_manda}' "
                  f"({'COMPRAS' if prioritaria == 'BUY' else 'VENTAS'}) — cada señal "
                  "hereda la prioridad de su propia zona")
        print("\n--- ESCÁNER DE PATRONES SOBRE EL MAPA (TF del patrón = 1 por debajo del ciclo) ---")
        for e in escaneos:
            res = e['resultado']
            marca = " <<<" if res['estado'] in ESTADOS_OPERABLES and not e['contexto'] else ""
            ctx = " [ZONA MACRO: contexto, no se opera]" if e['contexto'] else ""
            print(f"[{e['lado']}] {e['zona']} {e['rango'][0]:.2f}-{e['rango'][1]:.2f} "
                  f"(ciclo {e['tf_ciclo']} -> patrón {e['tf_patron']}, ancla {e['ancla']:.2f}){ctx}")
            # Trabajos de la zona (regla usuario 6 jul): TODA la cadena evaluada en el
            # episodio operativo — el usuario necesita ver si la zona YA fue trabajada
            # (entradas profundas, engaños, EE...), no solo el estado vigente.
            previos = [h for h in (res.get('historial') or []) if h is not res]
            for k, h in enumerate(previos, 1):
                dh = h.get('detalles', {})
                hora_h = dh.get('hora_gatillo') or dh.get('hora_validacion') or dh.get('pauta1_time')
                hora_h_txt = f" @ {hora_h}" if hora_h is not None else ""
                print(f"      trabajo {k}: {h['estado']}{hora_h_txt} — {h['mensaje']}")
            d_res = res.get('detalles', {})
            hora = d_res.get('hora_gatillo')
            hora_txt = f" [gatillo: {hora}]" if hora is not None else ""
            lleg = d_res.get('calidad_llegada')
            lleg_txt = ""
            if lleg == "BARRIDO":
                lleg_txt = (f" [LLEGADA: BARRIDO ⚡ mecha {d_res.get('mecha_vs_cuerpo')}x, "
                            f"{d_res.get('velas_visita')} vela(s)]")
            elif lleg == "LENTA":
                lleg_txt = f" [LLEGADA: LENTA — {d_res.get('cierres_dentro')} cierres dentro]"
            pref = f"trabajo {len(previos) + 1} (vigente): " if previos else ""
            print(f"      {pref}{res['estado']}: {res['mensaje']}{hora_txt}{lleg_txt}{marca}")
            op = e.get('operacion')
            if op:
                veredicto = (f"CUMPLE 1:{RATIO_MINIMO:.0f}" if op['cumple_ratio']
                             else f"NO CUMPLE 1:{RATIO_MINIMO:.0f} -> NO OPERAR (Secc 1)")
                print(f"      OPERACIÓN: entrada {op['entrada']:.2f} | SL {op['stop_loss']:.2f} "
                      f"(riesgo {op['riesgo']:.2f}) | TP zona {op['tp_zona'][0]:.2f}-{op['tp_zona'][1]:.2f} "
                      f"(al borde: {op['recompensa']:.2f})")
                print(f"      R:B 1:{op['ratio']:.1f} [{veredicto}] | {op['movimiento']} "
                      f"| Volumen: {op['volumen']}")
                if op.get('aviso'):
                    print(f"      AVISO: {op['aviso']}")
    return {'mapa': mapa, 'escaneos': escaneos,
            'prioritaria': prioritaria, 'zona_que_manda': zona_que_manda}


def _puntaje_patron(e):
    """Calidad del patrón para el DUELO entre tramos (regla usuario 12 jul:
    "cuando tengamos patrones que concurran en zona con otras [de otro tramo],
    miraremos en cuál patrón operaremos dependiendo de la calidad del patrón").
    Orden: llegada BARRIDO > NORMAL > LENTA; gatillo vivo > en espera;
    proporcional; sin carencia implícita en estado; ratio como desempate."""
    res = e['resultado']
    d = res.get('detalles', {})
    lleg = {'BARRIDO': 2, 'NORMAL': 1, 'LENTA': 0}.get(d.get('calidad_llegada'), 1)
    gatillo = 1 if 'GATILLO' in res['estado'] else 0
    prop = 1 if d.get('proporcional') else 0
    op = e.get('operacion') or {}
    return (lleg, gatillo, prop, op.get('ratio', 0.0))


def _rangos_solapan(a, b):
    return min(a[0], b[0]) >= max(a[1], b[1])  # rangos son (max, min)


def duelos_entre_tramos(escaneos):
    """Duelos de patrones: señales accionables del MISMO lado cuyas zonas
    concurren (se solapan) pero pertenecen a TRAMOS DISTINTOS — dentro del
    tramo manda la concurrencia de zonas (Secc 19); entre tramos decide la
    CALIDAD del patrón. Devuelve grupos ordenados: el primero es el ganador."""
    acc = [e for e in escaneos
           if e['resultado']['estado'] in ESTADOS_OPERABLES and not e['contexto']
           and e.get('tramo') is not None]
    grupos = []
    for e in acc:
        for g in grupos:
            if (g[0]['lado'] == e['lado']
                    and any(_rangos_solapan(x['rango'], e['rango']) for x in g)):
                g.append(e)
                break
        else:
            grupos.append([e])
    duelos = []
    for g in grupos:
        if len({x['tramo'] for x in g}) >= 2:
            g.sort(key=_puntaje_patron, reverse=True)
            duelos.append(g)
    return duelos


def escanear_tramos(cutoff=None, mapa=None, verbose=True, symbol=SYMBOL):
    """Escáner de patrones POR TRAMO (regla usuario 12 jul): cada tramo
    independiente escanea SUS zonas finales (concurrencia interna Secc 19) y
    las señales salen etiquetadas con su tramo. Caso que lo motivó: el
    EE_GATILLO de la Alta del M5 (venta 582.05/SL 583.42, el techo del rally
    del 11 jul) solo era visible en la vista por tramos — en el mapa global
    esa Alta queda absorbida (Caso 1) por la Media del Bajista N4.

    Devuelve {'mapa', 'escaneos' (con e['tramo']), 'duelos'}: los duelos son
    grupos de patrones accionables de TRAMOS DISTINTOS cuyas zonas concurren,
    ordenados por calidad (el primero gana)."""
    from mdt_macro_mapper import zonas_finales_tramo
    if mapa is None:
        mapa = generar_mapa(cutoff, verbose=False, symbol=symbol)
    limite = cutoff if cutoff is not None else _ahora()
    cache_df = {}
    escaneos = []
    for t in mapa.get('tramos', []):
        for lado, zona in zonas_finales_tramo(t, mapa['precio']):
            if zona.get('z') is None or zona.get('tf') is None or zona.get('ancla') is None:
                continue
            e = _escanear_zona(zona, lado, limite, cutoff, symbol, cache_df, mapa['precio'])
            e['tramo'] = t['nombre']
            if e['resultado']['estado'] in ESTADOS_OPERABLES and not e['contexto']:
                # La señal hereda la prioridad de SU zona (regla 10 jul)
                e['operacion'] = _operacion(e, None)
            escaneos.append(e)
    duelos = duelos_entre_tramos(escaneos)

    if verbose:
        print("\n--- ESCÁNER DE PATRONES POR TRAMO (zonas independientes por muñeca) ---")
        for e in escaneos:
            res = e['resultado']
            if res['estado'] == 'NO_INICIADO':
                continue
            marca = " <<<" if res['estado'] in ESTADOS_OPERABLES and not e['contexto'] else ""
            ctx = " [contexto]" if e['contexto'] else ""
            d = res.get('detalles', {})
            lleg = d.get('calidad_llegada')
            lleg_txt = f" [LLEGADA: {lleg}]" if lleg and lleg != 'NORMAL' else ""
            print(f"[{e['tramo']}] [{e['lado']}] {e['zona']} "
                  f"{e['rango'][0]:.2f}-{e['rango'][1]:.2f}{ctx}")
            print(f"      {res['estado']}: {res['mensaje'][:110]}{lleg_txt}{marca}")
            op = e.get('operacion')
            if op:
                print(f"      OPERACIÓN: entrada {op['entrada']:.2f} | SL {op['stop_loss']:.2f} "
                      f"| TP {op['tp_zona'][0]:.2f}-{op['tp_zona'][1]:.2f} | R:B 1:{op['ratio']:.1f}")
        for g in duelos:
            gana = g[0]
            print(f"\n🥇 DUELO ({'VENTAS' if gana['lado'] == 'SELL' else 'COMPRAS'} concurrentes "
                  f"entre tramos): GANA {gana['zona']} [{gana['tramo']}] "
                  f"(llegada {gana['resultado'].get('detalles', {}).get('calidad_llegada', '?')}, "
                  f"{gana['resultado']['estado']})")
            for x in g[1:]:
                print(f"      pierde: {x['zona']} [{x['tramo']}] ({x['resultado']['estado']})")
    return {'mapa': mapa, 'escaneos': escaneos, 'duelos': duelos}


def escanear_completo(cutoff=None, verbose=False, symbol=SYMBOL):
    """Escaneo global + escaneo por tramos, fusionados: las zonas que solo
    existen en la vista por tramos (las que la concurrencia global absorbió —
    caso Alta del M5) entran etiquetadas con su tramo; las compartidas no se
    duplican (manda la global). Los duelos entre tramos (regla usuario 12 jul)
    viajan en resultado['duelos']. Lo usan el bot en vivo y el backtest —
    misma lente, mismos números."""
    resultado = escanear_mapa(cutoff=cutoff, verbose=verbose, symbol=symbol)
    tr = escanear_tramos(cutoff=cutoff, mapa=resultado['mapa'], verbose=verbose, symbol=symbol)
    vistos = {(e['lado'], round(e['ancla'], 2), e['rango']) for e in resultado['escaneos']
              if e.get('ancla') is not None}
    extras = [e for e in tr['escaneos']
              if (e['lado'], round(e['ancla'], 2), e['rango']) not in vistos]
    resultado['escaneos'] = resultado['escaneos'] + extras
    resultado['duelos'] = tr['duelos']
    return resultado


def revalidar_setup(escaneo, cutoff=None, symbol=SYMBOL):
    """Candado mapa->escáner (Regla 3): ¿el ancla del setup sigue viva en un mapa
    fresco? Si el ancla fue enterrada (desgrane) o murió (138.2/evolución), el
    setup debe cancelarse aunque el patrón siga dibujado."""
    mapa = generar_mapa(cutoff, verbose=False, symbol=symbol)
    return ancla_viva(mapa, escaneo['ancla'])


if __name__ == "__main__":
    # Punto de entrada del ANÁLISIS COMPLETO: mapa (estructura macro + ciclos +
    # concurrencia) y escáner de patrones con las 4 Informaciones por señal.
    #   python mdt_escaner.py                          -> BNBUSDT, ahora
    #   python mdt_escaner.py --symbol ETHUSDT         -> otra moneda
    #   python mdt_escaner.py --cutoff "2026-07-01 04:21"  (UTC, time-travel)
    import argparse
    import sys
    # La consola de Windows llega en cp1252 y revienta con los emojis del reporte
    # (el motor ya había hecho todo el trabajo: sería una muerte por imprimir).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description="Análisis MDT completo de un símbolo")
    ap.add_argument("--symbol", default=SYMBOL, help="símbolo de futuros USDT-M (ej. ETHUSDT)")
    ap.add_argument("--cutoff", default=None, help="instante UTC para time-travel (default: ahora)")
    ap.add_argument("--tramos", action="store_true",
                    help="vista de tramos independientes (cada muñeca con sus propios "
                         "puntos de control y zonas, sin concurrencia entre tramos)")
    args = ap.parse_args()
    _cutoff = pd.Timestamp(args.cutoff) if args.cutoff else None
    if args.tramos:
        _mapa = generar_mapa(_cutoff, verbose=False, symbol=args.symbol.upper())
        print(reporte_tramos(_mapa))
        escanear_tramos(_cutoff, mapa=_mapa, verbose=True, symbol=args.symbol.upper())
    else:
        _mapa = generar_mapa(_cutoff, verbose=True, symbol=args.symbol.upper())
        escanear_mapa(_cutoff, mapa=_mapa, verbose=True, symbol=args.symbol.upper())
