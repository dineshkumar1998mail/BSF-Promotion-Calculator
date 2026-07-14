import streamlit as st
import pandas as pd
import numpy as np
from pandas.tseries.offsets import MonthEnd

st.set_page_config(page_title="BSF Officers Promotion Model", layout="wide")

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
    seniors = df[df['S. No'] < target_sno].copy()
    initial_rank = len(seniors) + 1
    
    baseline_thresh = {'ADG': 1, 'IG': 22, 'DIG': 181, 'COMDT': 554, '2IC': 1143, 'DC': 2452}
    cr_thresh = {'ADG': 1, 'IG': 33, 'DIG': 223, 'COMDT': 825, '2IC': 1698, 'DC': 2910}
    
    # Anchors for Reality Check (As of 08-july-2026)
    anchors = {'COMDT': '19975580', '2IC': '10694886', 'DC': '41427187'}
    anchor_snos = {k: int(df[df['IRLA No'] == v].iloc[0]['S. No']) if not df[df['IRLA No'] == v].empty else 0 for k, v in anchors.items()}

    # Natural Seniority (Normal Model)
    nat_ret_total = len(seniors[seniors['Retirement_Date'] <= target_ret])
    final_sen_normal = initial_rank - nat_ret_total

    # Start Point Adjustments (Natural clearance Jan-Apr 2026)
    nat_clr_jan_apr = len(seniors[(seniors['Retirement_Date'] >= '2026-01-01') & (seniors['Retirement_Date'] <= '2026-04-30')])
    adj_rank_start = max(1, initial_rank - nat_clr_jan_apr)

    future_seniors_raw = seniors[seniors['Retirement_Date'] > '2026-04-30'].copy()
    raw_future_rets = future_seniors_raw['Retirement_Date'].sort_values().reset_index(drop=True)

    # 1. Normal Column
    promo_normal = {}
    for rank in ['DC', '2IC', 'COMDT', 'DIG', 'IG', 'ADG']:
        needed = adj_rank_start - baseline_thresh[rank]
        if needed <= 0: promo_normal[rank] = "Already Achieved"
        elif needed > len(raw_future_rets): promo_normal[rank] = "Will not achieve"
        else:
            date = raw_future_rets.iloc[needed - 1]
            promo_normal[rank] = date.strftime('%d-%b-%Y') if date <= target_ret else "Will not achieve"

    # --- RECTIFIED ATTRITION SIMULATION ---
    def run_attrition_sim(thresholds, use_vrs=True):
        np.random.seed(42)
        working_pool = future_seniors_raw.copy()
        current_date = pd.Timestamp('2026-05-01')
        promo_dates = {}
        
        # Initial Anchor Check
        for r, t in thresholds.items():
            if r in anchor_snos and target_sno <= anchor_snos[r]: promo_dates[r] = "Already Achieved"
            elif adj_rank_start <= t: promo_dates[r] = "Already Achieved"

        initial_seniors_count = len(working_pool)
        
        while current_date <= target_ret and not working_pool.empty:
            m_end = current_date + MonthEnd(0)
            
            # Step A: Natural Retirements (Age 60)
            working_pool = working_pool[working_pool['Retirement_Date'] > m_end]
            
            # Step B: Cadre-Linked VRS (Reducing as cadre shrinks)
            if use_vrs and not working_pool.empty:
                current_vrs_annual = 50.0 * (len(working_pool) / initial_seniors_count)
                monthly_vrs_goal = current_vrs_annual / 12.0
                n_vrs = int(np.floor(monthly_vrs_goal + np.random.random()))
                
                if n_vrs > 0:
                    # Officers removed here cannot be counted as natural retirements later (No double-counting)
                    vrs_indices = np.random.choice(working_pool.index, min(n_vrs, len(working_pool)), replace=False)
                    working_pool = working_pool.drop(vrs_indices)
            
            # Step C: Rank Calculation
            rank_pos = len(working_pool) + 1
            for r, t in thresholds.items():
                if r not in promo_dates and rank_pos <= t:
                    promo_dates[r] = m_end.strftime('%d-%b-%Y')
            
            if rank_pos <= 1: break
            current_date = (current_date + pd.DateOffset(months=1)).replace(day=1)
            
        return promo_dates, (len(working_pool) + 1)

    promo_vrs_only, vrs_final_sen = run_attrition_sim(baseline_thresh, use_vrs=True)
    promo_cr_only, _ = run_attrition_sim(cr_thresh, use_vrs=False)
    promo_cr_vrs, _ = run_attrition_sim(cr_thresh, use_vrs=True)

    # Tracker Logic (Baseline)
    seniority_tracker = {}
    for y in range(2027, target_ret.year + 1):
        jan1 = pd.Timestamp(year=y, month=1, day=1)
        rets = (raw_future_rets < jan1).sum()
        seniority_tracker[str(y)] = adj_rank_start - rets
    
    return {'Normal': promo_normal, 
            'VRS (No CR)': promo_vrs_only, 
            'With CR': promo_cr_only, 
            'CR + VRS': promo_cr_vrs}, seniority_tracker, vrs_final_sen, final_sen_normal

# --- UI ---
st.title("🛡️ BSF Officers Promotion Model")
df = load_data()
irla = st.text_input("Enter IRLA Number:")

if irla:
    res = df[df['IRLA No'] == str(irla).strip()]
    if not res.empty:
        target = res.iloc[0]
        st.header(f"Officer: {target['Name']}")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current Rank", target['Rank'])
        c2.metric("S.No", int(target['S. No']))
        c3.metric("DOB", target['DOB'].strftime('%d-%b-%Y'))
        c4.metric("Retirement", target['Retirement_Date'].strftime('%d-%b-%Y'))
        
        promos, sens, f_vrs, f_norm = calculate_scenarios(df, target['S. No'], target['Retirement_Date'])
        
        st.divider()
        st.subheader("📈 Rectified Promotion Projections")
        st.table(pd.DataFrame(promos).reindex(['DC', '2IC', 'COMDT', 'DIG', 'IG', 'ADG']))
        
        st.divider()
        c_a, c_b = st.columns(2)
        c_a.metric("Final Seniority (Normal Model)", f"Rank #{max(1, int(f_norm))}", help="Based purely on natural age-60 retirements.")
        c_b.metric("Final Seniority (VRS Model)", f"Rank #{max(1, int(f_vrs))}", help="VRS rate reduces as cadre shrinks; no double-counting of future retirements.")
        
        st.divider()
        st.subheader("📅 Seniority Tracker (Jan 1st - Normal Model)")
        st.dataframe(pd.DataFrame(list(sens.items()), columns=['Year', 'Seniority Pos']).set_index('Year').T)
