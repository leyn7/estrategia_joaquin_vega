# -*- coding: utf-8 -*-
"""Telegram del bot MDT (bot propio: estrategia_juaqui_vega).

Token en MDT_TG_TOKEN (.env del servicio). El chat autorizado puede fijarse en
MDT_TG_CHAT; si no está, el bot ADOPTA el chat del primer mensaje que reciba
(quedará persistido en el estado por mdt_vivo) — así el operador solo tiene que
escribirle /start al bot una vez.
"""
import logging
import os

import requests

log = logging.getLogger('mdt.telegram')

TOKEN = os.environ.get('MDT_TG_TOKEN', '')
CHAT_ENV = os.environ.get('MDT_TG_CHAT', '')
MAX_LEN = 3900  # margen bajo el límite de 4096 de Telegram


def _api(metodo):
    return f'https://api.telegram.org/bot{TOKEN}/{metodo}'


def enviar(chat_id, texto):
    """Envía texto plano (troceado si excede el límite). True si todo salió."""
    if not TOKEN or not chat_id:
        # modo prueba sin token: el texto va a la consola (consolas Windows
        # cp1252 no soportan emoji -> degradar en vez de reventar)
        linea = f"[TELEGRAM->{chat_id or 'sin chat'}]\n{texto}\n"
        try:
            print(linea)
        except UnicodeEncodeError:
            print(linea.encode('ascii', 'replace').decode())
        return False
    ok = True
    while texto:
        trozo, texto = texto[:MAX_LEN], texto[MAX_LEN:]
        try:
            r = requests.post(_api('sendMessage'),
                              json={'chat_id': chat_id, 'text': trozo},
                              timeout=15)
            if r.status_code != 200:
                log.warning('telegram HTTP %s: %s', r.status_code, r.text[:120])
                ok = False
        except requests.RequestException as e:
            log.warning('telegram no disponible: %s', e)
            ok = False
    return ok


def leer_mensajes(offset, timeout=20):
    """Long-poll de mensajes nuevos. Devuelve ([(chat_id, texto)], nuevo_offset)."""
    if not TOKEN:
        return [], offset
    try:
        r = requests.get(_api('getUpdates'),
                         params={'offset': offset, 'timeout': timeout, 'limit': 10},
                         timeout=timeout + 10)
        d = r.json()
        if not d.get('ok'):
            return [], offset
        mensajes = []
        for u in d['result']:
            offset = max(offset, u['update_id'] + 1)
            m = u.get('message') or {}
            chat = (m.get('chat') or {}).get('id')
            if chat is not None and m.get('text'):
                mensajes.append((str(chat), m['text'].strip()))
        return mensajes, offset
    except requests.RequestException:
        return [], offset
