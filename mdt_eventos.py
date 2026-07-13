# -*- coding: utf-8 -*-
"""Detección de EVENTOS: qué cambió entre el escaneo anterior y el actual.

Todo lo que el bot notifica nace aquí. El principio es la DEDUPLICACIÓN por
firma: un mismo hecho se avisa UNA vez, aunque el escaneo lo siga viendo cada 5
minutos. En la primera pasada de un símbolo solo se registra (baseline) — si no,
el bot soltaría de golpe todo el historial vivo.

Qué se notifica (filtros MDT_NOTIF_* en el .env, sin tocar código):
  1. ACTIVACIÓN 38.2 de un ciclo      (apagado por defecto)
  2. LLEGADA del precio a una zona    (apagado por defecto)
  3. PATRÓN                           (por defecto: solo los DE OPERACIÓN)
  4. DUELO entre tramos               (siempre)
  5. OPERACIONES REALES               (siempre — son hechos, ver mdt_ops)
  6. ANCLAS del operador              (siempre — las marcó él)
"""
import logging
import os

import pandas as pd

from mdt_config import ZONA_MAX_OPERABLE_PCT
from mdt_operacion import ESTADOS_OPERABLES
from mdt_estado import INTERVALO, naive, podar_firmas
from mdt_formato import hora_cot, resumen_analisis, texto_escaneo
from mdt_ops import actualizar_operaciones, texto_operaciones

log = logging.getLogger('mdt.eventos')

# Hitos no-operables que sí son noticia (patrón muerto, carencia viva...)
ESTADOS_HITO = ("ANULADO_POR_CARENCIA", "ROTO_POR_DOBLE_TOQUE", "ROTO_POR_STOP_LOSS",
                "P3_CORTA_ROTA", "ROTO_POR_RETESTEO_DILATACION", "ZONA_AGOTADA")

# "Engaño Profundo" (nombre del usuario) = Entrada Profunda (Secc 16) + Engaño
# Extremo (Secc 17): el barrido que profundiza o se sale de la zona y se devuelve.
ESTADOS_PROFUNDO = ("ENTRADA_PROFUNDA_ESPERANDO", "P3_CORTA_GATILLO",
                    "EE_ARMADO", "EE_GATILLO")

NOTIF_ACTIVACION = os.environ.get('MDT_NOTIF_ACTIVACION', '0') == '1'
NOTIF_ZONA = os.environ.get('MDT_NOTIF_ZONA', '0') == '1'
# operacion (defecto) | profundo | operables | todos
NOTIF_PATRON = os.environ.get('MDT_NOTIF_PATRON', 'operacion').lower()
# 'barrido' -> solo patrones nacidos de una llegada BARRIDO (la mechita)
NOTIF_LLEGADA = os.environ.get('MDT_NOTIF_LLEGADA', '').lower()

FMT_ESTADO = 5  # versión de la firma; al cambiarla el símbolo se re-basa sin ráfaga


def _clave_zona(lado, nombre, ancla):
    banda = nombre.rsplit('(', 1)[-1].rstrip(')') if '(' in nombre else '?'
    return f"{lado}|{banda}|{ancla:.2f}"


def _interesa_patron(e, estado):
    """¿Este patrón se notifica, según los filtros del .env?"""
    if NOTIF_PATRON == 'operacion':
        # Patrón DE OPERACIÓN formado: trae entrada/SL/TP ya calculados
        interesa = e.get('operacion') is not None
    elif NOTIF_PATRON == 'profundo':
        interesa = estado in ESTADOS_PROFUNDO
    elif NOTIF_PATRON == 'operables':
        interesa = estado in ESTADOS_OPERABLES or estado in ESTADOS_HITO
    else:  # 'todos'
        interesa = True
    if interesa and NOTIF_LLEGADA == 'barrido':
        interesa = e['resultado'].get('detalles', {}).get('calidad_llegada') == 'BARRIDO'
    return interesa


