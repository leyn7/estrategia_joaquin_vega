# -*- coding: utf-8 -*-
"""Reportes del mapa para el operador (texto, sin lógica de decisión).

Dos vistas, ambas nacidas de reglas suyas:
  - Por TRAMOS (10 jul): cada muñeca es un mapa completo por sí misma; se listan
    solo los ciclos que conservan zonas operables tras la concurrencia interna.
  - Por ANCLA (13 jul): el tramo que él marca a mano desde Telegram.
"""
from mdt_data import to_cot
from mdt_zonas import zonas_finales_tramo


def _hora(t):
    """Hora del operador (COT): las velas viajan en UTC por dentro."""
    return str(to_cot(t))[:16]


def _bandas_por_ancla(zonas):
    """Agrupa las zonas por el ancla del ciclo que las produjo."""
    por_ancla = {}
    for lado, z in zonas:
        if z.get('ancla') is not None:
            por_ancla.setdefault(round(z['ancla'], 2), []).append((lado, z))
    return por_ancla


def _banda(z):
    return z['name'].rsplit('(', 1)[-1].rstrip(')') if '(' in z['name'] else '?'


def reporte_ancla(a):
    """Mapa del tramo que marcó el operador: ciclos CON zonas operables (los que
    quedaron sin ninguna se omiten) y dónde está el precio respecto a ellas."""
    precio = a['precio']
    sentido = "alcista" if a['direction'] == 'BULLISH' else "bajista"
    # La hora del ancla se muestra en HORA DEL OPERADOR (COT): las velas vienen
    # en UTC y salía con 5 horas de más — imposible de reconocer en su gráfico.
    L = [f"⚓ ANCLA {a['ancla']:.2f} ({sentido}) → extremo {a['extremo']:.2f}",
         f"   precio {precio:.2f} | ancla del {_hora(a['ancla_time'])}"
         f" (busqueda en {a.get('tf_busqueda', '30m')})"]
    # Si su precio no existe en el gráfico, se le DICE (antes se le sustituía en
    # silencio: pidió 587.07 y se le mapeó el 585.07 sin avisar)
    pedido = a.get('pedido')
    if pedido is not None and abs(pedido - a['ancla']) > precio * 0.001:
        L.append(f"   ⚠ Tu {pedido:.2f} no existe en el gráfico ahí: lo más cercano es "
                 f"{a['ancla']:.2f} (a {abs(pedido - a['ancla']):.2f}). Es lo que mapeé.")

    alt = a.get('alternativas') or []
    if alt:
        # Un precio suelto es ambiguo: se toma la coincidencia MÁS EXACTA (y entre
        # toques iguales, el más reciente), pero el operador debe ver los otros
        # candidatos por si el que él mira en su gráfico es otro.
        otras = ', '.join(f"{p:.2f} del {_hora(t)[:10]}" for t, p in alt)
        ej = _hora(alt[-1][0])
        L.append(f"   ⚠ Ese nivel se tocó más veces ({otras}): tomé la coincidencia "
                 f"exacta del {_hora(a['ancla_time'])[:10]}. Si querías otra, dime la "
                 f"fecha: ancla {a['ancla']:.2f} {ej[8:10]}/{ej[5:7]}")
    if a.get('reset_618'):
        L.append(f"   ⚡ RESET 61.8 del tramo ({a['reset_618']['nivel']:.2f}): "
                 "los puntos de control internos ya no son válidos.")

    por_ancla = _bandas_por_ancla(a['zonas'])
    dentro, fuera, omitidos = [], [], []
    L += ["", "CICLOS OPERABLES (concurrencia aplicada):"]
    hay = False

    for c in a['ciclos']:
        ev = c.get('eval') or {}
        if ev.get('estado') != 'VIVO':
            continue
        zs = por_ancla.get(round(c['ancla'], 2), [])
        if not zs:
            omitidos.append(f"{c['ancla']:.2f} ({_motivo_omision(c)})")
            continue
        hay = True
        grado = f"grado {c['grado']:.2f}" if c['grado'] is not None else "macro del tramo"
        estado = ("ACTIVADO" if ev.get('activado')
                  else f"en alerta (38.2 en {ev['nivel_activacion']:.2f})")
        L.append(f"  • Ciclo {c['ancla']:.2f} ({c['tf']}, {grado}) {estado}")
        for lado, z in sorted(zs, key=lambda x: -max(x[1]['z'])):
            zmax, zmin = max(z['z']), min(z['z'])
            accion = "VENTAS" if lado == "SELL" else "COMPRAS"
            if zmin <= precio <= zmax:
                dentro.append((accion, z))
                marca = "  ← PRECIO DENTRO 🎯"
            else:
                d = (zmin - precio) if precio < zmin else (precio - zmax)
                fuera.append((d, accion, z))
                marca = f"  (a {d:.2f} | {d / precio:.1%})"
            L.append(f"      [{accion}] {_banda(z)}: {zmax:.2f}-{zmin:.2f}{marca}")

    if not hay:
        L.append("  (ningún ciclo conserva zonas operables)")
    if omitidos:
        L.append(f"  Omitidos sin zona útil: {', '.join(omitidos)}")
    if dentro:
        lados = '/'.join(sorted({acc for acc, _ in dentro}))
        L += ["", f"🎯 EL PRECIO ESTÁ EN ZONA de {lados} — buscar patrón (3 Pautas)."]
    elif fuera:
        d, accion, z = min(fuera, key=lambda x: x[0])
        L += ["", f"➡️ Próxima zona: {z['name']} ({accion}) a {d:.2f} ({d / precio:.1%})"]
    return "\n".join(L)


