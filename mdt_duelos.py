# -*- coding: utf-8 -*-
"""Duelos de patrones ENTRE TRAMOS (regla usuario 12 jul).

Dentro de un tramo, dos zonas que concurren las resuelve la concurrencia de la
Secc 19 (una absorbe, acota o elimina a la otra). Pero dos tramos distintos son
dos mapas correctos por sí mismos: sus zonas pueden solaparse y ambas dar patrón.
Ahí no decide la geometría sino la CALIDAD DEL PATRÓN — "miraremos en cuál patrón
operaremos dependiendo de la calidad del patrón".
"""
from mdt_operacion import es_accionable


def _puntaje_patron(e):
    """Calidad del patrón para el duelo. Orden: llegada BARRIDO > NORMAL > LENTA;
    gatillo vivo > en espera; proporcional; ratio como desempate."""
    res = e['resultado']
    d = res.get('detalles', {})
    lleg = {'BARRIDO': 2, 'NORMAL': 1, 'LENTA': 0}.get(d.get('calidad_llegada'), 1)
    gatillo = 1 if 'GATILLO' in res['estado'] else 0
    prop = 1 if d.get('proporcional') else 0
    op = e.get('operacion') or {}
    return (lleg, gatillo, prop, op.get('ratio', 0.0))


def _rangos_solapan(a, b):
    return min(a[0], b[0]) >= max(a[1], b[1])  # rangos son (max, min)


def duelos_entre_tramos(escaneos):
    """Señales accionables del MISMO lado cuyas zonas concurren (se solapan) pero
    pertenecen a TRAMOS DISTINTOS. Devuelve grupos ordenados por calidad: el
    primero de cada grupo es el ganador (el patrón que se opera)."""
    acc = [e for e in escaneos if es_accionable(e) and e.get('tramo') is not None]
    grupos = []
    for e in acc:
        for g in grupos:
            if (g[0]['lado'] == e['lado']
                    and any(_rangos_solapan(x['rango'], e['rango']) for x in g)):
                g.append(e)
                break
        else:
            grupos.append([e])
    duelos = []
    for g in grupos:
        if len({x['tramo'] for x in g}) >= 2:
            g.sort(key=_puntaje_patron, reverse=True)
            duelos.append(g)
    return duelos
