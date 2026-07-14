# -*- coding: utf-8 -*-
"""Formato de los mensajes que el bot manda a Telegram (horas en COT).

Solo presentación: aquí no hay lógica de estrategia ni decisiones — se limita a
convertir los resultados del escáner en texto legible para el operador.
"""
from mdt_config import RATIO_MINIMO
from mdt_data import to_cot
from mdt_operacion import ESTADOS_OPERABLES


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


def texto_zona_estrecha(e):
    """Aviso de zona demasiado pequeña para su temporalidad de patrón (el bot no
    puede ver estructura ahí dentro, aunque el precio la esté trabajando)."""
    if not e.get('estrecha'):
        return []
    ancho, vela, tf = e.get('ancho_zona'), e.get('vela_tf'), e['tf_patron']
    return [f"   ⚠ ZONA MUY PEQUEÑA PARA SU ESCALA: mide {ancho:.2f} y la vela típica "
            f"de {tf} mide {vela:.2f}.",
            f"      No caben las 2+2 velas de una Pauta: el patrón NO se puede leer aquí "
            f"(por eso no ve nada aunque el precio la trabaje).",
            f"      Ciclo {e['ancla']:.2f} ({e['tf_ciclo']}): zona NO OPERABLE a su escala."]


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
    for linea in texto_zona_estrecha(e):
        txt += "\n" + linea
    return txt + texto_operacion(e.get('operacion'))


# Qué significa cada estado del patrón, en el idioma del operador (los estados
# son del motor; esto es lo que él quiere leer: "hizo un engaño profundo").
FRASES = {
    'P3_CORTA_GATILLO': '🔴 ENGAÑO PROFUNDO DISPARADO (entrada profunda, Pauta 3 corta)',
    'ENTRADA_PROFUNDA_ESPERANDO': '🟡 Entrada Profunda ARMADA: espera el retroceso al 61.8',
    'P3_CORTA_ROTA': '❌ Entrada Profunda que saltó el stop',
    'GATILLO_ACTIVADO': '🔴 ENGAÑO COMPLETO DISPARADO (3 Pautas)',
    'ENGAÑO_EN_CURSO': '🟡 engaño en curso: consumió el 161.8, espera el gatillo',
    'ESPERANDO_1618': '🟡 engaño formándose: aún no consume el 161.8',
    'EN_FORMACION_PAUTA_2': '⏳ formando la Pauta 2 (el rechazo aún corre)',
    'ROTO_POR_STOP_LOSS': '❌ engaño que saltó el stop',
    'ROTO_POR_DOBLE_TOQUE': '❌ engaño roto: retesteó el extremo del 161.8',
    'ANULADO_POR_CARENCIA': '⚠ gatillo con CARENCIA (no operable): espera el 161.8 o validación',
    'VALIDADO_POSTERIOR': '🟡 carencia VALIDADA después: solo entrada calmada',
    'DT_IMPULSO_GATILLO': '🔴 DOBLE TECHO/SUELO CON IMPULSO DISPARADO',
    'DT_IMPULSO_ESPERANDO': '🟡 Doble Techo/Suelo con Impulso: espera el 61.8',
    'ROTO_POR_RETESTEO_DILATACION': '❌ Doble Techo/Suelo roto (retesteó la dilatación)',
    'EE_GATILLO': '🔴 ENGAÑO EXTREMO DISPARADO (volvió a entrar a la zona)',
    'EE_ARMADO': '🟡 Engaño Extremo ARMADO: entra si el precio cruza de vuelta',
    'EE_EN_INDECISION': '⚪ precio fuera de la zona, en indecisión: INOPERABLE',
    'EE_DESCARTADO_25': '⚪ escape tímido (<25%): descartado, viene sacudida más potente',
    'ANULADO_POR_ESCAPE': '❌ anulado: el precio escapó de la zona',
    'ANULADO_VUELTA_EN_V': '⚪ vuelta en V (solo 2 pautas): sin información, descartado',
    'ANULADO_SIN_SALIDA_DE_ZONA': '⚪ trabajo interno (la P2 no salió de la zona): no es patrón',
    'ANULADO_POR_PROPORCIONALIDAD': '⚪ patrón no proporcional roto: evoluciona al siguiente engaño',
    'NO_PROPORCIONAL_EN_CURSO': '⚪ patrón NO proporcional (jamás operable): espera evolución',
    'ESTRUCTURA_DESCARTADA': '⚪ llegada tímida: sin patrón, esperar nueva Pauta 1',
    'ZONA_AGOTADA': '⚫ ZONA AGOTADA: se rompieron 3 engaños',
    'NO_INICIADO': '⚪ sin actividad: el precio no ha dejado picos dentro',
}


def _frase(estado):
    return FRASES.get(estado, estado)


def _linea_trabajo(h):
    """Un trabajo pasado de la zona: qué fue, cuándo y con qué entrada/SL."""
    d = h.get('detalles', {})
    hora = hora_cot(d.get('hora_gatillo') or d.get('hora_validacion') or d.get('pauta1_time'))
    txt = f"   • {_frase(h['estado'])}"
    if hora:
        txt += f" ({hora})"
    entrada = (d.get('gatillo_agresivo') or d.get('entrada_p3_corta')
               or d.get('entrada_dt_618') or d.get('espera_calmada'))
    if entrada is not None and d.get('stop_loss') is not None:
        txt += f"\n     entrada {entrada:.2f} | SL {d['stop_loss']:.2f}"
    return txt


