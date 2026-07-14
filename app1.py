import streamlit as st
import pandas as pd
import numpy as np
from pandas.tseries.offsets import MonthEnd
import datetime

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
    
    # --- LIVE PRODUCTION REALITY ANCHORS ---
    anchors = {'COMDT': '19975610', '2IC': '10694886', 'DC': '41427187'}
    
    # Resolve Anchor IRLAs to their current S.No positions
    anchor_snos = {}
    for rank, irla_val in anchors.items():
        match = df[df['IRLA No'] == irla_val]
        if not match.empty:
            anchor_snos[rank] = int(match.iloc[0]['S. No'])
        else:
            fallback_thresh = {'COMDT': 554, '2IC': 1143, 'DC': 2452}
            anchor_snos[rank] = fallback_thresh[rank]

    current_today = pd.Timestamp(datetime.date.today())

    # Structural Gate Positions (Absolute Pyramidal Capacities)
    baseline_capacities = {'ADG': 1, 'IG': 22, 'DIG': 181, 'COMDT': 554, '2IC': 1143, 'DC': 2452}
    cr_capacities = {'ADG': 1, 'IG': 33, 'DIG': 223, 'COMDT': 825, '2IC': 1698, 'DC': 2910}

    # --- 1. FIXED PURE RETIREMENTS COLUMN (NORMAL) ---
    active_seniors_normal = df[(df['S. No'] < target_sno) & (df['Retirement_Date'] > current_today)].copy()
    raw_future_rets = active_seniors_normal['Retirement_Date'].sort_values().reset_index(drop=True)
    
    rem_seniors_retiring_before_target = len(active_seniors_normal[active_seniors_normal['Retirement_Date'] <= target_ret])
    final_sen_normal = (len(active_seniors_normal) + 1) - rem_seniors_retiring_before_target

    promo_normal = {}
    for rank in ['DC', '2IC', 'COMDT', 'DIG', 'IG', 'ADG']:
        if rank in anchor_snos and target_sno <= anchor_snos[rank]:
            promo_normal[rank] = "Already Achieved"
        else:
            anchor_ref = anchor_snos.get(rank, baseline_capacities[rank])
            effective_rank_pos = target_sno - anchor_ref
            
            if effective_rank_pos <= 0:
                promo_normal[rank] = "Already Achieved"
            elif effective_rank_pos > len(raw_future_rets):
                promo_normal[rank] = "Will not achieve"
            else:
                date = raw_future_rets.iloc[effective_rank_pos - 1]
                promo_normal[rank] = date.strftime('%d-%b-%Y') if date <= target_ret else "Will not achieve"

    # --- 2. THE DYNAMIC ATTRITION SIMULATION ENGINE ---
    def run_simulation(capacities, use_vrs=True, is_cr=False):
        np.random.seed(42)
        sim_pool = df[(df['S. No'] < target_sno) & (df['Retirement_Date'] > current_today)].copy()
        initial_pool_size = max(1, len(sim_pool))
        
        sim_date = (current_today + pd.DateOffset(months=1)).replace(day=1)
        promo_dates = {}
        
        # Calculate dynamic gates ahead of loop execution
        effective_gates = {}
        for r, cap in capacities.items():
            base_anchor = anchor_snos.get(r, baseline_capacities[r])
            if is_cr:
                # Expand the gate dynamically based on how much structural growth the rank got
                expansion_bonus = capacities[r] - baseline_capacities[r]
                effective_gates[r] = base_anchor + expansion_bonus
            else:
                effective_gates[r] = base_anchor

        # Initial Boundary Enforcement
        for r, gate in effective_gates.items():
            if target_sno <= gate:
                promo_dates[r] = "Already Achieved"

        while sim_date <= target_ret and not sim_pool.empty:
            m_end = sim_date + MonthEnd(0)
            
            # 1. Clear Natural Retirements
            sim_pool = sim_pool[sim_pool['Retirement_Date'] > m_end]
            
            # 2. Apply Proportional Attrition (Linked accurately to the active pool length)
            if use_vrs and not sim_pool.empty:
                current_vrs_annual = 50.0 * (len(sim_pool) / initial_pool_size)
                monthly_vrs_goal = current_vrs_annual / 12.0
                n_vrs = int(np.floor(monthly_vrs_goal + np.random.random()))
                
                if n_vrs > 0:
                    vrs_idx = np.random.choice(sim_pool.index, min(n_vrs, len(sim_pool)), replace=False)
                    sim_pool = sim_pool.drop(vrs_idx)
            
            # 3. Dynamic Absolute Index Calculation
            sim_progress = initial_pool_size - len(sim_pool)
            current_absolute_sno = target_sno - sim_progress
            
            for r, gate in effective_gates.items():
                if r not in promo_dates:
                    if current_absolute_sno <= gate:
                        promo_dates[r] = m_end.strftime('%d-%b-%Y')
            
            if current_absolute_sno <= 1:
                break
            sim_date = (sim_date + pd.DateOffset(months=1)).replace(day=1)
            
        # Complete unreached fields cleanly
        for r, gate in effective_gates.items():
            if r not in promo_dates:
                promo_dates[r] = "Already Achieved" if target_sno <= gate else "Will not achieve"
                
        return promo_dates, max(1, len(sim_pool) + 1)

    # Compute clean, isolated models
    promo_vrs_only, vrs_final_sen = run_simulation(baseline_capacities, use_vrs=True, is_cr=False)
    promo_cr_only, _ = run_simulation(cr_capacities, use_vrs=False, is_cr=True)
    promo_cr_vrs, _ = run_simulation(cr_capacities, use_vrs=True, is_cr=True)

    # Tracker Logic (Baseline Normal)
    seniority_tracker = {}
    for y in range(current_today.year + 1, target_ret.year + 1):
        jan1 = pd.Timestamp(year=y, month=1, day=1)
        rets_before_jan1 = (raw_future_rets < jan1).sum()
        current_relative_rank = (len(active_seniors_normal) + 1) - rets_before_jan1
        seniority_tracker[str(y)] = max(1, current_relative_rank)
    
    return {'Normal': promo_normal, 
            'VRS (No CR)': promo_vrs_only, 
            'With CR': promo_cr_only, 
            'CR + VRS': promo_cr_vrs}, seniority_tracker, vrs_final_sen, final_sen_normal

# --- UI LAYER ---
st.title("🛡️ BSF Officers Promotion Model")
df = load_data()

arla = st.text_input("Enter IRLA Number:")

if arla:
    res = df[df['IRLA No'] == str(arla).strip()]
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
        st.subheader("📈 Proportional Promotion Projections")
        st.table(pd.DataFrame(promos).reindex(['DC', '2IC', 'COMDT', 'DIG', 'IG', 'ADG']))
        
        st.divider()
        c_a, c_b = st.columns(2)
        c_a.metric("Final Seniority (Normal Model)", f"Rank #{max(1, int(f_norm))}")
        c_b.metric("Final Seniority (VRS Model)", f"Rank #{max(1, int(f_vrs))}")
        
        st.divider()
        st.subheader("📅 Seniority Tracker (Jan 1st - Normal Model)")
        if sens:
            st.dataframe(pd.DataFrame(list(sens.items()), columns=['Year', 'Seniority Pos']).set_index('Year').T)
        else:
            st.write("Retirement falls within the current calendar year.")
