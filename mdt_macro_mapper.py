"""Motor Estructural Universal MDT (dual-timeframe 1D -> 2H -> 30m).

Mapea ciclos macro y sub-ciclos (alcista, bajista y alcista post-fondo),
aplica la regla del 61.8%, desgrana POCs con stack monótono y resuelve
la concurrencia global de zonas (Sección 19 de la estrategia).
"""
from mdt_data import get_binance_klines
from mdt_math import calc_zones, get_active_zones, apply_concurrency, format_z
from mdt_fractal import get_bullish_poc, get_bearish_poc

# --- Configuración ---
SYMBOL = "BNBUSDT"
# Origen del ciclo macro alcista, elegido por análisis de muñecas rusas (mínimo de
# junio 2022 en ~183 USDT). Se localiza la ÚLTIMA vela diaria cuyo low cae en la banda.
ORIGEN_MACRO_BANDA = (182.0, 183.5)


def registrar_ciclo(label, name, zona, direction, df, post_idx, peso, tipo_alerta, buys, sells, alerts):
    """Imprime el ciclo, evalúa activación/muerte y registra sus zonas activas o su alerta.

    Reparto de zonas según dirección:
      BULLISH -> Compras: Baja y Media | Ventas: Alta
      BEARISH -> Compras: Baja | Ventas: Alta y Media
    """
    status = get_active_zones(zona, direction, df, post_idx)
    print(f"[{label}] Origen: {zona['origen']:.2f} | Fin: {zona['fin']:.2f}")

    if status["CYCLE_DEAD"]:
        return status

    if status["ALTA"] or status["MEDIA"] or status["BAJA"]:
        if direction == "BULLISH":
            if status["BAJA"]: buys.append({"name": f"{name} (Baja)", "z": zona['BAJA'], "peso": peso})
            if status["MEDIA"]: buys.append({"name": f"{name} (Media)", "z": zona['MEDIA'], "peso": peso})
            if status["ALTA"]: sells.append({"name": f"{name} (Alta)", "z": zona['ALTA'], "peso": peso})
        else:
            if status["BAJA"]: buys.append({"name": f"{name} (Baja)", "z": zona['BAJA'], "peso": peso})
            if status["ALTA"]: sells.append({"name": f"{name} (Alta)", "z": zona['ALTA'], "peso": peso})
            if status["MEDIA"]: sells.append({"name": f"{name} (Media)", "z": zona['MEDIA'], "peso": peso})
    else:
        alerts.append({"name": name, "activacion": zona['activacion'], "zona_alerta": zona['MEDIA'], "tipo": tipo_alerta})
    return status


def extraer_pocs_zoom(direction, start_date, extremo_label):
    """Zoom 2H -> 30m: recolecta POCs con stack monótono desde start_date hasta el extremo.

    Devuelve (pocs, df_zoom, extremo_idx). Los RESET 61.8% quedan marcados con
    is_boundary=True (límite de fractalidad) y engullen los niveles menores previos.
    """
    dir_bull = direction == "BULLISH"
    get_poc = get_bullish_poc if dir_bull else get_bearish_poc
    key = 'trough' if dir_bull else 'peak'
    key_idx = 'trough_idx' if dir_bull else 'peak_idx'

    print(f"   >>> HACIENDO ZOOM A 2H PARA EXTRACCIÓN {extremo_label} (Desde: {start_date})")
    df_zoom = get_binance_klines(SYMBOL, "2h", start_time=start_date)
    extremo_idx = df_zoom['high'].idxmax() if dir_bull else df_zoom['low'].idxmin()
    search_idx = 0
    pocs = []
    tf = "2h"

    while search_idx < extremo_idx:
        # Hot-swap a 30m a partir del Nivel 4 (2 POCs reales encontrados en 2h)
        poc_count = sum(1 for p in pocs if not p.get('is_boundary'))
        if poc_count >= 2 and tf == "2h":
            switch_time = df_zoom.loc[search_idx, 'open_time']
            print(f"   >>> HACIENDO ZOOM A 30m PARA EXTRACCIÓN MICRO (A partir del Nivel 4, Desde: {switch_time})")
            df_zoom = get_binance_klines(SYMBOL, "30m", start_time=switch_time)
            extremo_idx = df_zoom['high'].idxmax() if dir_bull else df_zoom['low'].idxmin()
            search_idx = 0
            tf = "30m"

        poc = get_poc(df_zoom, search_idx, extremo_idx)
        if poc is None: break

        # Prevent duplication after timeframe swap
        if pocs and poc[key] == pocs[-1].get(key):
            search_idx = int(poc[key_idx])
            continue

        poc['tf'] = tf

        if poc.get('type') == 'RESET':
            # Pop de niveles engullidos (bull: troughs más altos; bear: peaks más bajos)
            while pocs and (pocs[-1].get(key, 0) > poc[key] if dir_bull else pocs[-1].get(key, 0) < poc[key]):
                popped = pocs.pop()
                print(f"       -> [X] Nivel en {popped[key]:.2f} invalidado (engullido por el reset).")

            # Añadir a la lista solo para registro cronológico visual
            poc['is_boundary'] = True
            pocs.append(poc)
            search_idx = int(poc[key_idx])
            continue

        pocs.append(poc)
        search_idx = int(poc[key_idx])

    return pocs, df_zoom, extremo_idx