def detectar_eventos(sym, resultado, mem):
    """Compara el escaneo con la memoria del símbolo, devuelve los mensajes
    nuevos y actualiza `mem` in place."""
    mapa = resultado['mapa']
    precio = mapa['precio']
    baseline = not mem.get('baseline') or mem.get('fmt') != FMT_ESTADO
    eventos = []
    ahora = pd.Timestamp.now(tz='UTC').tz_localize(None)
    vivas = {'activados': set(), 'en_zona': set(), 'patron': set(), 'duelos': set()}

    # 1) Activaciones 38.2 (el ciclo pasa de alerta a activado: nacen sus zonas)
    act = mem.setdefault('activados', {})
    for c in mapa['ciclos']:
        ev = c.get('eval') or {}
        if ev.get('estado') != 'VIVO':
            continue
        k = f"{c['direction']}|{c['ancla']:.2f}"
        vivas['activados'].add(k)
        activado = bool(ev.get('activado'))
        previo = act.get(k)
        if not baseline and NOTIF_ACTIVACION and activado and previo is False:
            eventos.append(f"🔔 {sym} | CICLO ACTIVADO (tocó su 38.2): {c['nombre']} "
                           f"({c['tf']}, ancla {c['ancla']:.2f}) "
                           f"{hora_cot(ev.get('hora_activacion'))}\n"
                           "Sus zonas de trabajo quedan operativas.")
        elif not baseline and NOTIF_ACTIVACION and activado and previo is None:
            # Ciclo nuevo que nació ya activado: solo avisar si es reciente
            h = ev.get('hora_activacion')
            if h is not None and (ahora - naive(h)) < pd.Timedelta(seconds=4 * INTERVALO):
                eventos.append(f"🔔 {sym} | CICLO NUEVO ACTIVADO: {c['nombre']} "
                               f"({c['tf']}, ancla {c['ancla']:.2f}) {hora_cot(h)}")
        act[k] = activado

    # 2) Llegada del precio a una zona operativa (las macro son contexto: no avisan)
    en_zona = mem.setdefault('en_zona', {})
    for lado, zonas in (("SELL", mapa['sells']), ("BUY", mapa['buys'])):
        for z in zonas:
            if not z.get('z') or z.get('ancla') is None:
                continue
            zmax, zmin = max(z['z']), min(z['z'])
            if (zmax - zmin) > precio * ZONA_MAX_OPERABLE_PCT:
                continue
            k = _clave_zona(lado, z['name'], z['ancla'])
            vivas['en_zona'].add(k)
            dentro = bool(zmin <= precio <= zmax)   # bool nativo: np.bool_ no es JSON
            if not baseline and NOTIF_ZONA and dentro and not en_zona.get(k):
                accion = 'VENTAS' if lado == 'SELL' else 'COMPRAS'
                eventos.append(f"📍 {sym} | PRECIO EN ZONA DE {accion}: {z['name']} "
                               f"{zmax:.2f}-{zmin:.2f} (ancla {z['ancla']:.2f}, "
                               f"ciclo {z.get('tf', '?')}) | precio {precio:.2f}\n"
                               "A vigilar formación de patrón (3 Pautas).")
            en_zona[k] = dentro

    # 3) Patrones. Firma = el ESTADO (no la hora del gatillo: esa cambia al
    # re-medirse la zona vela a vela y hacía re-notificar el mismo engaño).
    patron = mem.setdefault('patron', {})
    for e in resultado['escaneos']:
        if e['contexto']:
            continue
        estado_p = e['resultado']['estado']
        k = _clave_zona(e['lado'], e['zona'], e['ancla'])
        vivas['patron'].add(k)
        if not baseline and _interesa_patron(e, estado_p) and estado_p != patron.get(k):
            if estado_p in ESTADOS_HITO:
                eventos.append(f"💀 {sym} | HITO: {texto_escaneo(e)}")
            elif estado_p in ESTADOS_PROFUNDO:
                eventos.append(f"🎯 {sym} | ENGAÑO PROFUNDO: {texto_escaneo(e)}")
            else:
                eventos.append(f"🎯 {sym} | SEÑAL: {texto_escaneo(e)}")
        patron[k] = estado_p

    # 4) Duelos entre tramos: zonas concurrentes de tramos DISTINTOS — gana la
    # calidad del patrón (dentro del tramo manda la concurrencia de zonas).
    duelos_mem = mem.setdefault('duelos', {})
    for g in resultado.get('duelos') or []:
        gana = g[0]
        k = f"{gana['lado']}|" + "|".join(sorted(f"{x['ancla']:.2f}" for x in g))
        vivas['duelos'].add(k)
        firma = f"{gana['zona']}|{gana['resultado']['estado']}"
        if not baseline and firma != duelos_mem.get(k):
            rivales = ", ".join(f"{x['zona']} [{x['tramo']}] ({x['resultado']['estado']})"
                                for x in g[1:])
            lleg = gana['resultado'].get('detalles', {}).get('calidad_llegada', '?')
            eventos.append(f"🥇 {sym} | DUELO DE PATRONES (zonas concurrentes entre tramos)\n"
                           f"GANA por calidad: {texto_escaneo(gana)}\n"
                           f"  llegada: {lleg}\n"
                           f"  pierde(n): {rivales}")
        duelos_mem[k] = firma

    podar_firmas(mem, {'activados': (vivas['activados'], act),
                       'en_zona': (vivas['en_zona'], en_zona),
                       'patron': (vivas['patron'], patron),
                       'duelos': (vivas['duelos'], duelos_mem)})

    mem['baseline'] = True
    mem['fmt'] = FMT_ESTADO
    mem['ultimo_escaneo'] = str(ahora)
    mem['ultimo_precio'] = float(precio)

    # 5) Operaciones reales (hechos: siempre se notifican)
    ev_ops = actualizar_operaciones(sym, resultado, mem)

    if baseline:
        msj = (f"👁 Vigilando {sym} (escaneo cada {INTERVALO // 60} min).\n\n"
               + resumen_analisis(sym, resultado))
        ops_txt = texto_operaciones(sym, mem)
        if ops_txt:
            msj += "\n\n" + ops_txt
        return [msj]
    return eventos + ev_ops


