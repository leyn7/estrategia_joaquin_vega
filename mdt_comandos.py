# -*- coding: utf-8 -*-
"""Comandos que el operador manda al bot por Telegram.

Solo el chat autorizado manda (el primero que escriba queda vinculado, salvo que
MDT_TG_CHAT lo fije). Los comandos que tardan (analiza, tramos, ancla) avisan
antes de ponerse a trabajar: el escaneo completo puede tomar minutos.
"""
import logging

import requests

import mdt_telegram
from mdt_config import SYMBOL
from mdt_escaner import escanear_completo
from mdt_estado import guardar_estado
from mdt_formato import resumen_analisis
from mdt_ops import texto_operaciones

log = logging.getLogger('mdt.comandos')

AYUDA = ("Comandos:\n"
         "  lista — símbolos vigilados\n"
         "  agrega SYM — añade a la vigilancia (ej. agrega ETHUSDT)\n"
         "  quita SYM — deja de vigilar\n"
         "  analiza SYM — análisis completo puntual (1-3 min)\n"
         "  tramos SYM — mapa por tramos independientes (cada muñeca aparte)\n"
         "  operaciones — operaciones reales registradas (SL/parcial/estado)\n"
         "\n⚓ ANCLAS PROPIAS (tú marcas el origen del tramo):\n"
         "  ancla PRECIO [SYM] — mapea ese tramo (ciclos + zonas) y lo VIGILA;\n"
         "     avisa cuando el precio entre en una zona operativa suya.\n"
         "     Sentido automático (mínimo=alcista / máximo=bajista).\n"
         "     Forzarlo: ancla 560.58 alcista\n"
         "  anclas — las anclas que estoy vigilando\n"
         "  borra ancla PRECIO — dejar de vigilarla\n"
         "  ayuda — esto")


def simbolo_valido(sym):
    try:
        r = requests.get('https://fapi.binance.com/fapi/v1/klines',
                         params={'symbol': sym, 'interval': '1d', 'limit': 2},
                         timeout=10)
        return r.status_code == 200 and isinstance(r.json(), list)
    except requests.RequestException:
        return False


def _cmd_lista(estado):
    lineas = []
    for s in estado['watchlist']:
        p = estado['simbolos'].get(s, {}).get('ultimo_precio')
        lineas.append(f"  {s}" + (f" — último {p:.2f}" if p else " — sin escanear aún"))
    return "Vigilando:\n" + '\n'.join(lineas)


def _cmd_ancla(estado, partes):
    """ancla PRECIO [SYM] [alcista|bajista] — mapea ese tramo y lo deja vigilado."""
    try:
        precio_a = float(partes[1].replace(',', '.'))
    except ValueError:
        return "Uso: ancla 560.58 [SYM] [alcista|bajista]"
    resto = [p.lower() for p in partes[2:]]
    sym = next((p.upper() for p in partes[2:] if p.upper().endswith('USDT')), SYMBOL)
    direccion = ("BULLISH" if 'alcista' in resto else
                 "BEARISH" if 'bajista' in resto else None)
    mdt_telegram.enviar(estado['chat_id'],
                        f"⚓ Mapeando el tramo desde {precio_a:.2f}... (1-3 min)")
    try:
        from mdt_macro_mapper import analizar_ancla, reporte_ancla
        a = analizar_ancla(precio_a, symbol=sym, direction=direccion)
        if a is None:
            return f"No pude ubicar el ancla {precio_a:.2f} en el gráfico de {sym}."
        estado.setdefault('anclas', {})[f"{sym}|{a['ancla']:.2f}"] = {
            'symbol': sym, 'ancla': a['ancla'], 'direction': a['direction'],
            'zonas_vistas': {},
        }
        guardar_estado(estado)
        return (reporte_ancla(a) + "\n\n👁 VIGILANDO este tramo: te aviso cuando el "
                "precio entre en una de sus zonas operativas.")
    except Exception as e:  # noqa: BLE001 — se le reporta al operador
        log.exception("ancla %s", precio_a)
        return f"Error mapeando el ancla: {e}"


def _cmd_borra_ancla(estado, partes):
    try:
        p = float(partes[2].replace(',', '.'))
    except ValueError:
        return "Uso: borra ancla 560.58"
    anclas = estado.setdefault('anclas', {})
    fuera = [k for k in anclas if abs(anclas[k]['ancla'] - p) < 0.01]
    for k in fuera:
        anclas.pop(k)
    guardar_estado(estado)
    return f"🗑 Ancla {p:.2f} eliminada." if fuera else f"No vigilaba el ancla {p:.2f}."


