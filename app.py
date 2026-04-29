import streamlit as st
import pandas as pd
import numpy as np
from pandas.tseries.offsets import MonthEnd

st.set_page_config(page_title="BSF Officer Promotion & Seniority Calculator", layout="wide")

@st.cache_data
def load_data():
    df = pd.read_csv('gradation_list.csv')
    df['S. No'] = pd.to_numeric(df['S. No'], errors='coerce')
    df = df.dropna(subset=['S. No'])
    df['DOB'] = pd.to_datetime(df['Date of Birth'], errors='coerce')
    df = df.dropna(subset=['DOB'])
    df = df.sort_values('S. No').reset_index(drop=True)
    df['Retirement_Date'] = df['DOB'] + pd.DateOffset(years=60) + MonthEnd(0)
    df['IRLA No'] = df['IRLA No'].astype(str).str.strip()
    return df

def calculate_scenarios(df, target_sno, target_ret):
    target_sno = int(target_sno)
    
    baseline_thresh = {'ADG': 1, 'IG': 22, 'DIG': 181, 'COMDT': 554, '2IC': 1143, 'DC': 2452}
    cr_thresh = {'ADG': 1, 'IG': 33, 'DIG': 223, 'COMDT': 825, '2IC': 1698, 'DC': 2910}
    
    # --- REALITY TRUE-UP ENGINE (April 30, 2026) ---
    # Finds the S.No of IRLA 11323334 and converts all "extras" above capacity into Historical VRS
    df_base = df.copy()
    df_cr = df.copy()
    
    last_dc_df = df[df['IRLA No'] == '11323334']
    historical_vrs_cr = 0
    historical_vrs_base = 0
    
    if not last_dc_df.empty:
        last_dc_sno = int(last_dc_df['S. No'].iloc[0])
        np.random.seed(42) # Ensure historical drops are exactly identical every time
        
        # 1. Base Model True-up
        if last_dc_sno > baseline_thresh['DC']:
            historical_vrs_base = last_dc_sno - baseline_thresh['DC']
            # Protect the target officer from being accidentally dropped
            pool_base = df_base[(df_base['S. No'] <= last_dc_sno) & (df_base['S. No'] != target_sno)]
            if historical_vrs_base > 0 and len(pool_base) > historical_vrs_base:
                drop_idx = np.random.choice(pool_base.index, historical_vrs_base, replace=False)
                df_base = df_base.drop(drop_idx)
                
        # 2. CR Model True-up
        if last_dc_sno > cr_thresh['DC']:
            historical_vrs_cr = last_dc_sno - cr_thresh['DC']
            pool_cr = df_cr[(df_cr['S. No'] <= last_dc_sno) & (df_cr['S. No'] != target_sno)]
            if historical_vrs_cr > 0 and len(pool_cr) > historical_vrs_cr:
                drop_idx = np.random.choice(pool_cr.index, historical_vrs_cr, replace=False)
                df_cr = df_cr.drop(drop_idx)

    # Calculate True Initial Ranks
    seniors_base = df_base[df_base['S. No'] < target_sno].copy()
    retirements_base = seniors_base['Retirement_Date'].dropna().sort_values().reset_index(drop=True)
    initial_rank_base = len(seniors_base) + 1
    
    seniors_cr = df_cr[df_cr['S. No'] < target_sno].copy()
    retirements_cr = seniors_cr['Retirement_Date'].dropna().sort_values().reset_index(drop=True)
    initial_rank_cr = len(seniors_cr) + 1

    results = {}
    rank_order = ['DC', '2IC', 'COMDT', 'DIG', 'IG', 'ADG']
    
    # --- 1. Normal (Baseline) ---
    promo_normal = {}
    for rank in rank_order:
        needed = initial_rank_base - baseline_thresh[rank]
        if needed <= 0:
            promo_normal[rank] = "Already Achieved"
        elif needed > len(retirements_base):
            promo_normal[rank] = "Will not achieve"
        else:
            date = retirements_base.iloc[needed - 1]
            promo_normal[rank] = date.date() if date <= target_ret else "Will not achieve"
    results['Normal'] = promo_normal
    
    # --- 2. VRS (No CR) ---
    np.random.seed(42) # Reset seed for future simulation
    active_rets_base = seniors_base['Retirement_Date'].dropna().values.copy()
    current_date = pd.Timestamp('2026-05-01')
    acc_comdt_b = 0.0; acc_2ic_b = 0.0; acc_dc_b = 0.0; acc_ac_b = 0.0
    promo_base_vrs = {}
    
    for rank, thresh in baseline_thresh.items():
        if initial_rank_base <= thresh:
            promo_base_vrs[rank] = "Already Achieved"
            
    while current_date <= target_ret:
        month_end = current_date + MonthEnd(0)
        active_rets_base = active_rets_base[active_rets_base > np.datetime64(month_end)]
        n_seniors = len(active_rets_base)
        rank_pos = n_seniors + 1
        
        for rank, thresh in baseline_thresh.items():
            if rank not in promo_base_vrs and rank_pos <= thresh:
                promo_base_vrs[rank] = month_end.date()
                
        if rank_pos <= 1: break
        
        s_comdt = min(n_seniors, baseline_thresh['COMDT'])
        s_2ic = max(0, min(n_seniors, baseline_thresh['2IC']) - baseline_thresh['COMDT'])
        s_dc = max(0, min(n_seniors, baseline_thresh['DC']) - baseline_thresh['2IC'])
        s_ac = max(0, n_seniors - baseline_thresh['DC'])

        acc_comdt_b += (5.0/12.0) * (s_comdt/baseline_thresh['COMDT']) if baseline_thresh['COMDT'] else 0
        acc_2ic_b += (10.0/12.0) * (s_2ic/589.0)
        acc_dc_b += (20.0/12.0) * (s_dc/1309.0)
        acc_ac_b += (40.0/12.0) * (s_ac/1528.0)
        
        drops = int(acc_comdt_b) + int(acc_2ic_b) + int(acc_dc_b) + int(acc_ac_b)
        
        acc_comdt_b -= int(acc_comdt_b)
        acc_2ic_b -= int(acc_2ic_b)
        acc_dc_b -= int(acc_dc_b)
        acc_ac_b -= int(acc_ac_b)
        
        if drops > 0 and len(active_rets_base) > 0:
            indices = np.random.choice(range(len(active_rets_base)), min(drops, len(active_rets_base)), replace=False)
            active_rets_base = np.delete(active_rets_base, indices)
