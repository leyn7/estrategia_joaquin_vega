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
from mdt_config import SYMBOL, RATIO_MINIMO, PARCIAL_R, ZONA_MAX_OPERABLE_PCT
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
from mdt_escaner import escanear_mapa, escanear_tramos, ESTADOS_OPERABLES  # noqa: E402

# Hitos no-operables que sí se notifican (elección del usuario: operables + hitos)
ESTADOS_HITO = ("ANULADO_POR_CARENCIA", "ROTO_POR_DOBLE_TOQUE", "ROTO_POR_STOP_LOSS",
                "P3_CORTA_ROTA", "ROTO_POR_RETESTEO_DILATACION", "ZONA_AGOTADA")

# Engaño Profundo (nombre del usuario) = Entrada Profunda (Secc 16) + Engaño
# Extremo (Secc 17): el barrido que profundiza/se sale de la zona y se devuelve.
ESTADOS_PROFUNDO = ("ENTRADA_PROFUNDA_ESPERANDO", "P3_CORTA_GATILLO",
                    "EE_ARMADO", "EE_GATILLO")

# Qué notificar (regla usuario 8 jul 2026): por defecto SOLO el Engaño Profundo
# con su ancla. Ajustable por .env sin tocar código:
#   MDT_NOTIF_ACTIVACION=1  -> también avisa activaciones del 38.2
#   MDT_NOTIF_ZONA=1        -> también avisa llegadas del precio a una zona
#   MDT_NOTIF_PATRON=operables|todos  -> amplía más allá del engaño profundo
NOTIF_ACTIVACION = os.environ.get('MDT_NOTIF_ACTIVACION', '0') == '1'
NOTIF_ZONA = os.environ.get('MDT_NOTIF_ZONA', '0') == '1'
NOTIF_PATRON = os.environ.get('MDT_NOTIF_PATRON', 'profundo').lower()
# MDT_NOTIF_LLEGADA=barrido -> solo notifica patrones nacidos de una llegada
# BARRIDO (la mechita: toca y sale). Vacío = notifica todas (marcadas).
NOTIF_LLEGADA = os.environ.get('MDT_NOTIF_LLEGADA', '').lower()
FMT_ESTADO = 5  # versión del formato de firma; un cambio re-basa sin ráfaga


def escanear_completo(sym, cutoff=None):
    """Escaneo global + escaneo por tramos, fusionados para el detector de
    eventos: las zonas que solo existen en la vista por tramos (las que la
    concurrencia global absorbió — caso Alta del M5) entran etiquetadas con su
    tramo; las compartidas no se duplican (manda la global). Los duelos entre
    tramos (regla usuario 12 jul) viajan en resultado['duelos']."""
    resultado = escanear_mapa(cutoff=cutoff, verbose=False, symbol=sym)
    tr = escanear_tramos(cutoff=cutoff, mapa=resultado['mapa'], verbose=False, symbol=sym)
    vistos = {(e['lado'], round(e['ancla'], 2), e['rango']) for e in resultado['escaneos']
              if e.get('ancla') is not None}
    extras = [e for e in tr['escaneos']
              if (e['lado'], round(e['ancla'], 2), e['rango']) not in vistos]
    resultado['escaneos'] = resultado['escaneos'] + extras
    resultado['duelos'] = tr['duelos']
    return resultado

# Gatillos EJECUTADOS = entrada a mercado real. Se persisten como OPERACIONES
# (hechos): la cadena de patrones es sin-estado y al re-parsear con velas
# nuevas puede borrar del historial un gatillo que SÍ disparó (caso real: el
# EE_GATILLO venta 590.28/SL 593.83 del 5 jul desapareció el 8 jul cuando la
# Entrada Profunda re-leyó el episodio). La operación registrada conserva sus
# datos reales (entrada/SL/TP originales) y se sigue con velas, pase lo que
# pase con el re-parseo. Sobrevive reinicios (estado_vivo.json).
ESTADOS_EJECUTADOS = ("GATILLO_ACTIVADO", "P3_CORTA_GATILLO",
                      "DT_IMPULSO_GATILLO", "EE_GATILLO")


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
    txt = (f"\n  Entrada {op['entrada']:.2f} | SL {op['stop_loss']:.2f} "
           f"(riesgo {op['riesgo']:.2f})"
           f"\n  TP zona {op['tp_zona'][0]:.2f}-{op['tp_zona'][1]:.2f}"
           f"\n  R:B 1:{op['ratio']:.1f} [{ver}] | {op['movimiento']}"
           f"\n  Volumen: {op['volumen']}")
    if op.get('aviso'):
        txt += f"\n  ⚠ {op['aviso']}"
    return txt


