# -*- coding: utf-8 -*-
"""LA TABLA DE NIVELES: todo lo que el mapa ya sabe, listo para vigilar.

Idea del operador (18 jul): "el bot escanea una vez y luego va escribiendo lo que
hace el precio: el 38.2 ya se tiene en memoria — si el precio lo toca, se activa;
no es necesario estar haciendo siempre un escaneo general".

De un mapa recién construido se extraen TODOS los niveles que significan algo:
activaciones 38.2, bordes de zona, muertes, evolución, RESET 61.8 del tramo y los
extremos vigentes (que al superarse deslizan el 38.2). El vigía (mdt_vigia) solo
tiene que comparar el precio contra esta tabla — cero cómputo si nada se toca.

Cada nivel: {'id', 'tipo', 'nivel', 'detalle'} — el id es estable para deduplicar
avisos entre refrescos de la tabla.
"""


def _nv(niveles, id_, tipo, nivel, detalle):
    if nivel is None:
        return
    niveles.append({'id': id_, 'tipo': tipo, 'nivel': float(nivel), 'detalle': detalle})


def tabla_de_niveles(mapa):
    """Extrae la tabla de niveles vigilables de un mapa completo."""
    niveles = []

    # --- Por ciclo VIVO: activación, muerte, evolución, extremo vigente ---
    for c in mapa.get('ciclos', []):
        ev = c.get('eval') or {}
        if ev.get('estado') != 'VIVO':
            continue
        ancla = c.get('ancla')
        base = f"{c.get('ruta','?')}|{ancla:.2f}"
        nombre = c.get('nombre', f"ciclo {ancla:.2f}")

        if not ev.get('activado'):
            _nv(niveles, f"act|{base}", 'ACTIVACION_38.2', ev.get('nivel_activacion'),
                f"{nombre}: al tocarlo se ACTIVA el ciclo (nacen sus zonas)")
        _nv(niveles, f"muerte|{base}", 'MUERTE_CICLO', ev.get('nivel_muerte'),
            f"{nombre}: extensión -38.2 — el ciclo MUERE")
        _nv(niveles, f"evo|{base}", 'EVOLUCION_38.2', ev.get('evolucion_38_2'),
            f"{nombre}: evoluciona a ciclo mayor (Secc 8)")
        _nv(niveles, f"actcand|{base}", 'ACTIVACION_CANDIDATA', ev.get('activacion_candidata'),
            f"{nombre}: nace la medida candidata (fin corrido)")
        _nv(niveles, f"fin|{base}", 'EXTREMO_VIGENTE', ev.get('fin_vigente'),
            f"{nombre}: superarlo extiende el fin (desliza el 38.2)")

    # --- Por zona operativa final: sus dos bordes ---
    for lado, zonas in (("SELL", mapa.get('sells', [])), ("BUY", mapa.get('buys', []))):
        for z in zonas:
            if not z.get('z') or z.get('ancla') is None:
                continue
            zmax, zmin = max(z['z']), min(z['z'])
            base = f"{lado}|{z['name']}|{z['ancla']:.2f}"
            _nv(niveles, f"ztop|{base}", 'BORDE_ZONA', zmax,
                f"{z['name']} ({lado}): borde superior")
            _nv(niveles, f"zbot|{base}", 'BORDE_ZONA', zmin,
                f"{z['name']} ({lado}): borde inferior")
            _nv(niveles, f"anul|{base}", 'ANULACION_ZONA', z.get('nivel_anulacion'),
                f"{z['name']} ({lado}): anulación (muere la zona con el ciclo)")

    # --- Por tramo: el RESET 61.8 (si aún no disparó) ---
    for t in mapa.get('tramos', []):
        o, e = t.get('origen'), t.get('extremo')
        if o is None or e is None or t.get('reset_618'):
            continue
        imp = e - o
        nivel = e - imp * 0.618
        _nv(niveles, f"reset|{t['nombre']}", 'RESET_61.8_TRAMO', nivel,
            f"tramo {t['nombre']}: al cruzarlo mueren los CPs internos (queda el macro)")

    # --- Alertas 38.2 del mapa (ciclos por activar) ---
    for a in mapa.get('alerts', []):
        _nv(niveles, f"alerta|{a.get('name')}", 'ALERTA_38.2', a.get('activacion'),
            f"{a.get('name')}: activaría zona de {a.get('tipo')}")

    return niveles