def procesar_pocs(pocs, direction, fin_val, df_zoom, extremo_idx, base_nombre, boundary_label,
                  tipo_alerta, buys, sells, alerts):
    """Convierte cada POC extraído en un sub-ciclo con zonas (niveles desde el 2)."""
    key = 'trough' if direction == "BULLISH" else 'peak'
    nivel = 2
    for poc in pocs:
        tf_label = poc.get('tf', '2h').upper()
        if poc.get('is_boundary'):
            print(f"[{boundary_label}] Origen: {poc[key]:.2f} | Fin: {fin_val:.2f} -> Límite de fractalidad")
            continue

        zona = calc_zones(poc[key], fin_val, direction)
        name = f"{base_nombre} Nivel {nivel}"
        registrar_ciclo(f"{name.upper()} ({tf_label})", name, zona, direction, df_zoom, extremo_idx,
                        100 - nivel, tipo_alerta, buys, sells, alerts)
        nivel += 1


def resolver_concurrencia(zonas, buy_or_sell, current_price=None):
    """Aplica la concurrencia global (la zona de mayor peso manda) y devuelve las supervivientes.

    Excepción de la Zona en Trabajo (fractalidad infinita, Sección 3 Caso 2): la zona mayor
    que CONTIENE actualmente al precio es el campo de trabajo — no elimina a los sub-ciclos
    que nacen dentro de ella; esos sub-ciclos son la vía operativa del trabajo de la mayor.
    """
    if buy_or_sell == "BUY":
        zonas = sorted(zonas, key=lambda x: max(x['z']), reverse=True)
    else:
        zonas = sorted(zonas, key=lambda x: min(x['z']))

    finales = []
    for i in range(len(zonas)):
        current = zonas[i]
        if current['z'] is None: continue
        for j in range(len(zonas)):
            if i == j: continue
            otro = zonas[j]
            if otro['z'] is None: continue
            if current_price is not None and min(otro['z']) <= current_price <= max(otro['z']):
                continue  # la mayor está en trabajo (precio dentro): no tritura sub-ciclos
            if otro['peso'] > current['peso']:
                new_z, razon = apply_concurrency(otro['z'], current['z'], buy_or_sell)
                if new_z != current['z']:
                    print(f"[{current['name']} vs {otro['name']}] -> {razon}")
                current['z'] = new_z
                if current['z'] is None:
                    break
        if current['z'] is not None:
            finales.append(current)
    return finales


