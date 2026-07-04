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
from mdt_config import TF_PATRON, TF_MINUTOS
from mdt_data import to_cot
from mdt_macro_mapper import generar_mapa, _descargar, _ahora, ancla_viva

VELAS_ESCANEO = 1500  # ventana máxima de velas de la TF del patrón

# Estados que representan un setup accionable o vivo (para resaltar en el reporte)
ESTADOS_OPERABLES = ("GATILLO_ACTIVADO", "P3_CORTA_GATILLO", "DT_IMPULSO_GATILLO",
                     "EE_GATILLO", "EE_ARMADO", "VALIDADO_POSTERIOR",
                     "ENTRADA_PROFUNDA_ESPERANDO", "DT_IMPULSO_ESPERANDO",
                     "ENGAÑO_EN_CURSO", "ESPERANDO_1618")


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
            escaneos.append({'zona': zona['name'], 'rango': (zmax, zmin), 'lado': lado,
                             'tf_ciclo': zona['tf'], 'tf_patron': tf_patron,
                             'ancla': zona.get('ancla'),
                             'operativa_desde': desde_op, 'resultado': res})

    if verbose:
        print("\n--- ESCÁNER DE PATRONES SOBRE EL MAPA (TF del patrón = 1 por debajo del ciclo) ---")
        for e in escaneos:
            res = e['resultado']
            marca = " <<<" if res['estado'] in ESTADOS_OPERABLES else ""
            print(f"[{e['lado']}] {e['zona']} {e['rango'][0]:.2f}-{e['rango'][1]:.2f} "
                  f"(ciclo {e['tf_ciclo']} -> patrón {e['tf_patron']}, ancla {e['ancla']:.2f})")
            hora = res.get('detalles', {}).get('hora_gatillo')
            hora_txt = f" [gatillo: {hora}]" if hora is not None else ""
            print(f"      {res['estado']}: {res['mensaje']}{hora_txt}{marca}")
    return {'mapa': mapa, 'escaneos': escaneos}


def revalidar_setup(escaneo, cutoff=None):
    """Candado mapa->escáner (Regla 3): ¿el ancla del setup sigue viva en un mapa
    fresco? Si el ancla fue enterrada (desgrane) o murió (138.2/evolución), el
    setup debe cancelarse aunque el patrón siga dibujado."""
    mapa = generar_mapa(cutoff, verbose=False)
    return ancla_viva(mapa, escaneo['ancla'])


if __name__ == "__main__":
    escanear_mapa()
