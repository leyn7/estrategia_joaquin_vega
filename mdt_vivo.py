# -*- coding: utf-8 -*-
"""Bucle en vivo del bot MDT: escaneo periódico + eventos + Telegram.

Eventos que se notifican (una sola vez cada uno, con dedup por estado):
  1. ACTIVACIÓN 38.2: un ciclo del mapa pasa de EN ALERTA a ACTIVADO.
  2. LLEGADA A ZONA: el precio entra en una zona operativa final (no-contexto).
  3. PATRÓN: la zona cambia a un estado operable o a un hito (carencia viva,
     patrón muerto) — con ancla, TF y las 4 Informaciones si es accionable.

Comandos por Telegram: lista | agrega SYM | quita SYM | analiza SYM | ayuda.
El primer chat que escriba queda vinculado (si MDT_TG_CHAT no está fijado).

Estado persistente en JSON (MDT_ESTADO, default ./estado_vivo.json): watchlist,
offset de Telegram, chat vinculado y firmas de eventos ya notificados.
Uso local de prueba (sin token, mensajes a consola):
  python mdt_vivo.py --una-pasada
"""
import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import requests

import mdt_data
import mdt_telegram
from mdt_config import SYMBOL, RATIO_MINIMO, ZONA_MAX_OPERABLE_PCT
from mdt_data import to_cot

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger('mdt.vivo')

INTERVALO = int(os.environ.get('MDT_INTERVALO', '300'))  # segundos entre escaneos
RUTA_ESTADO = os.environ.get('MDT_ESTADO', os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'estado_vivo.json'))

# ---------------------------------------------------------------------------
# Caché incremental de velas: sin ella cada escaneo re-descargaría meses de 1m.
# Misma técnica que _backtest_estrategia: se parchea get_binance_klines ANTES
# de importar el escáner. La cola (vela parcial incluida) se refresca siempre.
# ---------------------------------------------------------------------------
_cache = {}
_descarga_original = mdt_data.get_binance_klines


def _naive(ts):
    ts = pd.Timestamp(ts)
    return ts.tz_convert('UTC').tz_localize(None) if ts.tzinfo is not None else ts


def get_klines_vivo(symbol=SYMBOL, interval="1d", start_time=None):
    clave = (symbol, interval)
    inicio = _naive(start_time) if start_time is not None else None
    df = _cache.get(clave)
    if df is None or (inicio is not None and df['open_time'].iloc[0] > inicio):
        df = _descarga_original(symbol, interval, start_time)
        if len(df):
            _cache[clave] = df
        return df.copy()
    # refrescar la cola desde la última vela cacheada (recoge la parcial en curso)
    ult = df['open_time'].iloc[-1]
    cola = _descarga_original(symbol, interval, ult.tz_localize('UTC'))
    if len(cola):
        df = pd.concat([df[df['open_time'] < cola['open_time'].iloc[0]], cola],
                       ignore_index=True)
        _cache[clave] = df
    if inicio is not None:
        return df[df['open_time'] >= inicio].reset_index(drop=True)
    return df.copy()


mdt_data.get_binance_klines = get_klines_vivo
import mdt_macro_mapper  # noqa: E402
mdt_macro_mapper.get_binance_klines = get_klines_vivo
from mdt_escaner import escanear_mapa, ESTADOS_OPERABLES  # noqa: E402

# Hitos no-operables que sí se notifican (elección del usuario: operables + hitos)
ESTADOS_HITO = ("ANULADO_POR_CARENCIA", "ROTO_POR_DOBLE_TOQUE", "ROTO_POR_STOP_LOSS",
                "P3_CORTA_ROTA", "ROTO_POR_RETESTEO_DILATACION", "ZONA_AGOTADA")


# ---------------------------------------------------------------------------
# Estado persistente
# ---------------------------------------------------------------------------
def cargar_estado():
    if os.path.exists(RUTA_ESTADO):
        with open(RUTA_ESTADO, encoding='utf-8') as f:
            e = json.load(f)
    else:
        e = {}
    e.setdefault('chat_id', mdt_telegram.CHAT_ENV or '')
    e.setdefault('offset', 0)
    e.setdefault('watchlist', [SYMBOL])
    e.setdefault('simbolos', {})
    return e


