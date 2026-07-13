# -*- coding: utf-8 -*-
"""Los textos del escáner por consola (sin lógica de decisión).

Dos vistas: la del mapa global (con TODOS los trabajos de cada zona) y la de
tramos independientes (con los duelos entre tramos al final).
"""
from mdt_config import RATIO_MINIMO
from mdt_operacion import es_accionable


def _texto_llegada(d):
    """La forma de la llegada a la zona (regla usuario 11 jul: la mechita)."""
    lleg = d.get('calidad_llegada')
    if lleg == "BARRIDO":
        return (f" [LLEGADA: BARRIDO ⚡ mecha {d.get('mecha_vs_cuerpo')}x, "
                f"{d.get('velas_visita')} vela(s)]")
    if lleg == "LENTA":
        return f" [LLEGADA: LENTA — {d.get('cierres_dentro')} cierres dentro]"
    return ""


def imprimir_escaneo_mapa(escaneos, prioritaria, zona_que_manda):
    if zona_que_manda:
        print(f"\nTRABAJO ACTUAL DEL PRECIO: dentro de '{zona_que_manda}' "
              f"({'COMPRAS' if prioritaria == 'BUY' else 'VENTAS'}) — cada señal "
              "hereda la prioridad de su propia zona")
    print("\n--- ESCÁNER DE PATRONES SOBRE EL MAPA (TF del patrón = 1 por debajo del ciclo) ---")
    for e in escaneos:
        res = e['resultado']
        marca = " <<<" if es_accionable(e) else ""
        ctx = " [ZONA MACRO: contexto, no se opera]" if e['contexto'] else ""
        print(f"[{e['lado']}] {e['zona']} {e['rango'][0]:.2f}-{e['rango'][1]:.2f} "
              f"(ciclo {e['tf_ciclo']} -> patrón {e['tf_patron']}, ancla {e['ancla']:.2f}){ctx}")
        # Trabajos de la zona (regla usuario 6 jul): TODA la cadena evaluada en el
        # episodio operativo — el usuario necesita ver si la zona YA fue trabajada
        # (entradas profundas, engaños, EE...), no solo el estado vigente.
        previos = [h for h in (res.get('historial') or []) if h is not res]
        for k, h in enumerate(previos, 1):
            dh = h.get('detalles', {})
            hora_h = dh.get('hora_gatillo') or dh.get('hora_validacion') or dh.get('pauta1_time')
            hora_h_txt = f" @ {hora_h}" if hora_h is not None else ""
            print(f"      trabajo {k}: {h['estado']}{hora_h_txt} — {h['mensaje']}")
        d_res = res.get('detalles', {})
        hora = d_res.get('hora_gatillo')
        hora_txt = f" [gatillo: {hora}]" if hora is not None else ""
        pref = f"trabajo {len(previos) + 1} (vigente): " if previos else ""
        print(f"      {pref}{res['estado']}: {res['mensaje']}{hora_txt}"
              f"{_texto_llegada(d_res)}{marca}")
        op = e.get('operacion')
        if op:
            veredicto = (f"CUMPLE 1:{RATIO_MINIMO:.0f}" if op['cumple_ratio']
                         else f"NO CUMPLE 1:{RATIO_MINIMO:.0f} -> NO OPERAR (Secc 1)")
            print(f"      OPERACIÓN: entrada {op['entrada']:.2f} | SL {op['stop_loss']:.2f} "
                  f"(riesgo {op['riesgo']:.2f}) | TP zona {op['tp_zona'][0]:.2f}-{op['tp_zona'][1]:.2f} "
                  f"(al borde: {op['recompensa']:.2f})")
            print(f"      R:B 1:{op['ratio']:.1f} [{veredicto}] | {op['movimiento']} "
                  f"| Volumen: {op['volumen']}")
            if op.get('aviso'):
                print(f"      AVISO: {op['aviso']}")


def imprimir_escaneo_tramos(escaneos, duelos):
    print("\n--- ESCÁNER DE PATRONES POR TRAMO (zonas independientes por muñeca) ---")
    for e in escaneos:
        res = e['resultado']
        if res['estado'] == 'NO_INICIADO':
            continue
        marca = " <<<" if es_accionable(e) else ""
        ctx = " [contexto]" if e['contexto'] else ""
        lleg = res.get('detalles', {}).get('calidad_llegada')
        lleg_txt = f" [LLEGADA: {lleg}]" if lleg and lleg != 'NORMAL' else ""
        print(f"[{e['tramo']}] [{e['lado']}] {e['zona']} "
              f"{e['rango'][0]:.2f}-{e['rango'][1]:.2f}{ctx}")
        print(f"      {res['estado']}: {res['mensaje'][:110]}{lleg_txt}{marca}")
        op = e.get('operacion')
        if op:
            print(f"      OPERACIÓN: entrada {op['entrada']:.2f} | SL {op['stop_loss']:.2f} "
                  f"| TP {op['tp_zona'][0]:.2f}-{op['tp_zona'][1]:.2f} | R:B 1:{op['ratio']:.1f}")
    for g in duelos:
        gana = g[0]
        print(f"\n🥇 DUELO ({'VENTAS' if gana['lado'] == 'SELL' else 'COMPRAS'} concurrentes "
              f"entre tramos): GANA {gana['zona']} [{gana['tramo']}] "
              f"(llegada {gana['resultado'].get('detalles', {}).get('calidad_llegada', '?')}, "
              f"{gana['resultado']['estado']})")
        for x in g[1:]:
            print(f"      pierde: {x['zona']} [{x['tramo']}] ({x['resultado']['estado']})")
