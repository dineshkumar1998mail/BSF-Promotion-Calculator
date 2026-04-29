import streamlit as st
import pandas as pd
import numpy as np
from pandas.tseries.offsets import MonthEnd

st.set_page_config(page_title="BSF Officer Promotion & Seniority Calculator", layout="wide")

@st.cache_data
def load_data():
    # Ensure your CSV is named 'gradation_list.csv'
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
    
    # --- NATURAL SENIORITY CALCULATION (NORMAL MODEL) ---
    # Total natural retirements before target's retirement date
    nat_retirements_total = len(seniors[seniors['Retirement_Date'] <= target_ret])
    final_seniority_normal = initial_rank - nat_retirements_total

    # Future pool for sim (Retiring after today, 30-04-2026)
    future_seniors_raw = seniors[seniors['Retirement_Date'] > '2026-04-30'].copy()
    raw_future_rets = future_seniors_raw['Retirement_Date'].sort_values().reset_index(drop=True)

    # 1. Normal Column Promotion Dates
    promo_normal = {}
    # Count how many have already retired Jan-Apr 2026
    already_retired = len(seniors[(seniors['Retirement_Date'] >= '2026-01-01') & (seniors['Retirement_Date'] <= '2026-04-30')])
    adj_start_normal = max(1, initial_rank - already_retired)

    for rank in ['DC', '2IC', 'COMDT', 'DIG', 'IG', 'ADG']:
        needed = adj_start_normal - baseline_thresh[rank]
        if needed <= 0: promo_normal[rank] = "Already Achieved"
        elif needed > len(raw_future_rets): promo_normal[rank] = "Will not achieve"
        else:
            date = raw_future_rets.iloc[needed - 1]
            promo_normal[rank] = date.strftime('%d-%m-%y') if date <= target_ret else "Will not achieve"

    # 2. Dynamic VRS Simulation (As defined previously)
    def run_dynamic_vrs_sim(thresholds, start_rank):
        np.random.seed(42)
        active_seniors = future_seniors_raw.copy()
        current_date = pd.Timestamp('2026-05-01')
        promo_dates = {}
        annual_vrs_rate = 50.0
        decay_factor = 0.95 
        
        while current_date <= target_ret and not active_seniors.empty:
            m_end = current_date + MonthEnd(0)
            active_seniors = active_seniors[active_seniors['Retirement_Date'] > m_end]
            if current_date.month == 1: annual_vrs_rate *= decay_factor
            monthly_vrs_goal = annual_vrs_rate / 12.0
            n_to_drop = int(np.floor(monthly_vrs_goal + np.random.random()))
            if n_to_drop > 0:
                drop_idx = np.random.choice(active_seniors.index, min(n_to_drop, len(active_seniors)), replace=False)
                active_seniors = active_seniors.drop(drop_idx)
            rank_pos = len(active_seniors) + 1
            for r, t in thresholds.items():
                if r not in promo_dates and rank_pos <= t:
                    promo_dates[r] = m_end.strftime('%d-%m-%y')
            current_date = (current_date + pd.DateOffset(months=1)).replace(day=1)
        return promo_dates, (len(active_seniors) + 1)

    promo_vrs, vrs_final_sen = run_dynamic_vrs_sim(baseline_thresh, adj_start_normal)

    # Yearly Tracker
    seniority_tracker = {}
    for y in range(2027, target_ret.year + 1):
        jan1 = pd.Timestamp(year=y, month=1, day=1)
        rets = len(seniors[seniors['Retirement_Date'] < jan1])
        seniority_tracker[str(y)] = initial_rank - rets

    return promo_normal, promo_vrs, seniority_tracker, final_seniority_normal, vrs_final_sen

# --- UI Layout ---
st.title("🛡️ BSF Seniority & Promotion Calculator")
df = load_data()
irla = st.text_input("Enter IRLA Number:")

if irla:
    res = df[df['IRLA No'] == str(irla).strip()]
    if not res.empty:
        target = res.iloc[0]
        st.header(f"Officer: {target['Name']}")
        
        p_norm, p_vrs, s_track, f_norm, f_vrs = calculate_scenarios(df, target['S. No'], target['Retirement_Date'])
        
        st.subheader("📈 Promotion Projections")
        st.table(pd.DataFrame({'Normal (Age-60)': p_norm, 'VRS Model': p_vrs}).reindex(['DC', '2IC', 'COMDT', 'DIG', 'IG', 'ADG']))

        st.divider()
        col1, col2 = st.columns(2)
        # DISPLAY FINAL SENIORITY FOR NORMAL MODEL
        col1.metric("Final Seniority (Normal Model)", f"Rank #{max(1, int(f_norm))}")
        col2.metric("Final Seniority (VRS Model)", f"Rank #{max(1, int(f_vrs))}")
        
        st.subheader("📅 Seniority Tracker (Normal Model)")
        st.dataframe(pd.DataFrame(list(s_track.items()), columns=['Year', 'Seniority Pos']).set_index('Year').T)
