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
from mdt_config import TF_PATRON, TF_MINUTOS, RATIO_MINIMO, ZONA_MAX_OPERABLE_PCT
from mdt_data import to_cot
from mdt_macro_mapper import generar_mapa, _descargar, _ahora, ancla_viva

VELAS_ESCANEO = 1500  # ventana máxima de velas de la TF del patrón

# Estados que representan un setup accionable o vivo (para resaltar en el reporte)
ESTADOS_OPERABLES = ("GATILLO_ACTIVADO", "P3_CORTA_GATILLO", "DT_IMPULSO_GATILLO",
                     "EE_GATILLO", "EE_ARMADO", "VALIDADO_POSTERIOR",
                     "ENTRADA_PROFUNDA_ESPERANDO", "DT_IMPULSO_ESPERANDO",
                     "ENGAÑO_EN_CURSO", "ESPERANDO_1618")


def direccion_prioritaria(mapa):
    """Regla del usuario (4 jul): "el que manda es el ciclo cuya zona se está
    trabajando ACTIVAMENTE" — la zona MÁS ESPECÍFICA (la más angosta) que contiene
    al precio, no la más grande que lo envuelva. Si el precio trabaja una zona de
    ventas, las ventas son el Movimiento Prioritario; operar en contra es un
    Movimiento Secundario con menor volumen/riesgo (Secc 1/7.1)."""
    precio = mapa['precio']
    candidatos = [("SELL", z) for z in mapa['sells']] + [("BUY", z) for z in mapa['buys']]
    contienen = [(lado, z) for lado, z in candidatos
                 if z.get('z') and min(z['z']) <= precio <= max(z['z'])]
    if not contienen:
        return None, None
    lado, z = min(contienen, key=lambda t: max(t[1]['z']) - min(t[1]['z']))
    return lado, z['name']


def _operacion(escaneo, prioritaria):
    """Construye las 4 Informaciones (Secc 7) de una señal accionable:
    entrada, SL estructural, TP (zona contraria / 61.8 de alerta), ratio 1:4
    (Secc 1, al borde cercano de la zona objetivo — conservador) y la etiqueta
    Prioritario/Secundario con su volumen."""
    res = escaneo['resultado']
    d = res.get('detalles', {})
    lado = escaneo['lado']
    entrada = (d.get('gatillo_agresivo') or d.get('entrada_p3_corta')
               or d.get('entrada_dt_618') or d.get('espera_calmada'))
    if entrada is None and res['estado'].startswith('EE_'):
        # Engaño Extremo: la agresiva entra al cruzar de vuelta el límite exterior
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
    prioritario = prioritaria is None or lado == prioritaria
    return {"entrada": entrada, "stop_loss": sl,
            "tp_zona": (max(tp_zona), min(tp_zona)), "tp_nivel": tp,
            "riesgo": riesgo, "recompensa": recompensa, "ratio": ratio,
            "cumple_ratio": ratio >= RATIO_MINIMO,
            "movimiento": "PRIORITARIO" if prioritario else "SECUNDARIO",
            "volumen": "Normal" if prioritario else "Reducido (Movimiento Secundario, Secc 1)"}


