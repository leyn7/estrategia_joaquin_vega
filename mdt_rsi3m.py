# -*- coding: utf-8 -*-
"""Estrategia RSI_3M bajo demanda (portada de bot_rsi5m, que corre en el VPS).

El operador marca un mínimo o un máximo —el que le deja un Engaño Extremo, por
ejemplo— y dice: "a partir de aquí opérame con rsi_3m". El bot vigila las velas
de 3m desde ese punto y avisa cuando la estrategia da señal.

REGLAS (todo sobre velas CERRADAS, RSI(14) de Wilder):
  La dirección la marca el último extremo del RSI:
    - último extremo SOBREVENTA (<=30) -> contexto bajista -> se buscan VENTAS
    - último extremo SOBRECOMPRA (>=70) -> contexto alcista -> se buscan COMPRAS

  VENTA:  tras el piso de sobreventa, el RSI rebota y cruza >=50. El MÁXIMO de
          ese rebote es el STOP LOSS (se sigue moviendo mientras el rebote sube).
          Entrada corta cuando una vela CIERRA en sobreventa (<=30).
  COMPRA: espejo. Tras el techo de sobrecompra, el RSI retrocede bajo 50. El
          MÍNIMO del retroceso es el STOP LOSS. Entrada larga cuando una vela
          CIERRA en sobrecompra (>=70).
  FLIP:   si el rebote cierra en sobrecompra (o el retroceso en sobreventa), el
          patrón se anula y se busca el contrario.
  TP = RR * riesgo (1:10 en la config validada).

INTERRUPTORES (la diferencia entre el bot automático y el modo bajo demanda):
  - `estructural`: exigir que la entrada no rompa el piso/techo previo
    (higher-low / lower-high). El bot automático lo exige; el operador lo quitó
    para el modo bajo demanda (13 jul): "le quitaremos esa condición".
  - `lados`: el bot automático solo opera LARGOS (los cortos no pasaron la
    validación de 5 años). Bajo demanda el operador pide los dos: él elige el
    contexto, él es el filtro.
  - `filtro_1h`: banda de RSI + sesgo + régimen EMA50/200 en 1h. El bot
    automático lo exige; bajo demanda va apagado por defecto.
"""
import numpy as np
import pandas as pd

from mdt_config import COMISION_LADO, MIN_RIESGO_PCT, SYMBOL
from mdt_feed import descargar

RSI_PERIOD = 14
MID, OB, OS = 50, 70, 30
RR = 10                    # TP = RR * riesgo (config validada)
FEE_ENTRY = FEE_EXIT = COMISION_LADO   # única fuente: mdt_config
EMA_FAST, EMA_SLOW = 50, 200
H1_VENTA_BANDA = (50, 70)
H1_COMPRA_BANDA = (30, 50)
DIAS_WARMUP = 4            # velas previas al ancla para que el RSI llegue caliente


