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
    seniors = df[df['S. No'] < target_sno].copy()
    initial_rank = len(seniors) + 1
    
    baseline_thresh = {'ADG': 1, 'IG': 22, 'DIG': 181, 'COMDT': 554, '2IC': 1143, 'DC': 2452}
    cr_thresh = {'ADG': 1, 'IG': 33, 'DIG': 223, 'COMDT': 825, '2IC': 1698, 'DC': 2910}
    
    anchors = {'COMDT': '19975597', '2IC': '10694886', 'DC': '11323334'}
    anchor_snos = {k: int(df[df['IRLA No'] == v].iloc[0]['S. No']) if not df[df['IRLA No'] == v].empty else 0 for k, v in anchors.items()}

    # Natural clearance Jan-Apr 2026
    nat_clearance = len(seniors[(seniors['Retirement_Date'] >= '2026-01-01') & (seniors['Retirement_Date'] <= '2026-04-30')])
    adj_rank_start = max(1, initial_rank - nat_clearance)

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
            promo_normal[rank] = date.strftime('%d-%m-%y') if date <= target_ret else "Will not achieve"

    # --- DYNAMIC DECAY VRS SIMULATION ---
    def run_dynamic_vrs_sim(thresholds, start_rank):
        np.random.seed(42)
        active_seniors = future_seniors_raw.copy()
        current_date = pd.Timestamp('2026-05-01')
        promo_dates = {}
        
        # Initial Anchor Check
        for r, t in thresholds.items():
            if r in anchor_snos and target_sno <= anchor_snos[r]: promo_dates[r] = "Already Achieved"
            elif start_rank <= t: promo_dates[r] = "Already Achieved"

        annual_vrs_rate = 50.0
        decay_factor = 0.95 # 5% reduction per year
        
        while current_date <= target_ret and len(active_seniors) >= 0:
            m_end = current_date + MonthEnd(0)
            
            # A. Natural Retirements this month
            active_seniors = active_seniors[active_seniors['Retirement_Date'] > m_end]
            
            # B. Dynamic VRS Attrition
            if current_date.month == 1:
                annual_vrs_rate *= decay_factor # Reduce VRS pool every year
            
            monthly_vrs_goal = annual_vrs_rate / 12.0
            
            # Distribute proportionally across senior ranks
            if not active_seniors.empty:
                n_to_drop = int(np.floor(monthly_vrs_goal + np.random.random()))
                if n_to_drop > 0:
                    drop_idx = np.random.choice(active_seniors.index, min(n_to_drop, len(active_seniors)), replace=False)
                    active_seniors = active_seniors.drop(drop_idx)
            
            # C. Check Promotion
            rank_pos = len(active_seniors) + 1
            for r, t in thresholds.items():
                if r not in promo_dates and rank_pos <= t:
                    promo_dates[r] = m_end.strftime('%d-%m-%y')
            
            if rank_pos <= 1: break
            current_date = (current_date + pd.DateOffset(months=1)).replace(day=1)
            
        return promo_dates, (len(active_seniors) + 1)

    promo_vrs_no_cr, vrs_final_sen = run_dynamic_vrs_sim(baseline_thresh, adj_rank_start)
    promo_cr, cr_final_sen = run_dynamic_vrs_sim(cr_thresh, adj_rank_start)

    # Seniority Calculation (Baseline)
    seniority = {}
    for y in range(2027, target_ret.year + 1):
        jan1 = pd.Timestamp(year=y, month=1, day=1)
        rets = (raw_future_rets < jan1).sum()
        seniority[str(y)] = adj_rank_start - rets
    
    return {'Normal': promo_normal, 'VRS (No CR)': promo_vrs_no_cr, 'With CR': promo_cr, 'CR + VRS': promo_cr}, seniority, vrs_final_sen

# --- UI ---
st.title("🛡️ BSF Officer Promotion & Seniority Calculator")
df = load_data()
irla_input = st.text_input("Enter IRLA Number:")

if irla_input:
    off = df[df['IRLA No'] == str(irla_input).strip()]
    if not off.empty:
        target = off.iloc[0]
        st.header(f"Profile: {target['Name']}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current Rank", target['Rank'])
        c2.metric("S.No", int(target['S. No']))
        c3.metric("DOB", target['DOB'].strftime('%d-%m-%y'))
        c4.metric("Retirement", target['Retirement_Date'].strftime('%d-%m-%y'))
        
        promos, sens, final_vrs = calculate_scenarios(df, target['S. No'], target['Retirement_Date'])
        
        st.divider()
        st.subheader("📈 Projected Promotion Dates")
        st.table(pd.DataFrame(promos).reindex(['DC', '2IC', 'COMDT', 'DIG', 'IG', 'ADG']))
        
        st.divider()
        st.metric("Final Seniority (VRS Simulation)", f"Rank #{max(1, int(final_vrs))}")
        
        st.divider()
        st.subheader("📅 Seniority Tracker (Jan 1st)")
        st.dataframe(pd.DataFrame(list(sens.items()), columns=['Year', 'Seniority Pos']).set_index('Year').T)