def main():
    print("\n" + "="*70)
    print(" MOTOR ESTRUCTURAL UNIVERSAL MDT (DUAL-TIMEFRAME 1D -> 2H)")
    print("="*70 + "\n")

    # ---------------------------------------------------------
    # PASO 1: VISIÓN MACRO (1D)
    # ---------------------------------------------------------
    df_1d = get_binance_klines(SYMBOL, "1d")

    # Origen del macro alcista: última vela diaria cuyo low cae en la banda configurada
    en_banda = df_1d[(df_1d['low'] > ORIGEN_MACRO_BANDA[0]) & (df_1d['low'] < ORIGEN_MACRO_BANDA[1])]
    if en_banda.empty:
        raise RuntimeError(f"No se encontró el origen macro alcista de {SYMBOL} en la banda {ORIGEN_MACRO_BANDA}. "
                           "Revisar ORIGEN_MACRO_BANDA (análisis de muñecas rusas).")
    start_bull_idx = en_banda.index[-1]

    ath_idx = df_1d['high'].idxmax()
    abs_max = df_1d.loc[ath_idx]['high']

    df_post_ath = df_1d.loc[ath_idx:]
    bottom_idx = df_post_ath['low'].idxmin()
    abs_min = df_post_ath.loc[bottom_idx]['low']

    print("--- 1. IDENTIFICACIÓN Y ACTIVACIÓN DE CICLOS ---")

    buys = []
    sells = []
    alerts = []

    # =========================================================================
    # RUTA ALCISTA
    # =========================================================================
    macro_bull = calc_zones(df_1d.loc[start_bull_idx]['low'], abs_max, "BULLISH")
    registrar_ciclo("MACRO ALCISTA (1D)", "Macro Alcista", macro_bull, "BULLISH", df_1d, ath_idx,
                    100, "COMPRAS", buys, sells, alerts)

    # Regla 61.8%: si el retroceso barrió la zona media macro, la fractalidad menor quedó obsoleta
    lowest_post_ath = df_1d.loc[ath_idx:, 'low'].min()
    nivel_618_macro = macro_bull['MEDIA'][0]
    frenar_bull = lowest_post_ath <= nivel_618_macro
    if frenar_bull:
        print(f"   [!] REGLA 61.8%: El precio cayó a {lowest_post_ath:.2f}, barriendo el 61.8% ({nivel_618_macro:.2f}). Se frena búsqueda recursiva en Nivel 1.")

    biggest_bull = get_bullish_poc(df_1d, start_bull_idx, ath_idx)
    if biggest_bull:
        sub_bull = calc_zones(biggest_bull['trough'], abs_max, "BULLISH")
        registrar_ciclo("SUB-C ALCISTA NIVEL 1 (1D)", "Sub-C Alcista Nivel 1", sub_bull, "BULLISH",
                        df_1d, ath_idx, 99, "COMPRAS", buys, sells, alerts)

        # ZOOM A 2H PARA EL RESTO (Si no se frenó en 1)
        if not frenar_bull:
            trough_date = df_1d.loc[biggest_bull['trough_idx'], 'open_time']
            pocs, df_zoom, extremo_idx = extraer_pocs_zoom("BULLISH", trough_date, "ALCISTA")
            procesar_pocs(pocs, "BULLISH", abs_max, df_zoom, extremo_idx, "Sub-C Alcista",
                          "PISO ESTRUCTURAL (RESET 61.8%)", "COMPRAS", buys, sells, alerts)

    # =========================================================================
    # RUTA BAJISTA
    # =========================================================================
    print("")
    macro_bear = calc_zones(abs_max, abs_min, "BEARISH")
    registrar_ciclo("MACRO BAJISTA (1D)", "Macro Bajista", macro_bear, "BEARISH", df_1d, bottom_idx,
                    100, "VENTAS", buys, sells, alerts)

    highest_post_bottom = df_1d.loc[bottom_idx:, 'high'].max() if bottom_idx < len(df_1d)-1 else abs_min
    nivel_618_macro_bear = macro_bear['MEDIA'][1]
    frenar_bear = highest_post_bottom >= nivel_618_macro_bear
    if frenar_bear:
        print(f"   [!] REGLA 61.8%: El precio subió a {highest_post_bottom:.2f}, barriendo el 61.8% ({nivel_618_macro_bear:.2f}). Se frena búsqueda recursiva en Nivel 1.")

    biggest_bear = get_bearish_poc(df_1d, ath_idx, bottom_idx)
    if biggest_bear:
        sub_bear = calc_zones(biggest_bear['peak'], abs_min, "BEARISH")
        registrar_ciclo("SUB-C BAJISTA NIVEL 1 (1D)", "Sub-C Bajista Nivel 1", sub_bear, "BEARISH",
                        df_1d, bottom_idx, 99, "VENTAS", buys, sells, alerts)

        # ZOOM A 2H PARA EL RESTO
        if not frenar_bear:
            peak_date = df_1d.loc[biggest_bear['peak_idx'], 'open_time']
            pocs, df_zoom, extremo_idx = extraer_pocs_zoom("BEARISH", peak_date, "BAJISTA")
            procesar_pocs(pocs, "BEARISH", abs_min, df_zoom, extremo_idx, "Sub-C Bajista",
                          "TECHO ESTRUCTURAL (RESET 61.8%)", "VENTAS", buys, sells, alerts)

    # =========================================================================
    # RUTA ALCISTA POST-FONDO (REBOTE)
    # =========================================================================
    bottom_date = df_1d.loc[bottom_idx, 'open_time']
    print(f"\n   >>> HACIENDO ZOOM A 30m PARA EXTRACCIÓN ALCISTA POST-FONDO (Desde: {bottom_date})")

    # We zoom into 30m starting from the 1D bottom date to capture intraday bounces
    df_post = get_binance_klines(SYMBOL, "30m", start_time=bottom_date)
    bottom_idx_post = df_post['low'].idxmin()

    post_bottom_df = df_post.loc[bottom_idx_post:]
    highest_post_bottom_idx = post_bottom_df['high'].idxmax()

    if highest_post_bottom_idx > bottom_idx_post:
        abs_max_post = df_post.loc[highest_post_bottom_idx, 'high']
        print(f"--- 1.5. EXTRACCIÓN ALCISTA POST-FONDO (Rebote a {abs_max_post:.2f}) ---")

        abs_min_post = df_post.loc[bottom_idx_post, 'low']

        # Absolute post-bottom cycle
        macro_pb = calc_zones(abs_min_post, abs_max_post, "BULLISH")
        registrar_ciclo("MACRO ALCISTA POST-FONDO (30M)", "Macro Alcista Post-F", macro_pb, "BULLISH",
                        df_post, highest_post_bottom_idx, 96, "COMPRAS", buys, sells, alerts)

        # Recolección de POCs post-fondo: búsqueda hacia atrás desde el techo del rebote,
        # con stack por tamaño de retroceso ('drop') además de los RESET.
        valid_pocs_post_bull = []
        current_search_idx_pb = highest_post_bottom_idx

        while current_search_idx_pb > bottom_idx_post:
            biggest_bull_pb = get_bullish_poc(df_post, bottom_idx_post, current_search_idx_pb)
            if biggest_bull_pb is None: break

            if biggest_bull_pb.get('type') == 'RESET':
                while valid_pocs_post_bull and valid_pocs_post_bull[-1].get('trough', 999999) > biggest_bull_pb['trough']:
                    popped = valid_pocs_post_bull.pop()
                    print(f"       -> [X] Nivel en {popped['trough']:.2f} invalidado (engullido por el reset).")
                biggest_bull_pb['is_boundary'] = True
                valid_pocs_post_bull.append(biggest_bull_pb)
                current_search_idx_pb = int(biggest_bull_pb['trough_idx'])
                continue

            valid_pocs_post_bull.append(biggest_bull_pb)
            current_search_idx_pb = int(biggest_bull_pb['trough_idx'])

        # DESGRANE DEL RUIDO (Sección 2): "el retroceso mayor se come al menor".
        # Recorrido cronológico (más antiguo primero): cada punto de control validado
        # posteriormente con un grado (retroceso) mayor MATA a los anteriores menores.
        # Los RESET (boundaries) son límites de fractalidad que el desgrane no cruza.
        cronologico = list(reversed(valid_pocs_post_bull))
        sobrevivientes = []
        for poc in cronologico:
            if poc.get('is_boundary'):
                sobrevivientes.append(poc)
                continue
            while sobrevivientes and not sobrevivientes[-1].get('is_boundary') and sobrevivientes[-1]['drop'] < poc['drop']:
                popped = sobrevivientes.pop()
                print(f"       -> [X] Punto de control en {popped['trough']:.2f} MUERE (desgrane: retroceso mayor posterior en {poc['trough']:.2f}).")
            sobrevivientes.append(poc)
        valid_pocs_post_bull = list(reversed(sobrevivientes))

        nivel_pb = 1
        for poc in reversed(valid_pocs_post_bull):
            if poc.get('is_boundary'):
                print(f"[FONDO ESTRUCTURAL POST (RESET)] Origen: {poc['trough']:.2f} | Fin: {abs_max_post:.2f}")
                continue

            pb_bull = calc_zones(poc['trough'], abs_max_post, "BULLISH")
            name = f"Sub-C Alcista Post-F Nivel {nivel_pb}"
            registrar_ciclo(f"{name.upper()} (30M)", name, pb_bull, "BULLISH", df_post,
                            highest_post_bottom_idx, 95 - nivel_pb, "COMPRAS", buys, sells, alerts)
            nivel_pb += 1

    # =========================================================================
    # CONCURRENCIA GLOBAL
    # =========================================================================
    print("\n--- 2. CONCURRENCIA GLOBAL DE ZONAS ACTIVAS ---")
    current_price = df_1d.iloc[-1]['close']

    print("\n[ZONAS DE COMPRAS]")
    final_buys = resolver_concurrencia(buys, "BUY", current_price)

    print("\n[ZONAS DE VENTAS]")
    final_sells = resolver_concurrencia(sells, "SELL", current_price)

    print("\n--- 3. ZONAS OPERATIVAS FINALES ---")
    print("ZONAS DE VENTAS:")
    for s in final_sells:
        print(f" -> {s['name']}: {format_z(s['z'])}")
    print("\nZONAS DE COMPRAS:")
    for b in final_buys:
        print(f" -> {b['name']}: {format_z(b['z'])}")

    if alerts:
        print("\n--- 4. ZONAS EN EVOLUCION (ALERTAS NO ACTIVADAS) ---")
        for a in alerts:
            print(f" -> {a['name']}: Si el precio toca {a['activacion']:.2f} (38.2%), se activará Zona de {a['tipo']} en {format_z(a['zona_alerta'])}")

    print(f"\nPRECIO ACTUAL: {current_price:.2f}")


if __name__ == "__main__":
    main()
