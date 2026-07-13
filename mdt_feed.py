# -*- coding: utf-8 -*-
"""Acceso al feed de velas para el motor del mapa.

OJO — POR QUÉ `mdt_data.get_binance_klines` SE BUSCA EN CADA LLAMADA (y no con
un `from mdt_data import ...`): el bot en vivo y los backtests SUSTITUYEN esa
función por una versión cacheada (mdt_estado) o con time-travel (backtests). Si
aquí se enlazara el nombre en el import, este módulo se quedaría con la función
ORIGINAL y el parche no tendría efecto — el bot re-descargaría meses de velas de
1m en cada escaneo, sin avisar. Con la búsqueda dinámica basta con parchear
`mdt_data.get_binance_klines` y todo el motor lo respeta.
"""
import pandas as pd

import mdt_data
from mdt_config import SYMBOL, TF_LADDER, TF_MINUTOS, MAX_VELAS_DESCARGA


def ahora():
    """Instante actual en UTC naive (el formato del feed)."""
    return pd.Timestamp.now(tz='UTC').tz_localize(None)


def descargar(tf, desde=None, cutoff=None, symbol=SYMBOL):
    """Velas de una temporalidad, recortadas al cutoff (time-travel honesto: el
    mapa nunca ve una vela posterior al instante que se está reconstruyendo)."""
    start = pd.Timestamp(desde).tz_localize('UTC') if desde is not None else None
    df = mdt_data.get_binance_klines(symbol, tf, start_time=start)  # búsqueda dinámica
    if cutoff is not None:
        df = df[df['open_time'] <= cutoff]
    return df.reset_index(drop=True)


def tf_para_span(span_min):
    """La TF más fina cuyo número de velas cabe en el presupuesto de descarga."""
    for tf in reversed(TF_LADDER):
        if span_min / TF_MINUTOS[tf] <= MAX_VELAS_DESCARGA:
            return tf
    return TF_LADDER[0]
