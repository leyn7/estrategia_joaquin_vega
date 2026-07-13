# -*- coding: utf-8 -*-
"""Formato de los mensajes que el bot manda a Telegram (horas en COT).

Solo presentación: aquí no hay lógica de estrategia ni decisiones — se limita a
convertir los resultados del escáner en texto legible para el operador.
"""
from mdt_config import RATIO_MINIMO
from mdt_data import to_cot
from mdt_escaner import ESTADOS_OPERABLES


def hora_cot(ts):
    if ts is None:
        return ''
    try:
        return to_cot(ts).strftime('%d %b %H:%M COT')
    except Exception:  # noqa: BLE001 — formatear nunca debe tumbar el bot
        return str(ts)


def texto_operacion(op):
    """Las 4 Informaciones de una señal accionable (entrada, SL, TP, ratio)."""
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


def texto_escaneo(e):
    """Un patrón con su ciclo (origen → fin), su zona y, si es accionable, la
    operación completa."""
    res = e['resultado']
    d = res.get('detalles', {})
    hora = hora_cot(d.get('hora_gatillo') or d.get('hora_validacion'))
    tramo_txt = f" [tramo {e['tramo']}]" if e.get('tramo') else ""
    if e.get('ciclo_origen') is not None and e.get('ciclo_fin') is not None:
        ciclo_txt = (f"  CICLO: {e['ciclo_origen']:.2f} → {e['ciclo_fin']:.2f} "
                     f"(ancla {e['ancla']:.2f}, {e['tf_ciclo']}) | patrón {e['tf_patron']}")
    else:
        ciclo_txt = f"  ciclo {e['tf_ciclo']} (ancla {e['ancla']:.2f}) -> patrón {e['tf_patron']}"
    txt = (f"{res['estado']} en {e['zona']} {e['rango'][0]:.2f}-{e['rango'][1]:.2f}{tramo_txt}\n"
           f"{ciclo_txt}\n"
           f"  {res['mensaje']}")
    lleg = d.get('calidad_llegada')
    if lleg == "BARRIDO":
        txt += (f"\n  ⚡ LLEGADA BARRIDO: tocó y salió (mecha {d.get('mecha_vs_cuerpo')}x "
                f"el cuerpo, {d.get('velas_visita')} vela(s), 0 cierres dentro)")
    elif lleg == "LENTA":
        txt += f"\n  🐌 llegada lenta (camping): {d.get('cierres_dentro')} cierres dentro"
    if hora:
        txt += f"\n  hora: {hora}"
    return txt + texto_operacion(e.get('operacion'))


def resumen_analisis(sym, resultado):
    """Resumen compacto de un escaneo completo (arranque y comando 'analiza')."""
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
        lineas += [texto_escaneo(e) for e in accionables]
    else:
        lineas.append("Sin señales operables ahora.")
    return '\n'.join(lineas)