def guardar_estado(e):
    tmp = RUTA_ESTADO + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(e, f, ensure_ascii=False, indent=1)
    os.replace(tmp, RUTA_ESTADO)


# ---------------------------------------------------------------------------
# Formato de mensajes (horas en COT)
# ---------------------------------------------------------------------------
def _hora_cot(ts):
    if ts is None:
        return ''
    try:
        return to_cot(ts).strftime('%d %b %H:%M COT')
    except Exception:
        return str(ts)


def _texto_operacion(op):
    if not op:
        return ''
    ver = (f"CUMPLE 1:{RATIO_MINIMO:.0f}" if op['cumple_ratio']
           else f"NO CUMPLE 1:{RATIO_MINIMO:.0f} -> NO OPERAR")
    return (f"\n  Entrada {op['entrada']:.2f} | SL {op['stop_loss']:.2f} "
            f"(riesgo {op['riesgo']:.2f})"
            f"\n  TP zona {op['tp_zona'][0]:.2f}-{op['tp_zona'][1]:.2f}"
            f"\n  R:B 1:{op['ratio']:.1f} [{ver}] | {op['movimiento']}"
            f"\n  Volumen: {op['volumen']}")


def _texto_escaneo(e):
    res = e['resultado']
    d = res.get('detalles', {})
    hora = _hora_cot(d.get('hora_gatillo') or d.get('hora_validacion'))
    txt = (f"{res['estado']} en {e['zona']} {e['rango'][0]:.2f}-{e['rango'][1]:.2f}\n"
           f"  ciclo {e['tf_ciclo']} (ancla {e['ancla']:.2f}) -> patrón {e['tf_patron']}\n"
           f"  {res['mensaje']}")
    if hora:
        txt += f"\n  hora: {hora}"
    return txt + _texto_operacion(e.get('operacion'))


def resumen_analisis(sym, resultado):
    """Resumen compacto de un escaneo completo (baseline y comando 'analiza')."""
    mapa = resultado['mapa']
    p = mapa['precio']
    lineas = [f"=== {sym} | precio {p:.2f} ==="]
    if resultado['zona_que_manda']:
        dir_txt = 'VENTAS' if resultado['prioritaria'] == 'SELL' else 'COMPRAS'
        lineas.append(f"Manda: {resultado['zona_que_manda']} -> prioritario {dir_txt}")
    ventas = sorted((z for z in mapa['sells'] if z.get('z')), key=lambda z: min(z['z']))
    compras = sorted((z for z in mapa['buys'] if z.get('z')), key=lambda z: -max(z['z']))
    lineas.append("Ventas (arriba):")
    lineas += [f"  {z['name']}: {max(z['z']):.2f}-{min(z['z']):.2f}" for z in ventas[:4]]
    lineas.append("Compras (abajo):")
    lineas += [f"  {z['name']}: {max(z['z']):.2f}-{min(z['z']):.2f}" for z in compras[:4]]
    alertas = mapa.get('alerts') or []
    if alertas:
        lineas.append("Alertas 38.2 (activarían zona):")
        lineas += [f"  {a['name']}: toca {a['activacion']:.2f} -> {a['tipo']}"
                   for a in alertas[:5]]
    accionables = [e for e in resultado['escaneos']
                   if e['resultado']['estado'] in ESTADOS_OPERABLES and not e['contexto']]
    if accionables:
        lineas.append("SEÑALES VIVAS:")
        lineas += [_texto_escaneo(e) for e in accionables]
    else:
        lineas.append("Sin señales operables ahora.")
    return '\n'.join(lineas)


# ---------------------------------------------------------------------------
# Detección de eventos (transiciones entre escaneo anterior y actual)
# ---------------------------------------------------------------------------
def _clave_zona(lado, nombre, ancla):
    banda = nombre.rsplit('(', 1)[-1].rstrip(')') if '(' in nombre else '?'
    return f"{lado}|{banda}|{ancla:.2f}"