def escanear_mapa(cutoff=None, mapa=None, verbose=True):
    """Genera (o recibe) el mapa y escanea patrones en cada zona operativa final.

    Devuelve {'mapa': ..., 'escaneos': [{zona, rango, lado, tf_ciclo, tf_patron,
    ancla, resultado}, ...]}. El escáner NO decide entradas: reporta el estado del
    patrón de cada zona; la gestión/el candado ancla_viva son de quien lo llama.
    """
    from mdt_patrones import detect_patron_institucional

    if mapa is None:
        mapa = generar_mapa(cutoff, verbose=False)

    limite = cutoff if cutoff is not None else _ahora()
    cache_df = {}
    escaneos = []
    for lado, zonas in (("SELL", mapa['sells']), ("BUY", mapa['buys'])):
        for zona in zonas:
            if zona.get('z') is None or zona.get('tf') is None:
                continue  # alertas o zonas sin ciclo rastreable
            tf_patron = TF_PATRON.get(zona['tf'], zona['tf'])
            if tf_patron not in cache_df:
                desde = limite - pd.Timedelta(minutes=VELAS_ESCANEO * TF_MINUTOS[tf_patron])
                df = _descargar(tf_patron, desde, cutoff)
                df['open_time'] = to_cot(df['open_time'])
                cache_df[tf_patron] = df
            df = cache_df[tf_patron]
            # Secc 13 (checklist 1): el patrón solo vale dentro de una zona ACTIVA.
            # Se recorta la ventana al episodio operativo (desde la activación del
            # ciclo o la apertura de la excursión) — la estructura anterior a que la
            # zona existiera es historia de otro contexto, no Pautas de este trabajo.
            df_z = df
            desde_op = zona.get('operativa_desde')
            if desde_op is not None:
                pos = int(df['open_time'].searchsorted(to_cot(pd.Timestamp(desde_op))))
                df_z = df.iloc[max(0, pos - 2):].reset_index(drop=True)
            zmax, zmin = max(zona['z']), min(zona['z'])
            res = detect_patron_institucional(df_z, zmax, zmin, lado,
                                              nivel_anulacion=zona.get('nivel_anulacion'))
            # Preferencia del usuario: las zonas macro (más anchas que el % del
            # precio) son CONTEXTO — no se operan; sus oportunidades llegan por
            # los sub-ciclos pequeños de adentro.
            es_contexto = (zmax - zmin) > mapa['precio'] * ZONA_MAX_OPERABLE_PCT
            escaneos.append({'zona': zona['name'], 'rango': (zmax, zmin), 'lado': lado,
                             'tf_ciclo': zona['tf'], 'tf_patron': tf_patron,
                             'ancla': zona.get('ancla'), 'tp_zona': zona.get('tp_zona'),
                             'contexto': es_contexto,
                             'operativa_desde': desde_op, 'resultado': res})

    # Las 4 Informaciones (Secc 7) para cada señal accionable (no-contexto)
    prioritaria, zona_que_manda = direccion_prioritaria(mapa)
    for e in escaneos:
        if e['resultado']['estado'] in ESTADOS_OPERABLES and not e['contexto']:
            e['operacion'] = _operacion(e, prioritaria)

    if verbose:
        if zona_que_manda:
            print(f"\nEL CICLO QUE MANDA: precio trabajando '{zona_que_manda}' -> "
                  f"Movimiento Prioritario = {'COMPRAS' if prioritaria == 'BUY' else 'VENTAS'}")
        print("\n--- ESCÁNER DE PATRONES SOBRE EL MAPA (TF del patrón = 1 por debajo del ciclo) ---")
        for e in escaneos:
            res = e['resultado']
            marca = " <<<" if res['estado'] in ESTADOS_OPERABLES and not e['contexto'] else ""
            ctx = " [ZONA MACRO: contexto, no se opera]" if e['contexto'] else ""
            print(f"[{e['lado']}] {e['zona']} {e['rango'][0]:.2f}-{e['rango'][1]:.2f} "
                  f"(ciclo {e['tf_ciclo']} -> patrón {e['tf_patron']}, ancla {e['ancla']:.2f}){ctx}")
            hora = res.get('detalles', {}).get('hora_gatillo')
            hora_txt = f" [gatillo: {hora}]" if hora is not None else ""
            print(f"      {res['estado']}: {res['mensaje']}{hora_txt}{marca}")
            op = e.get('operacion')
            if op:
                veredicto = ("CUMPLE 1:4" if op['cumple_ratio']
                             else f"NO CUMPLE 1:{RATIO_MINIMO:.0f} -> NO OPERAR (Secc 1)")
                print(f"      OPERACIÓN: entrada {op['entrada']:.2f} | SL {op['stop_loss']:.2f} "
                      f"(riesgo {op['riesgo']:.2f}) | TP zona {op['tp_zona'][0]:.2f}-{op['tp_zona'][1]:.2f} "
                      f"(al borde: {op['recompensa']:.2f})")
                print(f"      R:B 1:{op['ratio']:.1f} [{veredicto}] | {op['movimiento']} "
                      f"| Volumen: {op['volumen']}")
    return {'mapa': mapa, 'escaneos': escaneos,
            'prioritaria': prioritaria, 'zona_que_manda': zona_que_manda}


def revalidar_setup(escaneo, cutoff=None):
    """Candado mapa->escáner (Regla 3): ¿el ancla del setup sigue viva en un mapa
    fresco? Si el ancla fue enterrada (desgrane) o murió (138.2/evolución), el
    setup debe cancelarse aunque el patrón siga dibujado."""
    mapa = generar_mapa(cutoff, verbose=False)
    return ancla_viva(mapa, escaneo['ancla'])


if __name__ == "__main__":
    escanear_mapa()