def _texto_escaneo(e):
    res = e['resultado']
    d = res.get('detalles', {})
    hora = _hora_cot(d.get('hora_gatillo') or d.get('hora_validacion'))
    tramo_txt = f" [tramo {e['tramo']}]" if e.get('tramo') else ""
    txt = (f"{res['estado']} en {e['zona']} {e['rango'][0]:.2f}-{e['rango'][1]:.2f}{tramo_txt}\n"
           f"  ciclo {e['tf_ciclo']} (ancla {e['ancla']:.2f}) -> patrón {e['tf_patron']}\n"
           f"  {res['mensaje']}")
    lleg = d.get('calidad_llegada')
    if lleg == "BARRIDO":
        txt += (f"\n  ⚡ LLEGADA BARRIDO: tocó y salió (mecha {d.get('mecha_vs_cuerpo')}x "
                f"el cuerpo, {d.get('velas_visita')} vela(s), 0 cierres dentro)")
    elif lleg == "LENTA":
        txt += f"\n  🐌 llegada lenta (camping): {d.get('cierres_dentro')} cierres dentro"
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
# Operaciones reales (gatillos ejecutados persistidos + gestión Secc 20)
# ---------------------------------------------------------------------------
def _op_de_escaneo(e):
    """Extrae los HECHOS de un gatillo ejecutado (o None): entrada, SL original,
    TP del ciclo y hora — lo que el operador necesita aunque el re-parseo de la
    cadena luego pierda este trabajo."""
    res = e['resultado']
    if res['estado'] not in ESTADOS_EJECUTADOS:
        return None
    d = res.get('detalles', {})
    hora = d.get('hora_gatillo')
    entrada = (d.get('gatillo_agresivo') or d.get('entrada_p3_corta')
               or d.get('entrada_dt_618'))
    if entrada is None and res['estado'].startswith('EE_'):
        entrada = e['rango'][0] if e['lado'] == 'SELL' else e['rango'][1]
    sl = d.get('stop_loss', d.get('extremo_escape'))
    tp = e.get('tp_zona')
    if hora is None or entrada is None or sl is None or tp is None:
        return None
    return {'zona': e['zona'], 'lado': e['lado'], 'patron': res['estado'],
            'tf': e['tf_patron'], 'ancla': float(e['ancla']),
            'entrada': round(float(entrada), 4), 'sl': round(float(sl), 4),
            'tp_zona': [round(float(max(tp)), 4), round(float(min(tp)), 4)],
            'hora_gatillo': str(_naive(hora))}


def _seguir_operacion(sym, op):
    """Sigue la operación con velas reales desde su gatillo (gestión Secc 20).

    Determinista desde los hechos persistidos: SL tocado -> SL (-1R). Si el
    objetivo supera 1:3, parcial OBLIGATORIO a la mitad del objetivo (mín 1:2):
    mitad fuera + stop a BREAKEVEN; luego breakeven cierra el resto en lo
    asegurado y el TP completa. Conservador vela a vela (el lado malo primero).
    """
    lado, entrada, sl = op['lado'], op['entrada'], op['sl']
    riesgo = abs(sl - entrada)
    if riesgo <= 0:
        return None
    tp = max(op['tp_zona']) if lado == 'SELL' else min(op['tp_zona'])
    ratio = abs(entrada - tp) / riesgo
    signo = -1.0 if lado == 'SELL' else 1.0
    nivel_parcial = None
    ratio_parcial = 0.0
    if ratio > RATIO_MINIMO:
        ratio_parcial = max(PARCIAL_R, ratio / 2.0)
        nivel_parcial = entrada + signo * ratio_parcial * riesgo
    hora = pd.Timestamp(op['hora_gatillo'])
    df = get_klines_vivo(sym, op['tf'], hora.tz_localize('UTC'))
    velas = df[df['open_time'] > hora]
    base = {'ratio': ratio, 'nivel_parcial': nivel_parcial, 'tp': tp}
    fase, r_aseg = 'ABIERTA', 0.0
    for v in velas.itertuples():
        if fase == 'ABIERTA':
            if (v.high >= sl) if lado == 'SELL' else (v.low <= sl):
                return {**base, 'fase': 'SL', 'r': -1.0, 'sl_actual': sl}
            if nivel_parcial is not None and \
                    ((v.low <= nivel_parcial) if lado == 'SELL' else (v.high >= nivel_parcial)):
                fase, r_aseg = 'PARCIAL', 0.5 * ratio_parcial
            elif nivel_parcial is None and \
                    ((v.low <= tp) if lado == 'SELL' else (v.high >= tp)):
                return {**base, 'fase': 'TP', 'r': ratio, 'sl_actual': sl}
        else:
            if (v.high >= entrada) if lado == 'SELL' else (v.low <= entrada):
                return {**base, 'fase': 'BE', 'r': r_aseg, 'sl_actual': entrada}
            if (v.low <= tp) if lado == 'SELL' else (v.high >= tp):
                return {**base, 'fase': 'TP', 'r': r_aseg + 0.5 * ratio, 'sl_actual': entrada}
    ult = float(velas['close'].iloc[-1]) if len(velas) else entrada
    r_flot = ((entrada - ult) if lado == 'SELL' else (ult - entrada)) / riesgo
    if fase == 'PARCIAL':
        return {**base, 'fase': 'PARCIAL', 'r': r_aseg + 0.5 * r_flot,
                'r_asegurada': r_aseg, 'sl_actual': entrada, 'precio': ult}
    return {**base, 'fase': 'ABIERTA', 'r': r_flot, 'sl_actual': sl, 'precio': ult}


