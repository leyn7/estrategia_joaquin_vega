# -*- coding: utf-8 -*-
"""Estado persistente del bot en vivo + caché incremental de velas.

IMPORTANTE — este módulo debe importarse ANTES que el escáner/mapper: al
importarse parchea `get_binance_klines` con la versión cacheada. Sin la caché,
cada escaneo re-descargaría meses de velas de 1m.

El estado (estado_vivo.json) guarda watchlist, chat de Telegram, firmas de
eventos ya notificados, anclas vigiladas y las OPERACIONES REALES — que son
hechos y no se pueden perder: por eso hay backup .bak y recuperación.
"""
import json
import logging
import os
import shutil

import pandas as pd

import mdt_data
import mdt_telegram
from mdt_config import SYMBOL

log = logging.getLogger('mdt.estado')

INTERVALO = int(os.environ.get('MDT_INTERVALO', '300'))  # segundos entre escaneos
RUTA_ESTADO = os.environ.get('MDT_ESTADO', os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'estado_vivo.json'))
PODA_ESCANEOS = 288       # ~24h a 5 min: firmas ausentes tanto tiempo se purgan
MAX_OPS_CERRADAS = 30     # operaciones cerradas retenidas en el estado


def naive(ts):
    """Timestamp sin zona horaria (UTC), como los devuelve el feed."""
    ts = pd.Timestamp(ts)
    return ts.tz_convert('UTC').tz_localize(None) if ts.tzinfo is not None else ts


# ---------------------------------------------------------------------------
# Caché incremental de velas
# ---------------------------------------------------------------------------
_cache = {}
_descarga_original = mdt_data.get_binance_klines


def get_klines_vivo(symbol=SYMBOL, interval="1d", start_time=None):
    """Velas con caché: solo se re-descarga la COLA (que incluye la vela parcial
    en curso), no todo el histórico."""
    clave = (symbol, interval)
    inicio = naive(start_time) if start_time is not None else None
    df = _cache.get(clave)
    if df is None or (inicio is not None and df['open_time'].iloc[0] > inicio):
        df = _descarga_original(symbol, interval, start_time)
        if len(df):
            _cache[clave] = df
        return df.copy()
    ult = df['open_time'].iloc[-1]
    cola = _descarga_original(symbol, interval, ult.tz_localize('UTC'))
    if len(cola):
        df = pd.concat([df[df['open_time'] < cola['open_time'].iloc[0]], cola],
                       ignore_index=True)
        _cache[clave] = df
    if inicio is not None:
        return df[df['open_time'] >= inicio].reset_index(drop=True)
    return df.copy()


# Un solo parche basta: mdt_feed busca `mdt_data.get_binance_klines` en CADA
# llamada (no lo enlaza en el import), así que todo el motor respeta la caché.
# (Antes había que parchear también mdt_macro_mapper — una trampa silenciosa: al
# mover la descarga de módulo, el bot habría dejado de cachear sin avisar.)
mdt_data.get_binance_klines = get_klines_vivo


# ---------------------------------------------------------------------------
# Estado persistente
# ---------------------------------------------------------------------------
def cargar_estado():
    """Carga el estado con recuperación: si el JSON principal está corrupto se
    intenta el .bak (las operaciones reales son hechos que no se pueden perder).
    Tras una carga buena, el principal se respalda a .bak."""
    e = None
    for ruta in (RUTA_ESTADO, RUTA_ESTADO + '.bak'):
        if not os.path.exists(ruta):
            continue
        try:
            with open(ruta, encoding='utf-8') as f:
                e = json.load(f)
            if ruta.endswith('.bak'):
                log.warning("estado principal ilegible: RECUPERADO desde %s", ruta)
            break
        except (json.JSONDecodeError, OSError):
            log.exception("no se pudo leer %s", ruta)
    if e is None:
        e = {}
    elif os.path.exists(RUTA_ESTADO):
        try:
            shutil.copy2(RUTA_ESTADO, RUTA_ESTADO + '.bak')
        except OSError:
            log.exception("no se pudo escribir el backup del estado")
    e.setdefault('chat_id', mdt_telegram.CHAT_ENV or '')
    e.setdefault('offset', 0)
    e.setdefault('watchlist', [SYMBOL])
    e.setdefault('simbolos', {})
    e.setdefault('anclas', {})
    return e


def guardar_estado(e):
    """Escritura atómica (tmp + replace): un corte de luz no corrompe el estado."""
    tmp = RUTA_ESTADO + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(e, f, ensure_ascii=False, indent=1)
    os.replace(tmp, RUTA_ESTADO)


def podar_firmas(mem, vivas):
    """Purga las firmas de zonas/ciclos que ya no existen en el mapa tras
    PODA_ESCANEOS escaneos ausentes — sin esto el estado crece para siempre."""
    n = mem['_n'] = mem.get('_n', 0) + 1
    visto = mem.setdefault('visto', {})
    for cat, dic in vivas.items():
        activas, guardadas = dic
        for k in activas:
            visto[f"{cat}:{k}"] = n
        for k in list(guardadas):
            if n - visto.get(f"{cat}:{k}", n) > PODA_ESCANEOS:
                guardadas.pop(k)
                visto.pop(f"{cat}:{k}", None)
