# -*- coding: utf-8 -*-
"""Integración mapa -> escáner (Regla 3: el mapa es la ÚNICA fuente de zonas).

Para cada zona operativa final del mapa (tras concurrencia), busca patrones de
giro (Secciones 9-18) en la TF DEL PATRÓN: una temporalidad por debajo de la TF
del ciclo (Secc 10: "bajar una temporalidad por debajo del tamaño del ciclo que
se está trabajando"). Cada resultado lleva el ancla de su ciclo: un bucle en
vivo debe re-validar con ancla_viva(mapa_fresco, ancla) antes de armar o
disparar cualquier entrada (candado mapa->escáner).

Este archivo ORQUESTA el escaneo; lo que decide y lo que se imprime vive aparte:
  mdt_operacion.py        las 4 Informaciones de una señal (Secc 7) + prioridad
  mdt_duelos.py           duelos de patrones entre tramos (calidad del patrón)
  mdt_reporte_escaner.py  los textos por consola
"""
import pandas as pd
from mdt_config import SYMBOL, TF_PATRON, TF_MINUTOS, ZONA_MAX_OPERABLE_PCT
from mdt_data import to_cot
from mdt_duelos import duelos_entre_tramos
from mdt_macro_mapper import generar_mapa, reporte_tramos, _descargar, _ahora, ancla_viva
from mdt_operacion import (ESTADOS_OPERABLES, construir_operacion,  # noqa: F401
                           direccion_prioritaria, es_accionable)
from mdt_reporte_escaner import imprimir_escaneo_mapa, imprimir_escaneo_tramos
from mdt_patrones import detect_patron_institucional

VELAS_ESCANEO = 1500  # ventana máxima de velas de la TF del patrón


def _escanear_zona(zona, lado, limite, cutoff, symbol, cache_df, precio):
    """Escanea la cadena de patrones de UNA zona (episodio operativo recortado).

    Secc 13 (checklist 1): el patrón solo vale dentro de una zona ACTIVA — la
    ventana arranca en operativa_desde (activación del ciclo o apertura de la
    excursión); la estructura anterior es historia de otro contexto.
    """
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
        if es_accionable(e):
            e['operacion'] = construir_operacion(e, prioritaria)

    if verbose:
        imprimir_escaneo_mapa(escaneos, prioritaria, zona_que_manda)
    return {'mapa': mapa, 'escaneos': escaneos,
            'prioritaria': prioritaria, 'zona_que_manda': zona_que_manda}


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
            if es_accionable(e):
                # La señal hereda la prioridad de SU zona (regla 10 jul)
                e['operacion'] = construir_operacion(e, None)
            escaneos.append(e)
    duelos = duelos_entre_tramos(escaneos)

    if verbose:
        imprimir_escaneo_tramos(escaneos, duelos)
    return {'mapa': mapa, 'escaneos': escaneos, 'duelos': duelos}


def escanear_ancla(a, cutoff=None, symbol=SYMBOL):
    """Patrones de las zonas del tramo que marcó el operador (regla usuario 13
    jul: "necesito que me termine el análisis — qué está ocurriendo o qué ocurrió
    en alguna de sus zonas"). El mapa del ancla dice DÓNDE están las zonas; esto
    dice QUÉ ha pasado dentro de ellas: toda la cadena de engaños del episodio
    (res['historial']), no solo el estado vigente.

    Devuelve la lista de escaneos, con su operación si el patrón es accionable."""
    limite = cutoff if cutoff is not None else _ahora()
    cache_df = {}
    escaneos = []
    for lado, zona in a['zonas']:
        if zona.get('z') is None or zona.get('tf') is None:
            continue
        e = _escanear_zona(zona, lado, limite, cutoff, symbol, cache_df, a['precio'])
        e['tramo'] = f"Ancla {a['ancla']:.2f}"
        if es_accionable(e):
            e['operacion'] = construir_operacion(e, None)
        escaneos.append(e)
    return escaneos


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
