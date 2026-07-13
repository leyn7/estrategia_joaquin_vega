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

from mdt_config import (SYMBOL, TZ_LOCAL, TF_MINUTOS, MAX_VELAS_DESCARGA,
                        ORIGENES_MACRO_MANUAL, NIVEL_382, NIVEL_618)
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


TF_BUSQUEDA = ("1m", "3m", "15m", "30m", "1h", "2h", "4h", "1d")
TOL_ANCLA_PCT = 0.0005   # 0.05% del precio: dos toques dentro de esto son "el mismo nivel"
EPS_ANCLA = 1e-9         # dos coincidencias así de parejas son EL MISMO punto: manda la reciente


def _a_utc(t_cot):
    """Hora del operador (COT, sin zona) -> UTC sin zona, como vienen las velas."""
    return pd.Timestamp(t_cot).tz_localize(TZ_LOCAL).tz_convert('UTC').tz_localize(None)


def localizar_ancla(precio_ancla, symbol=SYMBOL, cutoff=None, direction=None,
                    tf="30m", dias=240, fecha=None):
    """Ubica en el gráfico el ancla que el operador marcó y decide su sentido.

    Un ancla alcista es un MÍNIMO (origen de un impulso al alza); una bajista es
    un MÁXIMO. Se busca la vela cuyo low (o high) más se acerque al precio dado.

    Dos precisiones que el operador pidió (13 jul), porque un precio suelto es
    ambiguo:
      - `fecha` (día en HORA DEL OPERADOR, COT): la búsqueda se encierra en ese
        día. Sin ella se miran los últimos `dias`.
      - `tf`: resolución de BÚSQUEDA del punto, no del análisis — el análisis
        sigue siendo fractal (cascada 1d->1m). Un ancla de mecha fina no existe
        en 30m: `tf="1m"` la encuentra. El presupuesto de descarga acota la
        ventana sola (240 días de 1m no existen).

    Cuando el mismo nivel fue tocado varias veces manda EL MÁS RECIENTE (el que
    el operador está viendo en el gráfico) y los demás se devuelven como
    alternativas — antes se elegía el más antiguo en silencio.

    Devuelve (hora_ancla, direction, precio_real, alternativas) o None.
    """
    minutos = TF_MINUTOS.get(tf)
    if minutos is None:
        return None
    limite = pd.Timestamp(cutoff) if cutoff is not None else ahora()
    if fecha is not None:
        desde = _a_utc(pd.Timestamp(fecha).normalize())
        limite = min(limite, desde + pd.Timedelta(days=1))
    else:
        # El presupuesto de descarga manda: en 1m no hay 240 días de histórico
        dias = min(dias, max(1, int(MAX_VELAS_DESCARGA * minutos / 1440)))
        desde = limite - pd.Timedelta(days=dias)
    df = descargar(tf, desde, limite, symbol)
    if not len(df):
        return None

    err_lo = (df['low'] - precio_ancla).abs()
    err_hi = (df['high'] - precio_ancla).abs()
    if direction is None:
        direction = "BULLISH" if err_lo.min() <= err_hi.min() else "BEARISH"
    col, err = ('low', err_lo) if direction == "BULLISH" else ('high', err_hi)

    # Manda el precio que dio el operador: gana la coincidencia MÁS EXACTA. Solo
    # cuando el mismo punto se repite (varios toques igual de exactos) desempata
    # el MÁS RECIENTE — el que él está viendo en el gráfico; antes ganaba el más
    # antiguo en silencio.
    mejor = float(err.min())
    elegido = df[err <= mejor + EPS_ANCLA].iloc[-1]
    # Otros toques del MISMO nivel (dentro de la tolerancia): no cambian el ancla,
    # solo avisan de que el precio suelto era ambiguo.
    tol = max(mejor, precio_ancla * TOL_ANCLA_PCT)
    otros = df[(err <= tol) & (df['open_time'] != elegido['open_time'])]
    alternativas = [(t, float(p)) for t, p in
                    zip(otros['open_time'], otros[col])][-3:]
    return elegido['open_time'], direction, float(elegido[col]), alternativas