def _texto_op_real(op, s):
    """Línea de estado de una operación real (para resumen y alertas)."""
    accion = 'VENTA' if op['lado'] == 'SELL' else 'COMPRA'
    hora = _hora_cot(pd.Timestamp(op['hora_gatillo']))
    txt = (f"{accion} {op['entrada']:.2f} ({op['patron']}, {hora})\n"
           f"  zona: {op['zona']} | SL original {op['sl']:.2f} | "
           f"TP {op['tp_zona'][0]:.2f}-{op['tp_zona'][1]:.2f} (1:{s['ratio']:.1f})")
    if s['fase'] == 'PARCIAL':
        txt += (f"\n  PARCIAL HECHO en {s['nivel_parcial']:.2f} "
                f"(+{s.get('r_asegurada', 0):.2f}R asegurada) -> STOP EN BREAKEVEN "
                f"{s['sl_actual']:.2f} | flotante total {s['r']:+.2f}R")
    elif s['fase'] == 'ABIERTA':
        extra = (f" | parcial (Secc 20) en {s['nivel_parcial']:.2f}"
                 if s['nivel_parcial'] is not None else "")
        txt += f"\n  ABIERTA: SL {s['sl_actual']:.2f}{extra} | flotante {s['r']:+.2f}R"
    else:
        cierre = {'SL': 'STOP LOSS', 'BE': 'BREAKEVEN (tras parcial)', 'TP': 'TP COMPLETO'}
        txt += f"\n  CERRADA por {cierre.get(s['fase'], s['fase'])}: {s['r']:+.2f}R"
    return txt


def actualizar_operaciones(sym, resultado, mem):
    """Registra gatillos ejecutados nuevos y sigue los abiertos con velas reales.
    Devuelve eventos de transición (parcial/breakeven/SL/TP). Las operaciones
    son HECHOS: se notifican siempre, sin filtro de notificaciones."""
    ops = mem.setdefault('operaciones', {})
    eventos = []
    # 1) registrar gatillos ejecutados nuevos (dedup por lado|ancla|patron|entrada)
    for e in resultado['escaneos']:
        if e['contexto']:
            continue
        op = _op_de_escaneo(e)
        if op is None:
            continue
        k = f"{op['lado']}|{op['ancla']:.2f}|{op['patron']}|{op['entrada']:.2f}"
        if k not in ops:
            ops[k] = {**op, 'fase': None}
    # 2) seguir cada operación no cerrada
    for k, op in list(ops.items()):
        if op.get('fase') in ('SL', 'BE', 'TP'):
            continue
        try:
            s = _seguir_operacion(sym, op)
        except Exception:
            log.exception("seguimiento de operación %s", k)
            continue
        if s is None:
            ops.pop(k)
            continue
        previa = op.get('fase')
        if s['fase'] != previa:
            icono = {'PARCIAL': '💰', 'SL': '☠️', 'BE': '⚖️', 'TP': '🏁'}.get(s['fase'], '📌')
            titulo = {'PARCIAL': 'PARCIAL TOCADO -> STOP A BREAKEVEN (Secc 20)',
                      'SL': 'STOP LOSS: operación cerrada',
                      'BE': 'BREAKEVEN tocado: cerrada con lo asegurado',
                      'TP': 'TP COMPLETO'}.get(s['fase'], 'OPERACIÓN REGISTRADA')
            if previa is None and s['fase'] == 'ABIERTA':
                titulo = 'OPERACIÓN REGISTRADA (gatillo ejecutado)'
            eventos.append(f"{icono} {sym} | {titulo}\n{_texto_op_real(op, s)}")
        op['fase'] = s['fase']
        if s['fase'] in ('SL', 'BE', 'TP'):
            op['r_final'] = round(s['r'], 2)
    return eventos