def detectar_eventos(sym, resultado, mem):
    """Compara el escaneo con la memoria del símbolo. Devuelve mensajes nuevos
    y actualiza `mem` in place. En la primera pasada solo registra (baseline)."""
    mapa = resultado['mapa']
    precio = mapa['precio']
    baseline = not mem.get('baseline')
    eventos = []
    ahora = pd.Timestamp.now(tz='UTC').tz_localize(None)

    # 1) Activaciones 38.2 (ciclos vivos que pasan de alerta a activado)
    act = mem.setdefault('activados', {})
    for c in mapa['ciclos']:
        ev = c.get('eval') or {}
        if ev.get('estado') != 'VIVO':
            continue
        k = f"{c['direction']}|{c['ancla']:.2f}"
        activado = bool(ev.get('activado'))
        previo = act.get(k)
        if not baseline and activado and previo is False:
            eventos.append(f"🔔 {sym} | CICLO ACTIVADO (tocó su 38.2): {c['nombre']} "
                           f"({c['tf']}, ancla {c['ancla']:.2f}) "
                           f"{_hora_cot(ev.get('hora_activacion'))}\n"
                           "Sus zonas de trabajo quedan operativas.")
        elif not baseline and activado and previo is None:
            # ciclo nuevo que nació ya activado: solo avisar si es reciente
            h = ev.get('hora_activacion')
            if h is not None and (ahora - _naive(h)) < pd.Timedelta(seconds=4 * INTERVALO):
                eventos.append(f"🔔 {sym} | CICLO NUEVO ACTIVADO: {c['nombre']} "
                               f"({c['tf']}, ancla {c['ancla']:.2f}) "
                               f"{_hora_cot(h)}")
        act[k] = activado

    # 2) Llegada del precio a una zona operativa final (no-contexto)
    en_zona = mem.setdefault('en_zona', {})
    for lado, zonas in (("SELL", mapa['sells']), ("BUY", mapa['buys'])):
        for z in zonas:
            if not z.get('z') or z.get('ancla') is None:
                continue
            zmax, zmin = max(z['z']), min(z['z'])
            if (zmax - zmin) > precio * ZONA_MAX_OPERABLE_PCT:
                continue  # zona macro: contexto, sin alertas de llegada
            k = _clave_zona(lado, z['name'], z['ancla'])
            dentro = bool(zmin <= precio <= zmax)  # bool nativo: np.bool_ no es JSON
            if not baseline and dentro and not en_zona.get(k):
                accion = 'VENTAS' if lado == 'SELL' else 'COMPRAS'
                eventos.append(f"📍 {sym} | PRECIO EN ZONA DE {accion}: {z['name']} "
                               f"{zmax:.2f}-{zmin:.2f} (ancla {z['ancla']:.2f}, "
                               f"ciclo {z.get('tf', '?')}) | precio {precio:.2f}\n"
                               "A vigilar formación de patrón (3 Pautas).")
            en_zona[k] = dentro

    # 3) Cambios de patrón por zona (operables + hitos), con dedup por firma
    patron = mem.setdefault('patron', {})
    for e in resultado['escaneos']:
        if e['contexto']:
            continue
        res = e['resultado']
        d = res.get('detalles', {})
        k = _clave_zona(e['lado'], e['zona'], e['ancla'])
        firma = f"{res['estado']}|{d.get('hora_gatillo') or d.get('pauta1_time') or ''}"
        if not baseline and firma != patron.get(k):
            if res['estado'] in ESTADOS_OPERABLES:
                eventos.append(f"🎯 {sym} | SEÑAL: {_texto_escaneo(e)}")
            elif res['estado'] in ESTADOS_HITO:
                eventos.append(f"💀 {sym} | HITO: {_texto_escaneo(e)}")
        patron[k] = firma

    mem['baseline'] = True
    mem['ultimo_escaneo'] = str(ahora)
    mem['ultimo_precio'] = float(precio)
    if baseline:
        return [f"👁 Vigilando {sym} (escaneo cada {INTERVALO // 60} min).\n\n"
                + resumen_analisis(sym, resultado)]
    return eventos


# ---------------------------------------------------------------------------
# Comandos de Telegram
# ---------------------------------------------------------------------------
AYUDA = ("Comandos:\n"
         "  lista — símbolos vigilados\n"
         "  agrega SYM — añade a la vigilancia (ej. agrega ETHUSDT)\n"
         "  quita SYM — deja de vigilar\n"
         "  analiza SYM — análisis completo puntual (1-3 min)\n"
         "  ayuda — esto")


def _simbolo_valido(sym):
    try:
        r = requests.get('https://fapi.binance.com/fapi/v1/klines',
                         params={'symbol': sym, 'interval': '1d', 'limit': 2},
                         timeout=10)
        return r.status_code == 200 and isinstance(r.json(), list)
    except requests.RequestException:
        return False


