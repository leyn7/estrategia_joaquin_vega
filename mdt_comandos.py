# -*- coding: utf-8 -*-
"""Comandos que el operador manda al bot por Telegram.

Solo el chat autorizado manda (el primero que escriba queda vinculado, salvo que
MDT_TG_CHAT lo fije). Los comandos que tardan (analiza, tramos, ancla) avisan
antes de ponerse a trabajar: el escaneo completo puede tomar minutos.
"""
import logging

import pandas as pd
import requests

import mdt_telegram
from mdt_config import SYMBOL, TZ_LOCAL
from mdt_escaner import escanear_ancla, escanear_completo
from mdt_estructura import TF_BUSQUEDA
from mdt_estado import guardar_estado
from mdt_formato import resumen_analisis, texto_rsi3m, texto_zonas_ancla
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
         "     Forzarlo:  ancla 560.58 alcista\n"
         "     Mecha fina: ancla 578.81 1m   (TF solo para BUSCAR el punto;\n"
         "       el análisis sigue siendo fractal. 1m 3m 15m 30m 1h 2h 4h 1d)\n"
         "     Nivel repetido: ancla 560.58 08/07   (fecha en tu horario)\n"
         "  anclas — las anclas que estoy vigilando\n"
         "  borra ancla PRECIO — dejar de vigilarla\n"
         "\n📈 RSI_3M BAJO DEMANDA (solo cuando tú lo digas):\n"
         "  rsi3m PRECIO [compras|ventas] [SYM] [TF] [FECHA]\n"
         "     'a partir de este mínimo/máximo, opérame con rsi_3m'.\n"
         "     Estrategia PURA: sin filtros, TP 1:10. Te aviso de cada señal.\n"
         "     Sin decir nada opera los DOS lados (la dirección la marca el RSI).\n"
         "     Acotarlo:  rsi3m 562.52 compras\n"
         "  borra rsi3m PRECIO — dejar de aplicarla\n"
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


def _fecha_ancla(tok):
    """Fecha del ancla EN HORA DEL OPERADOR (COT). Acepta 08/07, 8-7, 2026-07-08.
    Sin año, el del día de hoy (o el anterior si la fecha aún no ha llegado)."""
    t = tok.replace('-', '/').replace('.', '/')
    trozos = [x for x in t.split('/') if x]
    if not all(x.isdigit() for x in trozos):
        return None
    hoy = pd.Timestamp.now(tz=TZ_LOCAL).tz_localize(None).normalize()
    try:
        if len(trozos) == 3 and len(trozos[0]) == 4:      # 2026/07/08
            f = pd.Timestamp(int(trozos[0]), int(trozos[1]), int(trozos[2]))
        elif len(trozos) == 3:                            # 08/07/2026
            f = pd.Timestamp(int(trozos[2]), int(trozos[1]), int(trozos[0]))
        elif len(trozos) == 2:                            # 08/07 -> año en curso
            f = pd.Timestamp(hoy.year, int(trozos[1]), int(trozos[0]))
            if f > hoy:
                f = pd.Timestamp(hoy.year - 1, int(trozos[1]), int(trozos[0]))
        else:
            return None
    except ValueError:
        return None
    return f


def _cmd_ancla(estado, partes):
    """ancla PRECIO [SYM] [alcista|bajista] [TF] [FECHA] — mapea ese tramo y lo vigila.

    TF y FECHA solo acotan DÓNDE se busca el punto del ancla (regla usuario 13
    jul): una mecha fina no existe en 30m, y un nivel tocado varias veces es
    ambiguo. El análisis que sale de ahí sigue siendo fractal.
    """
    try:
        precio_a = float(partes[1].replace(',', '.'))
    except ValueError:
        return "Uso: ancla 560.58 [SYM] [alcista|bajista] [TF] [FECHA]"
    resto = [p.lower() for p in partes[2:]]
    sym = next((p.upper() for p in partes[2:] if p.upper().endswith('USDT')), SYMBOL)
    direccion = ("BULLISH" if 'alcista' in resto else
                 "BEARISH" if 'bajista' in resto else None)
    tf_b = next((p for p in resto if p in TF_BUSQUEDA), "30m")
    fecha = next((f for f in (_fecha_ancla(p) for p in resto) if f is not None), None)

    aviso = f"⚓ Mapeando el tramo desde {precio_a:.2f} (busco en {tf_b}"
    aviso += f", día {fecha.strftime('%d/%m')})..." if fecha is not None else ")..."
    mdt_telegram.enviar(estado['chat_id'], aviso + " (1-3 min)")
    try:
        from mdt_macro_mapper import analizar_ancla, reporte_ancla
        a = analizar_ancla(precio_a, symbol=sym, direction=direccion,
                           tf_busqueda=tf_b, fecha=fecha)
        if a is None:
            return (f"No pude ubicar el ancla {precio_a:.2f} en el gráfico de {sym}"
                    + (f" el {fecha.strftime('%d/%m')} (¿otra fecha?)." if fecha is not None
                       else f" buscando en {tf_b}."))
        estado.setdefault('anclas', {})[f"{sym}|{a['ancla']:.2f}"] = {
            'symbol': sym, 'ancla': a['ancla'], 'direction': a['direction'],
            'zonas_vistas': {},
        }
        guardar_estado(estado)
        # El mapa dice DÓNDE están las zonas; el escáner, QUÉ pasó dentro de ellas
        # (regla usuario 13 jul: "el precio hizo un engaño profundo y no me lo dijo")
        escaneos = escanear_ancla(a, symbol=sym)
        return (reporte_ancla(a) + texto_zonas_ancla(escaneos, a['precio'])
                + "\n\n👁 VIGILANDO este tramo: te aviso cuando el precio entre en "
                  "una de sus zonas operativas.")
    except Exception as e:  # noqa: BLE001 — se le reporta al operador
        log.exception("ancla %s", precio_a)
        return f"Error mapeando el ancla: {e}"