def _motivo_omision(c):
    """Por qué un ciclo vivo se quedó sin zonas operables."""
    ev = c['eval']
    if not c.get('operable', True):
        return "sub-operable <1%"
    if not ev.get('activado') and not ev.get('en_excursion'):
        return f"en alerta (38.2 en {ev['nivel_activacion']:.2f})"
    if ev.get('en_excursion') and not ev.get('zona_origen_en_trabajo'):
        return "en indecisión"
    return "zonas tejidas por la concurrencia"


def _estado_ciclo(c, direction):
    ev = c['eval']
    if ev.get('en_excursion'):
        if ev.get('zona_origen_en_trabajo'):
            return "TRABAJANDO parte " + ("baja" if direction == 'BULLISH' else "alta")
        return "en indecisión"
    if ev.get('activado'):
        return "ACTIVADO" + (" | EVOLUCIONADO" if ev.get('evolucionado') else "")
    return f"en alerta (38.2 en {ev['nivel_activacion']:.2f})"


def _reporte_de_un_tramo(t, precio):
    sentido = "alcista" if t['direction'] == 'BULLISH' else "bajista"
    L = ["", f"=== {t['nombre'].upper()} ({sentido}): "
             f"{t['origen']:.2f} -> {t['extremo']:.2f} ==="]
    if t.get('reset_618'):
        L.append(f"  RESET 61.8 DEL TRAMO: el retroceso cruzó {t['reset_618']['nivel']:.2f} — "
                 "los puntos de control internos ya NO son válidos; queda solo "
                 "el macro del tramo trabajando su Media.")

    vivos = [c for c in t['ciclos'] if c.get('eval', {}).get('estado') == 'VIVO']
    muertos = sum(1 for c in t['ciclos'] if c.get('eval', {}).get('estado') == 'MUERTO')
    if not vivos:
        L.append(f"  Sin puntos de control vivos ({muertos} muertos): sin estructura vigente.")
        return L

    por_ancla = _bandas_por_ancla(zonas_finales_tramo(t, precio))
    operables, omitidos = [], []
    for c in vivos:
        zs = por_ancla.get(round(c['ancla'], 2), [])
        if zs:
            operables.append((c, zs))
        else:
            omitidos.append(f"{c['ancla']:.2f} ({_motivo_omision(c)})")

    dentro, fuera = [], []
    if operables:
        L.append(f"  CICLOS CON ZONAS OPERABLES (concurrencia Secc 19 aplicada; "
                 f"{muertos} CPs muertos):")
        for c, zs in operables:
            grado = f"grado {c['grado']:.2f}" if c['grado'] is not None else "macro del tramo"
            L.append(f"   - Ciclo {c['ancla']:.2f} ({c['tf']}, {grado}) "
                     f"{_estado_ciclo(c, t['direction'])}:")
            for lado, z in sorted(zs, key=lambda x: -max(x[1]['z'])):
                zmax, zmin = max(z['z']), min(z['z'])
                accion = "VENTAS" if lado == "SELL" else "COMPRAS"
                if zmin <= precio <= zmax:
                    dentro.append(accion)
                    marca = "  <<< PRECIO DENTRO"
                else:
                    dist = (zmin - precio) if precio < zmin else (precio - zmax)
                    fuera.append((dist, accion, z))
                    marca = f"  (a {dist:.2f} | {dist / precio:.1%})"
                L.append(f"       [{accion}] {_banda(z)}: {zmax:.2f} a {zmin:.2f}{marca}")
    else:
        L.append("  Ningún ciclo del tramo conserva zonas operables ahora.")

    if omitidos:
        L.append(f"  Omitidos sin zona útil: {', '.join(omitidos)}")
    if dentro:
        L.append(f"  >> EL PRECIO ESTÁ EN ZONA de este tramo: buscar patrón de "
                 f"{'/'.join(sorted(set(dentro)))} (3 Pautas, Secc 9).")
    elif fuera:
        d, accion, z = min(fuera, key=lambda x: x[0])
        L.append(f"  >> Próxima zona del tramo: {z['name']} ({accion}) "
                 f"a {d:.2f} ({d / precio:.1%}).")
    for a in t.get('alerts', []):
        L.append(f"   [ALERTA 38.2] {a['name']}: si toca {a['activacion']:.2f} "
                 f"activa zona de {a['tipo']}")
    return L


def reporte_tramos(mapa):
    """Vista de tramos INDEPENDIENTES: cada muñeca con sus propios ciclos y zonas
    (concurrencia solo interna), omitiendo los ciclos que quedaron sin zona útil
    (Secc 6: un ciclo es útil mientras conserve al menos una zona útil)."""
    precio = mapa['precio']
    lineas = [f"MAPA POR TRAMOS INDEPENDIENTES | precio {precio:.2f}"]
    for t in mapa.get('tramos', []):
        lineas += _reporte_de_un_tramo(t, precio)
    return '\n'.join(lineas)
