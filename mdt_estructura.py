# -*- coding: utf-8 -*-
"""DÓNDE EMPIEZA EL MAPA (Sección 2 de la biblia): las muñecas rusas.

"Localizamos el impulso mayor absoluto del gráfico. El retroceso de este gran
fractal 1 se convierte automáticamente en el impulso del fractal 2..."

Aquí se responde una sola pregunta: ¿desde qué punto se mapea el mercado? De él
salen las tres rutas del mapa (alcista hasta el ATH, su retroceso bajista, y el
retroceso de ese retroceso) — y también se ubica el ancla que el operador marca
a mano desde Telegram.
"""
import pandas as pd

from mdt_config import SYMBOL, ORIGENES_MACRO_MANUAL, NIVEL_382, NIVEL_618
from mdt_feed import ahora, descargar


def origen_por_munecas(df_1d, ath_idx):
    """Muñecas rusas mecánicas (Secc 2) sobre el diario, acotadas al ATH.

    Cada vez que un retroceso supera el 61.8% del impulso corrido (origen ->
    máximo alcanzado), el fractal queda SELLADO y el mercado se re-funda en el
    fondo completo de ese retroceso. Solo cuentan como muñecas los sellos de
    ESCALA MACRO (impulso sellado >= 38.2% del impulso total del gráfico): un
    fractal minúsculo de la infancia del activo no es estructura mensual (caso
    ETHUSDT: un sello de 50 puntos a 3 días del listado NO re-funda el mapa).

    El origen elegido es la re-fundación macro cuyo impulso hasta el ATH es el
    mayor — "el impulso mayor absoluto del gráfico". Sin re-fundaciones macro
    (moneda joven en tendencia): el mínimo global.
    """
    lows, highs = df_1d['low'].values, df_1d['high'].values
    min_global = int(df_1d.loc[:ath_idx, 'low'].idxmin())
    imp_total = highs[ath_idx] - lows[min_global]
    o = min_global
    candidatos = []
    while True:
        p_val = lows[o]
        sello = None
        for i in range(o + 1, ath_idx + 1):
            if highs[i] > p_val:
                p_val = highs[i]
            if p_val > lows[o] and (p_val - lows[i]) / (p_val - lows[o]) > NIVEL_618:
                sello = i
                break
        if sello is None:
            break
        imp_sellado = p_val - lows[o]
        # Fondo del retroceso: el mínimo hasta que el precio supere el extremo sellado
        fin_retro = ath_idx
        for j in range(sello, ath_idx + 1):
            if highs[j] > p_val:
                fin_retro = j
                break
        o = sello + int(lows[sello:fin_retro + 1].argmin())
        if imp_sellado >= NIVEL_382 * imp_total:
            candidatos.append((o, highs[ath_idx] - lows[o]))
    if candidatos:
        return max(candidatos, key=lambda c: c[1])[0]
    return min_global


def derivar_estructura_macro(df_1d, symbol=SYMBOL, verbose=True):
    """Origen alcista, ATH y fondo del gráfico — de aquí salen las 3 rutas.

    El origen sale de la banda manual del operador si la fijó (la biblia le deja
    a él la elección de la muñeca), y si no, de la derivación automática.
    """
    ath_idx = int(df_1d['high'].idxmax())
    fondo_idx = int(df_1d.loc[ath_idx:, 'low'].idxmin()) if ath_idx < len(df_1d) - 1 else None

    banda = ORIGENES_MACRO_MANUAL.get(symbol)
    if banda is not None:
        en_banda = df_1d[(df_1d['low'] > banda[0]) & (df_1d['low'] < banda[1])]
        if en_banda.empty:
            raise RuntimeError(
                f"No hay velas diarias de {symbol} con low en la banda manual {banda}. "
                "Revisar ORIGENES_MACRO_MANUAL o dejar la derivación automática.")
        origen_idx = int(en_banda.index[-1])
        modo = f"manual (banda {banda})"
    elif ath_idx > 0:
        origen_idx = origen_por_munecas(df_1d, ath_idx)
        modo = "auto (muñecas rusas Secc 2)"
    else:
        origen_idx, modo = None, "sin tramo alcista (ATH al inicio del histórico)"

    if verbose:
        o_txt = (f"{df_1d.loc[origen_idx, 'low']:.2f} @ {df_1d.loc[origen_idx, 'open_time'].date()}"
                 if origen_idx is not None else "—")
        f_txt = (f"{df_1d.loc[fondo_idx, 'low']:.2f} @ {df_1d.loc[fondo_idx, 'open_time'].date()}"
                 if fondo_idx is not None else "—")
        print(f"ESTRUCTURA MACRO {symbol}: origen {o_txt} [{modo}] | "
              f"ATH {df_1d.loc[ath_idx, 'high']:.2f} @ {df_1d.loc[ath_idx, 'open_time'].date()} | "
              f"fondo post-ATH {f_txt}")
    return {'origen_idx': origen_idx, 'ath_idx': ath_idx, 'fondo_idx': fondo_idx}


def localizar_ancla(precio_ancla, symbol=SYMBOL, cutoff=None, direction=None,
                    tf="30m", dias=240):
    """Ubica en el gráfico el ancla que el operador marcó y decide su sentido.

    Un ancla alcista es un MÍNIMO (origen de un impulso al alza); una bajista es
    un MÁXIMO. Se busca la vela cuyo low (o high) más se acerque al precio dado;
    sin sentido explícito, gana la coincidencia más exacta.
    Devuelve (hora_ancla, direction, precio_real) o None.
    """
    limite = pd.Timestamp(cutoff) if cutoff is not None else ahora()
    df = descargar(tf, limite - pd.Timedelta(days=dias), cutoff, symbol)
    if not len(df):
        return None
    i_lo = int((df['low'] - precio_ancla).abs().idxmin())
    i_hi = int((df['high'] - precio_ancla).abs().idxmin())
    err_lo = abs(float(df.loc[i_lo, 'low']) - precio_ancla)
    err_hi = abs(float(df.loc[i_hi, 'high']) - precio_ancla)
    if direction is None:
        direction = "BULLISH" if err_lo <= err_hi else "BEARISH"
    if direction == "BULLISH":
        return df.loc[i_lo, 'open_time'], direction, float(df.loc[i_lo, 'low'])
    return df.loc[i_hi, 'open_time'], direction, float(df.loc[i_hi, 'high'])