def rsi_wilder(close, period=RSI_PERIOD):
    """RSI con suavizado de Wilder (el mismo que pinta TradingView)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def cargar_3m(symbol=SYMBOL, desde=None, cutoff=None):
    """Velas de 3m CERRADAS con su RSI (la vela en curso se descarta)."""
    df = descargar("3m", desde, cutoff, symbol)
    if len(df) < RSI_PERIOD + 2:
        return df.assign(rsi=np.nan)
    df = df.rename(columns={'open_time': 'dt'})[['dt', 'open', 'high', 'low', 'close']]
    df['rsi'] = rsi_wilder(df['close'])
    return df.iloc[:-1].dropna(subset=['rsi']).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Filtro de la temporalidad mayor (1h) — solo si se pide
# ---------------------------------------------------------------------------
def _serie_1h(df):
    """Velas de 1h (resampleo exacto de las 3m) con RSI, sesgo y régimen EMA."""
    s = df.set_index('dt')
    h1 = pd.DataFrame({
        'open': s['open'].resample('1h', label='left', closed='left').first(),
        'high': s['high'].resample('1h', label='left', closed='left').max(),
        'low': s['low'].resample('1h', label='left', closed='left').min(),
        'close': s['close'].resample('1h', label='left', closed='left').last(),
    }).dropna()
    h1['rsi'] = rsi_wilder(h1['close'])
    ema_f = h1['close'].ewm(span=EMA_FAST, adjust=False).mean()
    ema_s = h1['close'].ewm(span=EMA_SLOW, adjust=False).mean()
    h1['regime'] = (ema_f > ema_s).map({True: 'bull', False: 'bear'})

    # Reconquista del 50: bloquea comprar mientras el 1h sigue bajo 50 saliendo
    # de sobreventa (un cuchillo en el marco mayor)
    ru, rd, up, down = [], [], False, False
    for r in h1['rsi']:
        if pd.notna(r):
            if r >= MID:
                up = True
            elif r <= OS:
                up = False
            if r <= MID:
                down = True
            elif r >= OB:
                down = False
        ru.append(up)
        rd.append(down)
    h1['reclaim_up'], h1['reclaim_down'] = ru, rd

    bias, b, last_ext, armado, prev = [], 'none', None, None, None
    for r in h1['rsi']:
        if pd.notna(r):
            if r >= OB and last_ext != 'ob':
                if last_ext == 'os':
                    armado = 'bull'
                last_ext = 'ob'
            elif r <= OS and last_ext != 'os':
                if last_ext == 'ob':
                    armado = 'bear'
                last_ext = 'os'
            if prev is not None:
                if prev < MID <= r and armado == 'bear':
                    b, armado = 'bear', None
                elif prev > MID >= r and armado == 'bull':
                    b, armado = 'bull', None
            prev = r
        bias.append(b)
    h1['bias'] = bias
    return h1


def _anexar_1h(df):
    """A cada vela 3m, el estado de la última vela 1h CERRADA (sin lookahead)."""
    h1 = _serie_1h(df)
    starts = h1.index.values.astype('datetime64[ns]')
    t = df['dt'].values.astype('datetime64[ns]')
    lastc = np.searchsorted(starts, t, side='right') - 2   # la anterior a la que contiene a t
    valid = lastc >= 0
    df = df.copy()
    for col, defecto in (('rsi', np.nan), ('bias', 'none'), ('regime', 'bear'),
                         ('reclaim_up', False), ('reclaim_down', False)):
        vals = np.array(h1[col].values, dtype=object)
        out = np.array([defecto] * len(df), dtype=object)
        out[valid] = vals[lastc[valid]]
        df['h1' + col] = out
    return df


# ---------------------------------------------------------------------------
# Motor de señales (máquina de estados sobre el RSI de 3m)
# ---------------------------------------------------------------------------
def senales(df, lados=("long", "short"), estructural=False, filtro_1h=False,
            rr=RR, desde=None):
    """Recorre las velas y devuelve las señales de la estrategia.

    `desde`: solo se reportan las entradas posteriores a ese instante (el ancla
    del operador); las anteriores solo sirven para calentar la máquina.
    """
    if filtro_1h:
        df = _anexar_1h(df)
    corte = pd.Timestamp(desde) if desde is not None else None

    def permiso(tipo, j):
        if not filtro_1h:
            return True
        r = df['h1rsi'].iloc[j]
        b = df['h1bias'].iloc[j]
        if pd.isna(r):
            return False
        if tipo == 'venta':
            return H1_VENTA_BANDA[0] <= r < H1_VENTA_BANDA[1] and b == 'bear'
        return H1_COMPRA_BANDA[0] < r <= H1_COMPRA_BANDA[1] and b == 'bull'

    estado = 'idle'          # idle | bear_rebote | bear_entrada | bull_retro | bull_entrada
    piso = techo = sl_ext = None
    pos_long = pos_short = None
    trades, descartados = [], 0
    permiso_venta = permiso_compra = not filtro_1h
    lado = run_hi = run_lo = None
    run_hi_i = run_lo_i = 0
    run_ob = run_os = False

    def abrir(side, i, v):
        nonlocal pos_long, pos_short, descartados
        e = float(v['close'])
        riesgo = abs(sl_ext - e)
        if riesgo / e < MIN_RIESGO_PCT:     # SL pegado: las comisiones se lo comen
            descartados += 1
            return False
        p = {'side': side, 'i': i, 'dt': v['dt'], 'entry': e, 'sl': float(sl_ext),
             'tp': e - rr * riesgo if side == 'short' else e + rr * riesgo,
             'riesgo': riesgo, 'riesgo_pct': riesgo / e,
             'nivel': piso if side == 'short' else techo}
        if side == 'short':
            pos_short = p
        else:
            pos_long = p
        return True

    def gestionar(p, i, v):
        if p is None or i <= p['i']:
            return p
        side = p['side']
        hit_sl = v['high'] >= p['sl'] if side == 'short' else v['low'] <= p['sl']
        hit_tp = v['low'] <= p['tp'] if side == 'short' else v['high'] >= p['tp']
        cerrado = 'SL' if hit_sl else ('TP' if hit_tp else None)   # si ambos, pierde
        if not cerrado:
            return p
        salida = p['tp'] if cerrado == 'TP' else p['sl']
        bruto = rr if cerrado == 'TP' else -1
        fee_r = (FEE_ENTRY * p['entry'] + FEE_EXIT * salida) / p['riesgo']
        p.update(salida_time=v['dt'], resultado=cerrado, R=bruto - fee_r)
        if corte is None or p['dt'] >= corte:
            trades.append(p)
        return None

    for i, v in df.iterrows():
        rsi, hi, lo = v['rsi'], v['high'], v['low']
        if pd.isna(rsi):
            continue
        pos_long = gestionar(pos_long, i, v)
        pos_short = gestionar(pos_short, i, v)

        # SL dinámico: sigue el extremo del rebote/retroceso hasta la entrada
        if sl_ext is not None:
            if estado.startswith('bear'):
                sl_ext = max(sl_ext, hi)
            elif estado.startswith('bull'):
                sl_ext = min(sl_ext, lo)

        # --- entradas (un slot por lado: nunca dos del mismo lado) ---
        if sl_ext is not None:
            if (estado == 'bear_entrada' and rsi <= OS and pos_short is None
                    and permiso_venta and 'short' in lados):
                regimen_ok = (not filtro_1h) or v['h1regime'] == 'bear'
                reclaim_ok = (not filtro_1h) or bool(v['h1reclaim_down'])
                nivel_ok = (not estructural) or lo >= piso   # higher low
                if nivel_ok and regimen_ok and reclaim_ok:
                    if not abrir('short', i, v):
                        estado = 'bear_rebote'
            elif (estado == 'bull_entrada' and rsi >= OB and pos_long is None
                  and permiso_compra and 'long' in lados):
                regimen_ok = (not filtro_1h) or v['h1regime'] == 'bull'
                reclaim_ok = (not filtro_1h) or bool(v['h1reclaim_up'])
                nivel_ok = (not estructural) or hi <= techo  # lower high
                if nivel_ok and regimen_ok and reclaim_ok:
                    if not abrir('long', i, v):
                        estado = 'bull_retro'

        # --- fin de un run (el RSI cruza la línea media) ---
        nuevo_lado = 'up' if rsi >= MID else 'down'
        if lado is None:
            lado, run_hi, run_lo = nuevo_lado, hi, lo
            run_hi_i = run_lo_i = i
            run_ob, run_os = rsi >= OB, rsi <= OS
        elif nuevo_lado != lado:
            if lado == 'down':
                if run_os:                    # episodio de SOBREVENTA -> patrón de COMPRA
                    piso = run_lo
                    estado = 'bear_rebote'
                    sl_ext = hi               # el rebote arranca aquí
                    permiso_compra = permiso('compra', run_lo_i)
                elif estado == 'bull_retro':  # retroceso alcista sin tocar sobreventa
                    estado = 'bull_entrada'
            else:
                if run_ob:                    # episodio de SOBRECOMPRA -> patrón de VENTA
                    techo = run_hi
                    estado = 'bull_retro'
                    sl_ext = lo               # el retroceso arranca aquí
                    permiso_venta = permiso('venta', run_hi_i)
                elif estado == 'bear_rebote':  # rebote bajista sin tocar sobrecompra
                    estado = 'bear_entrada'
            lado, run_hi, run_lo = nuevo_lado, hi, lo
            run_hi_i = run_lo_i = i
            run_ob, run_os = rsi >= OB, rsi <= OS
        else:
            if hi > run_hi:
                run_hi, run_hi_i = hi, i
            if lo < run_lo:
                run_lo, run_lo_i = lo, i
            run_ob = run_ob or rsi >= OB
            run_os = run_os or rsi <= OS

    # Señales aún VIVAS al final (las que el operador puede tomar ahora mismo)
    for p in (pos_long, pos_short):
        if p is not None and (corte is None or p['dt'] >= corte):
            p.update(salida_time=None, resultado='ABIERTA', R=None)
            trades.append(p)

    trades.sort(key=lambda t: t['dt'])
    return trades, descartados


def desde_ancla(precio_ancla, t_ancla, symbol=SYMBOL, cutoff=None,
                lados=("long", "short"), estructural=False, filtro_1h=False, rr=RR):
    """Aplica la rsi_3m desde el ancla que marcó el operador."""
    t_ancla = pd.Timestamp(t_ancla)
    desde = t_ancla - pd.Timedelta(days=DIAS_WARMUP)
    df = cargar_3m(symbol, desde, cutoff)
    if not len(df):
        return [], 0, None
    trades, descartados = senales(df, lados, estructural, filtro_1h, rr, desde=t_ancla)
    return trades, descartados, df