def texto_operaciones(sym, mem):
    """Bloque 'OPERACIONES REALES' para el arranque y el comando operaciones."""
    ops = mem.get('operaciones') or {}
    vivas, cerradas = [], []
    for op in ops.values():
        if op.get('fase') in ('SL', 'BE', 'TP'):
            cerradas.append(op)
            continue
        try:
            s = _seguir_operacion(sym, op)
        except Exception:
            continue
        if s is not None:
            vivas.append(_texto_op_real(op, s))
    if not vivas and not cerradas:
        return ''
    lineas = [f"OPERACIONES REALES {sym}:"]
    lineas += vivas or ["  (ninguna abierta)"]
    if cerradas:
        lineas.append("Cerradas: " + ", ".join(
            f"{o['patron']} {o['entrada']:.2f} ({o.get('r_final', 0):+.2f}R)" for o in cerradas[-5:]))
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
    # baseline = primera pasada del símbolo (solo registra, no notifica). También
    # se re-basa si cambió el formato de firma, para no soltar una ráfaga del
    # historial vivo tras un cambio de reglas.
    baseline = not mem.get('baseline') or mem.get('fmt') != FMT_ESTADO
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
        if not baseline and NOTIF_ACTIVACION and activado and previo is False:
            eventos.append(f"🔔 {sym} | CICLO ACTIVADO (tocó su 38.2): {c['nombre']} "
                           f"({c['tf']}, ancla {c['ancla']:.2f}) "
                           f"{_hora_cot(ev.get('hora_activacion'))}\n"
                           "Sus zonas de trabajo quedan operativas.")
        elif not baseline and NOTIF_ACTIVACION and activado and previo is None:
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
            if not baseline and NOTIF_ZONA and dentro and not en_zona.get(k):
                accion = 'VENTAS' if lado == 'SELL' else 'COMPRAS'
                eventos.append(f"📍 {sym} | PRECIO EN ZONA DE {accion}: {z['name']} "
                               f"{zmax:.2f}-{zmin:.2f} (ancla {z['ancla']:.2f}, "
                               f"ciclo {z.get('tf', '?')}) | precio {precio:.2f}\n"
                               "A vigilar formación de patrón (3 Pautas).")
            en_zona[k] = dentro

    # 3) Cambios de patrón por zona. Por defecto SOLO Engaño Profundo (regla
    # usuario 8 jul). Firma ESTABLE: el nivel de entrada redondeado, NO la
    # hora_gatillo — esta última cambia cada vez que la zona se re-mide vela a
    # vela, y hacía re-notificar el mismo engaño una y otra vez.
    patron = mem.setdefault('patron', {})
    for e in resultado['escaneos']:
        if e['contexto']:
            continue
        res = e['resultado']
        estado = res['estado']
        if NOTIF_PATRON == 'profundo':
            interesa = estado in ESTADOS_PROFUNDO
        elif NOTIF_PATRON == 'operables':
            interesa = estado in ESTADOS_OPERABLES or estado in ESTADOS_HITO
        else:  # 'todos'
            interesa = True
        if interesa and NOTIF_LLEGADA == 'barrido':
            interesa = res.get('detalles', {}).get('calidad_llegada') == 'BARRIDO'
        # Firma = solo el estado. La zona (su ancla) ya está en la clave `k`, así
        # que un mismo Engaño Profundo se avisa UNA vez y no se repite aunque la
        # zona oscile su borde vela a vela; solo re-avisa si el patrón murió (otro
        # estado de por medio) y volvió a armarse.
        k = _clave_zona(e['lado'], e['zona'], e['ancla'])
        firma = estado
        if not baseline and interesa and firma != patron.get(k):
            if estado in ESTADOS_HITO:
                eventos.append(f"💀 {sym} | HITO: {_texto_escaneo(e)}")
            elif estado in ESTADOS_PROFUNDO:
                eventos.append(f"🎯 {sym} | ENGAÑO PROFUNDO: {_texto_escaneo(e)}")
            else:
                eventos.append(f"🎯 {sym} | SEÑAL: {_texto_escaneo(e)}")
        patron[k] = firma

    # 4) Duelos entre tramos (regla usuario 12 jul): patrones accionables de
    # tramos DISTINTOS cuyas zonas concurren — gana la calidad del patrón.
    duelos_mem = mem.setdefault('duelos', {})
    for g in resultado.get('duelos') or []:
        gana = g[0]
        k = f"{gana['lado']}|" + "|".join(sorted(f"{x['ancla']:.2f}" for x in g))
        d_g = gana['resultado'].get('detalles', {})
        firma_d = f"{gana['zona']}|{gana['resultado']['estado']}"
        if not baseline and firma_d != duelos_mem.get(k):
            rivales = ", ".join(f"{x['zona']} [{x['tramo']}] ({x['resultado']['estado']})"
                                for x in g[1:])
            eventos.append(f"🥇 {sym} | DUELO DE PATRONES (zonas concurrentes entre tramos)\n"
                           f"GANA por calidad: {_texto_escaneo(gana)}\n"
                           f"  llegada: {d_g.get('calidad_llegada', '?')}\n"
                           f"  pierde(n): {rivales}")
        duelos_mem[k] = firma_d

    mem['baseline'] = True
    mem['fmt'] = FMT_ESTADO
    mem['ultimo_escaneo'] = str(ahora)
    mem['ultimo_precio'] = float(precio)

    # 5) Operaciones reales: registro + gestión Secc 20 (sin filtro de notifs —
    # son los hechos del operador y sobreviven al re-parseo de la cadena)
    ev_ops = actualizar_operaciones(sym, resultado, mem)

    if baseline:
        msj = (f"👁 Vigilando {sym} (escaneo cada {INTERVALO // 60} min).\n\n"
               + resumen_analisis(sym, resultado))
        ops_txt = texto_operaciones(sym, mem)
        if ops_txt:
            msj += "\n\n" + ops_txt
        return [msj]
    return eventos + ev_ops