def atender_comando(estado, texto):
    """Ejecuta un comando y devuelve la respuesta (texto) para el chat."""
    partes = texto.split()
    if not partes:
        return AYUDA
    cmd = partes[0].lower().lstrip('/')
    arg = partes[1].upper() if len(partes) > 1 else ''

    if cmd in ('start', 'ayuda', 'help'):
        return AYUDA
    if cmd in ('lista', 'list', 'estado'):
        return _cmd_lista(estado)
    if cmd in ('operaciones', 'ops', 'operacion'):
        bloques = [b for b in (texto_operaciones(s, estado['simbolos'].get(s, {}))
                               for s in estado['watchlist']) if b]
        return '\n\n'.join(bloques) if bloques else "Sin operaciones registradas aún."

    if cmd in ('agrega', 'add') and arg:
        if arg in estado['watchlist']:
            return f"{arg} ya está en la lista."
        if not simbolo_valido(arg):
            return f"{arg} no existe en futuros USDT-M de Binance."
        estado['watchlist'].append(arg)
        return f"{arg} agregado. El primer análisis sale en el próximo ciclo."
    if cmd in ('quita', 'remove', 'quitar') and arg:
        if arg not in estado['watchlist']:
            return f"{arg} no estaba en la lista."
        estado['watchlist'].remove(arg)
        estado['simbolos'].pop(arg, None)
        return f"{arg} eliminado de la vigilancia."

    if cmd == 'ancla' and len(partes) > 1:
        return _cmd_ancla(estado, partes)
    if cmd == 'anclas':
        anclas = estado.get('anclas') or {}
        if not anclas:
            return "Sin anclas vigiladas. Envía: ancla 560.58"
        lineas = ["⚓ Anclas vigiladas:"]
        for v in anclas.values():
            sentido = 'alcista' if v['direction'] == 'BULLISH' else 'bajista'
            lineas.append(f"  {v['symbol']} {v['ancla']:.2f} ({sentido})")
        return '\n'.join(lineas)
    if cmd == 'borra' and len(partes) > 2 and partes[1].lower() == 'ancla':
        return _cmd_borra_ancla(estado, partes)

    if cmd in ('tramos', 'tramo'):
        sym = arg or SYMBOL
        if not simbolo_valido(sym):
            return f"{sym} no existe en futuros USDT-M de Binance."
        mdt_telegram.enviar(estado['chat_id'], f"Armando tramos de {sym}... (1-3 min)")
        try:
            from mdt_macro_mapper import generar_mapa, reporte_tramos
            return reporte_tramos(generar_mapa(verbose=False, symbol=sym))
        except Exception as e:  # noqa: BLE001
            log.exception("tramos %s", sym)
            return f"Error armando tramos de {sym}: {e}"

    if cmd in ('analiza', 'analizar', 'analisis') or (cmd.endswith('usdt') and not arg):
        sym = arg or cmd.upper()
        if not simbolo_valido(sym):
            return f"{sym} no existe en futuros USDT-M de Binance."
        mdt_telegram.enviar(estado['chat_id'], f"Analizando {sym}... (1-3 min)")
        try:
            return resumen_analisis(sym, escanear_completo(verbose=False, symbol=sym))
        except Exception as e:  # noqa: BLE001
            log.exception("analiza %s", sym)
            return f"Error analizando {sym}: {e}"

    return "No entendí. " + AYUDA


def procesar_comandos(estado, timeout=20):
    """Long-poll de Telegram: atiende los comandos que hayan llegado."""
    mensajes, estado['offset'] = mdt_telegram.leer_mensajes(estado['offset'], timeout)
    for chat, texto in mensajes:
        if not estado['chat_id']:
            estado['chat_id'] = chat
            mdt_telegram.enviar(chat, "Chat vinculado ✔ Este es ahora el chat "
                                      "autorizado del bot MDT.\n\n" + AYUDA)
            continue
        if chat != str(estado['chat_id']):
            continue  # solo el chat autorizado
        respuesta = atender_comando(estado, texto)
        mdt_telegram.enviar(estado['chat_id'], respuesta)
        guardar_estado(estado)