def vigilar_anclas(estado):
    """Anclas marcadas por el OPERADOR (regla usuario 13 jul): re-mapea cada
    tramo en cada escaneo — el extremo se mueve con el precio — y avisa cuando el
    precio ENTRA en una de sus zonas operativas. Un aviso por entrada."""
    from mdt_macro_mapper import analizar_ancla
    eventos = []
    for clave, v in list((estado.get('anclas') or {}).items()):
        try:
            a = analizar_ancla(v['ancla'], symbol=v['symbol'], direction=v['direction'])
        except Exception:  # noqa: BLE001 — un ancla rota no tumba el bucle
            log.exception("vigilancia del ancla %s", clave)
            continue
        if a is None:
            continue
        precio = a['precio']
        vistas = v.setdefault('zonas_vistas', {})
        activas = set()
        for lado, z in a['zonas']:
            if not z.get('z') or z.get('ancla') is None:
                continue
            zmax, zmin = max(z['z']), min(z['z'])
            k = f"{lado}|{z['name']}|{z['ancla']:.2f}"
            activas.add(k)
            dentro = bool(zmin <= precio <= zmax)
            if dentro and not vistas.get(k):
                accion = 'VENTAS' if lado == 'SELL' else 'COMPRAS'
                eventos.append(
                    f"⚓🎯 {v['symbol']} | PRECIO EN ZONA DEL ANCLA {a['ancla']:.2f}\n"
                    f"{z['name']}: {zmax:.2f}-{zmin:.2f} ({accion})\n"
                    f"  precio {precio:.2f} | ciclo {z.get('tf', '?')} "
                    f"(ancla {z['ancla']:.2f})\n"
                    f"  tramo: {a['ancla']:.2f} → {a['extremo']:.2f}\n"
                    "  A vigilar formación de patrón (3 Pautas).")
            vistas[k] = dentro
        for k in list(vistas):          # zonas que ya no existen en el tramo
            if k not in activas:
                vistas.pop(k)
    return eventos