def texto_zonas_ancla(escaneos, precio):
    """QUÉ HA PASADO en cada zona del tramo del ancla (regla usuario 13 jul: "el
    precio hizo un engaño profundo desde esa ancla y el bot no me lo dijo").

    De cada zona sale su HISTORIA completa (la cadena de engaños del episodio) y
    lo que ocurre AHORA; si hay algo operable, con la operación entera."""
    if not escaneos:
        return "\n\nSin zonas escaneables en este tramo."
    L = ["", "📖 QUÉ HA PASADO EN SUS ZONAS:"]
    for e in sorted(escaneos, key=lambda e: -max(e['rango'])):
        res = e['resultado']
        accion = "VENTAS" if e['lado'] == "SELL" else "COMPRAS"
        zmax, zmin = e['rango']
        if zmin <= precio <= zmax:
            donde = "← PRECIO DENTRO 🎯"
        else:
            d = (zmin - precio) if precio < zmin else (precio - zmax)
            donde = f"(a {d:.2f} | {d / precio:.1%})"
        ctx = " [zona macro: contexto]" if e['contexto'] else ""
        # La banda (Alta/Media/Baja) y, sobre todo, EL ANCLA DE SU CICLO — el
        # punto de control que crea la zona (regla usuario 13 jul: "necesito las
        # anclas de los ciclos, no la principal repetida en todas").
        banda = e['zona'].rsplit('(', 1)[-1].rstrip(')') if '(' in e['zona'] else e['zona']
        L.append(f"\n[{accion}] {banda} {zmax:.2f}-{zmin:.2f} {donde}{ctx}")
        if e.get('ancla') is not None:
            ciclo = ""
            if e.get('ciclo_origen') is not None and e.get('ciclo_fin') is not None:
                ciclo = f": {e['ciclo_origen']:.2f} → {e['ciclo_fin']:.2f}"
            L.append(f"   ⚓ ancla del ciclo: {e['ancla']:.2f} ({e['tf_ciclo']}){ciclo}")
        L += texto_zona_estrecha(e)

        previos = [h for h in (res.get('historial') or []) if h is not res]
        if previos:
            L.append(f"   ── ya trabajada {len(previos)} vez(ces):")
            L += [_linea_trabajo(h) for h in previos]
        if res['estado'] == 'NO_INICIADO' and not previos:
            L.append(f"   {_frase(res['estado'])}")
            continue
        L.append(f"   ➡ AHORA: {_frase(res['estado'])}")
        d = res.get('detalles', {})
        hora = hora_cot(d.get('hora_gatillo') or d.get('hora_validacion'))
        if hora:
            L.append(f"      {hora}")
        lleg = d.get('calidad_llegada')
        if lleg == "BARRIDO":
            L.append(f"      ⚡ llegada BARRIDO: tocó y salió (mecha {d.get('mecha_vs_cuerpo')}x)")
        elif lleg == "LENTA":
            L.append(f"      🐌 llegada lenta: {d.get('cierres_dentro')} cierres dentro")
        op = e.get('operacion')
        if op:
            L.append(texto_operacion(op).lstrip('\n'))
        elif e['contexto'] and res['estado'] in ESTADOS_OPERABLES:
            L.append("      (zona macro: no se opera; sus oportunidades llegan por los sub-ciclos)")
    return '\n'.join(L)


def texto_rsi3m(sym, ancla, ancla_time, trades, descartadas, lados_txt="compras y ventas"):
    """Lo que ha hecho la rsi_3m desde el ancla que marcó el operador."""
    L = [f"📈 RSI_3M {sym} desde {ancla:.2f} ({hora_cot(ancla_time)})",
         f"   estrategia pura: {lados_txt}, sin filtros, TP 1:10"]
    vivas = [t for t in trades if t['resultado'] == 'ABIERTA']
    cerradas = [t for t in trades if t['resultado'] in ('TP', 'SL')]
    if not trades:
        L.append("\nSin señales desde el ancla. 👁 VIGILANDO: te aviso en cuanto haya una.")
        return '\n'.join(L)

    if cerradas:
        r = sum(t['R'] for t in cerradas)
        ganadas = sum(1 for t in cerradas if t['resultado'] == 'TP')
        L.append(f"\nYA OCURRIERON ({len(cerradas)}, ganadas {ganadas}, R {r:+.2f}):")
        for t in cerradas:
            icono = '✅' if t['resultado'] == 'TP' else '❌'
            lado = 'COMPRA' if t['side'] == 'long' else 'VENTA'
            L.append(f"  {icono} {lado} {hora_cot(t['dt'])} | entrada {t['entry']:.2f} "
                     f"SL {t['sl']:.2f} → {t['resultado']} ({t['R']:+.2f}R)")
    if vivas:
        L.append("\n🔥 SEÑAL VIVA AHORA:")
        for t in vivas:
            lado = 'COMPRA' if t['side'] == 'long' else 'VENTA'
            L.append(f"  {lado} | entrada {t['entry']:.2f} | SL {t['sl']:.2f} "
                     f"| TP 1:10 {t['tp']:.2f}\n"
                     f"  riesgo {t['riesgo_pct'] * 100:.2f}% | {hora_cot(t['dt'])}")
    if descartadas:
        L.append(f"\n({descartadas} setup(s) descartado(s): SL demasiado pegado, "
                 "las comisiones se lo comen)")
    L.append("\n👁 VIGILANDO: te aviso de cada señal nueva de rsi_3m en este ancla.")
    return '\n'.join(L)


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
