import pandas as pd

def get_bullish_poc(df, start_idx, end_idx):
    start_idx = int(start_idx)
    current_end = int(end_idx)
    origin_low = df.loc[start_idx, 'low']
    
    while current_end > start_idx:
        swings = []
        df_segment = df.loc[start_idx:current_end]
        
        max_seen = df_segment.loc[start_idx, 'high']
        peak_idx = start_idx
        
        min_low_since_max = float('inf')
        min_low_idx = -1
        
        for j in range(start_idx + 1, current_end):
            curr_high = df_segment.loc[j, 'high']
            if curr_high > max_seen:
                max_seen = curr_high
                peak_idx = j
                
                min_low_since_max = float('inf')
                min_low_idx = -1
            else:
                curr_low = df_segment.loc[j, 'low']
                if curr_low < min_low_since_max:
                    min_low_since_max = curr_low
                    min_low_idx = j
                    
                drop = max_seen - min_low_since_max
                if drop > 0 and min_low_idx != -1:
                    swings.append({
                        'peak': max_seen,
                        'trough': min_low_since_max,
                        'drop': drop,
                        'peak_idx': peak_idx,
                        'trough_idx': min_low_idx
                    })
                
        if not swings: return None
        
        swings_df = pd.DataFrame(swings).sort_values(by='drop', ascending=False)
        biggest = swings_df.iloc[0]
        
        abs_max_val = df.loc[current_end, 'high']
        req_break = biggest['drop'] / 3.0
        actual_break = abs_max_val - biggest['peak']
        
        if actual_break >= req_break:
            res = biggest.to_dict()
            res['type'] = 'POC'
            return res
        else:
            total_rise = biggest['peak'] - origin_low
            if total_rise > 0 and biggest['drop'] >= total_rise * 0.618:
                return {
                    'type': 'RESET',
                    'trough': biggest['trough'],
                    'trough_idx': biggest['trough_idx']
                }
            
            current_end = int(biggest['peak_idx'])
            if current_end <= start_idx: break
            
    return None

def get_bearish_poc(df, start_idx, end_idx):
    start_idx = int(start_idx)
    current_end = int(end_idx)
    origin_high = df.loc[start_idx, 'high']
    
    while current_end > start_idx:
        swings = []
        df_segment = df.loc[start_idx:current_end]
        
        min_seen = df_segment.loc[start_idx, 'low']
        trough_idx = start_idx
        
        max_high_since_min = -float('inf')
        max_high_idx = -1
        
        for j in range(start_idx + 1, current_end):
            curr_low = df_segment.loc[j, 'low']
            if curr_low < min_seen:
                min_seen = curr_low
                trough_idx = j
                
                max_high_since_min = -float('inf')
                max_high_idx = -1
            else:
                curr_high = df_segment.loc[j, 'high']
                if curr_high > max_high_since_min:
                    max_high_since_min = curr_high
                    max_high_idx = j
                    
                bounce = max_high_since_min - min_seen
                if bounce > 0 and max_high_idx != -1:
                    swings.append({
                        'peak': max_high_since_min,
                        'trough': min_seen,
                        'bounce': bounce,
                        'peak_idx': max_high_idx,
                        'trough_idx': trough_idx
                    })
                
        if not swings: return None
        
        swings_df = pd.DataFrame(swings).sort_values(by='bounce', ascending=False)
        biggest = swings_df.iloc[0]
        
        abs_min_val = df.loc[current_end, 'low']
        req_break = biggest['bounce'] / 3.0
        actual_break = biggest['trough'] - abs_min_val
        
        if actual_break >= req_break:
            res = biggest.to_dict()
            res['type'] = 'POC'
            return res
        else:
            total_drop = origin_high - biggest['trough']
            if total_drop > 0 and biggest['bounce'] >= total_drop * 0.618:
                return {
                    'type': 'RESET',
                    'peak': biggest['peak'],
                    'peak_idx': biggest['peak_idx']
                }
                
            current_end = int(biggest['trough_idx'])
            if current_end <= start_idx: break
            
    return None
