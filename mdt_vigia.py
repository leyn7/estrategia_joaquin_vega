# -*- coding: utf-8 -*-
"""EL VIGÍA (fase 1: MODO SOMBRA) — reacciona en segundos, no en ciclos.

Arquitectura del operador (18 jul): "una sola vez escanea, luego va escribiendo
lo que hace el precio contra lo que ya tiene en memoria; solo se actualiza lo
que el precio toque".

Cómo funciona:
  - Cada escaneo completo refresca la TABLA DE NIVELES (mdt_niveles) — el escaneo
    pasa a ser el AUDITOR que garantiza que la memoria no deriva.
  - Entre escaneos, paso() mira SOLO las velas de 1m nuevas (una petición ligera
    que la caché resuelve) y detecta qué niveles cruzó el precio.

MODO SOMBRA: solo escribe su bitácora (logs/vigia.jsonl) y el log del servicio.
NO notifica, NO opera, NO toca el estado del bot. Sirve para medir, durante unos
días, cuánto se ANTICIPA a lo que el escáner descubre 5-10 minutos después. Si la
sombra demuestra que ve lo mismo (pero antes), pasa a mandar y el escaneo queda
de auditor horario.
"""
import json
import logging
import os
import time

import pandas as pd

from mdt_estado import get_klines_vivo
from mdt_niveles import tabla_de_niveles

log = logging.getLogger('mdt.vigia')

RUTA_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'logs', 'vigia.jsonl')

# Estado en memoria por símbolo (sombra: no se persiste; cada escaneo lo refresca)
_estado = {}   # sym -> {'tabla', 'ts_tabla', 'ultima_vela', 'vistos'}


def actualizar_tabla(sym, mapa):
    """El escaneo completo acaba de reconstruir el mapa: refrescar la memoria."""
    try:
        tabla = tabla_de_niveles(mapa)
    except Exception:  # noqa: BLE001 — la sombra jamás tumba al bot
        log.exception("vigia: no se pudo construir la tabla de %s", sym)
        return
    e = _estado.setdefault(sym, {'vistos': {}})
    e['tabla'] = tabla
    e['ts_tabla'] = time.time()
    e.setdefault('ultima_vela', None)
    log.info("vigia %s: tabla refrescada — %d niveles en memoria", sym, len(tabla))


def paso(sym):
    """Un latido del vigía: ¿las velas de 1m nuevas cruzaron algún nivel?
    Barato a propósito: una petición de velas (cache) + comparaciones."""
    e = _estado.get(sym)
    if not e or not e.get('tabla'):
        return []
    try:
        desde = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(minutes=10)
        df = get_klines_vivo(sym, '1m', desde.tz_localize('UTC'))
    except Exception:  # noqa: BLE001
        log.debug("vigia %s: feed no disponible en este latido", sym)
        return []
    if df is None or not len(df):
        return []

    # Solo velas NUEVAS desde el último latido (la última puede estar en curso:
    # también cuenta — el toque de un nivel no espera al cierre)
    if e.get('ultima_vela') is not None:
        df = df[df['open_time'] >= e['ultima_vela']]
    if not len(df):
        return []
    e['ultima_vela'] = df['open_time'].iloc[-1]

    lo = float(df['low'].min())
    hi = float(df['high'].max())
    precio = float(df['close'].iloc[-1])

    eventos = []
    for n in e['tabla']:
        nivel = n['nivel']
        if not (lo <= nivel <= hi):
            continue
        # dedupe: un nivel tocado no re-avisa hasta que la tabla se refresque
        # y el nivel siga existiendo, o pasen 30 min (retesteos sí interesan)
        visto = e['vistos'].get(n['id'], 0)
        if time.time() - visto < 1800:
            continue
        e['vistos'][n['id']] = time.time()
        ev = {'ts': pd.Timestamp.utcnow().isoformat(timespec='seconds'),
              'symbol': sym, 'tipo': n['tipo'], 'nivel': nivel,
              'precio': precio, 'detalle': n['detalle']}
        eventos.append(ev)
        log.info("vigia %s: %s @ %.2f (precio %.2f) — %s",
                 sym, n['tipo'], nivel, precio, n['detalle'][:60])
    if eventos:
        _bitacora(eventos)
    return eventos


def _bitacora(eventos):
    try:
        os.makedirs(os.path.dirname(RUTA_LOG), exist_ok=True)
        with open(RUTA_LOG, 'a', encoding='utf-8') as f:
            for ev in eventos:
                f.write(json.dumps(ev, ensure_ascii=False) + '\n')
    except OSError:
        log.exception("vigia: no se pudo escribir la bitácora")