def atender_comando(estado, texto):
    """Ejecuta un comando y devuelve la respuesta (texto) para el chat."""
    partes = texto.split()
    cmd = partes[0].lower().lstrip('/')
    arg = partes[1].upper() if len(partes) > 1 else ''
    if cmd in ('start', 'ayuda', 'help'):
        return AYUDA
    if cmd in ('lista', 'list', 'estado'):
        lineas = []
        for s in estado['watchlist']:
            m = estado['simbolos'].get(s, {})
            p = m.get('ultimo_precio')
            lineas.append(f"  {s}" + (f" — último {p:.2f}" if p else " — sin escanear aún"))
        return "Vigilando:\n" + '\n'.join(lineas)
    if cmd in ('agrega', 'add') and arg:
        if arg in estado['watchlist']:
            return f"{arg} ya está en la lista."
        if not _simbolo_valido(arg):
            return f"{arg} no existe en futuros USDT-M de Binance."
        estado['watchlist'].append(arg)
        return f"{arg} agregado. El primer análisis sale en el próximo ciclo."
    if cmd in ('quita', 'remove', 'quitar') and arg:
        if arg not in estado['watchlist']:
            return f"{arg} no estaba en la lista."
        estado['watchlist'].remove(arg)
        estado['simbolos'].pop(arg, None)
        return f"{arg} eliminado de la vigilancia."
    if cmd in ('analiza', 'analizar', 'analisis') or (cmd.endswith('USDT'.lower()) and not arg):
        sym = arg or cmd.upper()
        if not _simbolo_valido(sym):
            return f"{sym} no existe en futuros USDT-M de Binance."
        mdt_telegram.enviar(estado['chat_id'], f"Analizando {sym}... (1-3 min)")
        try:
            resultado = escanear_mapa(verbose=False, symbol=sym)
            return resumen_analisis(sym, resultado)
        except Exception as e:  # noqa: BLE001 — se reporta al operador
            log.exception("analiza %s", sym)
            return f"Error analizando {sym}: {e}"
    return "No entendí. " + AYUDA


def procesar_comandos(estado, timeout=20):
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


# ---------------------------------------------------------------------------
# Bucle principal
# ---------------------------------------------------------------------------
def una_pasada(estado):
    for sym in list(estado['watchlist']):
        mem = estado['simbolos'].setdefault(sym, {})
        resultado = escanear_mapa(verbose=False, symbol=sym)
        for ev in detectar_eventos(sym, resultado, mem):
            mdt_telegram.enviar(estado.get('chat_id'), ev)
    guardar_estado(estado)


def main():
    ap = argparse.ArgumentParser(description="Bot MDT en vivo (escaneo + Telegram)")
    ap.add_argument("--una-pasada", action="store_true",
                    help="un solo escaneo de la watchlist y salir (prueba local)")
    args = ap.parse_args()

    estado = cargar_estado()
    log.info("watchlist %s | intervalo %ss | estado en %s",
             estado['watchlist'], INTERVALO, RUTA_ESTADO)
    if args.una_pasada:
        una_pasada(estado)
        return
    if not mdt_telegram.TOKEN:
        log.warning("MDT_TG_TOKEN vacío: los mensajes saldrán solo al log. "
                    "Crear el bot en @BotFather y ponerlo en /opt/mdt_bot/.env")

    while True:
        inicio = time.time()
        for sym in list(estado['watchlist']):
            mem = estado['simbolos'].setdefault(sym, {})
            try:
                resultado = escanear_mapa(verbose=False, symbol=sym)
                for ev in detectar_eventos(sym, resultado, mem):
                    log.info("evento %s: %s", sym, ev.splitlines()[0])
                    mdt_telegram.enviar(estado['chat_id'], ev)
            except Exception:  # noqa: BLE001 — el bucle jamás muere por un símbolo
                log.exception("escaneo %s falló; se reintenta en el próximo ciclo", sym)
            guardar_estado(estado)
        # ventana de comandos hasta el próximo escaneo (long-poll de Telegram)
        while time.time() - inicio < INTERVALO:
            if mdt_telegram.TOKEN:
                procesar_comandos(estado)
            else:
                time.sleep(30)
        guardar_estado(estado)


if __name__ == "__main__":
    main()