def _cmd_rsi3m(estado, partes):
    """rsi3m PRECIO [SYM] [TF] [FECHA] — "a partir de este mínimo/máximo, opérame
    con rsi_3m" (regla usuario 13 jul).

    Estrategia PURA: largos y cortos, SIN la condición de no romper el techo/piso
    y SIN filtros (ni banda de 1h, ni EMA, ni sesgo). El contexto lo pone él: por
    eso solo corre cuando él lo pide. El bot automático bot_rsi5m sigue con sus
    filtros por su lado, intacto.
    """
    try:
        precio_a = float(partes[0].replace(',', '.'))
    except (ValueError, IndexError):
        return "Uso: rsi3m 560.58 [SYM] [TF] [FECHA]"
    resto = [p.lower() for p in partes[1:]]
    sym = next((p.upper() for p in partes[1:] if p.upper().endswith('USDT')), SYMBOL)
    tf_b = next((p for p in resto if p in TF_BUSQUEDA), "30m")
    fecha = next((f for f in (_fecha_ancla(p) for p in resto) if f is not None), None)
    # Qué lado operar. Por defecto los dos: la dirección la marca el RSI, no el
    # ancla (él puede marcar un mínimo y que el RSI arme una venta). Si él lo
    # acota, manda él: "rsi3m 562.52 compras".
    solo_compras = any(p in ('compras', 'compra', 'largos', 'long') for p in resto)
    solo_ventas = any(p in ('ventas', 'venta', 'cortos', 'short') for p in resto)
    lados = (("long",) if solo_compras and not solo_ventas else
             ("short",) if solo_ventas and not solo_compras else ("long", "short"))

    lados_txt = ("solo COMPRAS" if lados == ("long",) else
                 "solo VENTAS" if lados == ("short",) else "compras y ventas")
    mdt_telegram.enviar(estado['chat_id'],
                        f"📈 Aplicando rsi_3m desde {precio_a:.2f} ({lados_txt})...")
    try:
        from mdt_estructura import localizar_ancla
        from mdt_rsi3m import desde_ancla
        loc = localizar_ancla(precio_a, symbol=sym, tf=tf_b, fecha=fecha)
        if loc is None:
            return f"No pude ubicar {precio_a:.2f} en el gráfico de {sym}."
        t_ancla, _dir, precio_real, _alt = loc
        trades, descartadas, _ = desde_ancla(precio_real, t_ancla, symbol=sym, lados=lados)

        estado.setdefault('rsi3m', {})[f"{sym}|{precio_real:.2f}"] = {
            'symbol': sym, 'ancla': precio_real, 'ancla_time': str(t_ancla),
            'lados': list(lados),
            'senales_vistas': [f"{t['side']}|{str(t['dt'])[:16]}" for t in trades],
        }
        guardar_estado(estado)
        return texto_rsi3m(sym, precio_real, t_ancla, trades, descartadas, lados_txt)
    except Exception as e:  # noqa: BLE001 — se le reporta al operador
        log.exception("rsi3m %s", precio_a)
        return f"Error aplicando rsi_3m: {e}"


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

    # rsi_3m bajo demanda. Se acepta pegado tal cual él lo escribe:
    #   "rsi3m 560.58"  |  "aplica entradas rsi3m 560.58"
    if cmd in ('rsi3m', 'rsi_3m', 'rsi') and len(partes) > 1:
        return _cmd_rsi3m(estado, partes[1:])
    if cmd == 'aplica' and len(partes) > 3 and partes[2].lower().replace('_', '') == 'rsi3m':
        return _cmd_rsi3m(estado, partes[3:])
    if cmd == 'rsi3m' or (cmd == 'aplica' and len(partes) <= 3):
        return ("Uso: rsi3m 560.58 [SYM] [TF] [FECHA]\n"
                "  o: aplica entradas rsi3m 560.58\n"
                "Aplica la rsi_3m PURA (largos y cortos, sin filtros, TP 1:10) "
                "desde ese mínimo/máximo, y te avisa de cada señal nueva.")
    if cmd == 'rsi3m_off' or (cmd == 'borra' and len(partes) > 2
                              and partes[1].lower() in ('rsi3m', 'rsi_3m')):
        r = estado.setdefault('rsi3m', {})
        try:
            p = float(partes[2].replace(',', '.'))
        except (ValueError, IndexError):
            return "Uso: borra rsi3m 560.58"
        fuera = [k for k in r if abs(r[k]['ancla'] - p) < 0.01]
        for k in fuera:
            r.pop(k)
        guardar_estado(estado)
        return (f"🗑 rsi_3m del ancla {p:.2f} desactivada." if fuera
                else f"No estaba aplicando rsi_3m en {p:.2f}.")
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