# ---------------------------------------------------------------------------
# Comandos de Telegram
# ---------------------------------------------------------------------------
AYUDA = ("Comandos:\n"
         "  lista — símbolos vigilados\n"
         "  agrega SYM — añade a la vigilancia (ej. agrega ETHUSDT)\n"
         "  quita SYM — deja de vigilar\n"
         "  analiza SYM — análisis completo puntual (1-3 min)\n"
         "  tramos SYM — mapa por tramos independientes (cada muñeca aparte, 1-3 min)\n"
         "  operaciones — operaciones reales registradas (SL/parcial/estado)\n"
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
    if cmd in ('operaciones', 'ops', 'operacion'):
        bloques = [texto_operaciones(s, estado['simbolos'].get(s, {}))
                   for s in estado['watchlist']]
        bloques = [b for b in bloques if b]
        return '\n\n'.join(bloques) if bloques else "Sin operaciones registradas aún."
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
    if cmd in ('tramos', 'tramo'):
        sym = arg or SYMBOL
        if not _simbolo_valido(sym):
            return f"{sym} no existe en futuros USDT-M de Binance."
        mdt_telegram.enviar(estado['chat_id'], f"Armando tramos de {sym}... (1-3 min)")
        try:
            from mdt_macro_mapper import generar_mapa, reporte_tramos
            mapa = generar_mapa(verbose=False, symbol=sym)
            return reporte_tramos(mapa)
        except Exception as e:  # noqa: BLE001 — se reporta al operador
            log.exception("tramos %s", sym)
            return f"Error armando tramos de {sym}: {e}"
    if cmd in ('analiza', 'analizar', 'analisis') or (cmd.endswith('USDT'.lower()) and not arg):
        sym = arg or cmd.upper()
        if not _simbolo_valido(sym):
            return f"{sym} no existe en futuros USDT-M de Binance."
        mdt_telegram.enviar(estado['chat_id'], f"Analizando {sym}... (1-3 min)")
        try:
            resultado = escanear_completo(sym)
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
        resultado = escanear_completo(sym)
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
                resultado = escanear_completo(sym)
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
