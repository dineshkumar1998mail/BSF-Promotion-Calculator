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
    rank_order = ['DC', '2IC', 'COMDT', 'DIG', 'IG', 'ADG']
    
    # --- TRIPLE ANCHOR DEFINITIONS ---
    anchors = {
        'COMDT': '19975597',
        '2IC': '10694886',
        'DC': '11323334'
    }
    anchor_snos = {k: int(df[df['IRLA No'] == v].iloc[0]['S. No']) if not df[df['IRLA No'] == v].empty else 0 for k, v in anchors.items()}

    # Calculate Natural Retirements Jan-Apr 2026
    nat_clearance = len(seniors[(seniors['Retirement_Date'] >= '2026-01-01') & (seniors['Retirement_Date'] <= '2026-04-30')])
    vrs_drop_total = 50 

    adj_rank_normal = max(1, initial_rank - nat_clearance)
    adj_rank_sim = max(1, initial_rank - nat_clearance - vrs_drop_total)

    future_seniors = seniors[seniors['Retirement_Date'] > '2026-04-30'].copy()
    raw_future_rets = future_seniors['Retirement_Date'].sort_values().reset_index(drop=True)

    # 1. Normal (Baseline)
    promo_normal = {}
    for rank in rank_order:
        needed = adj_rank_normal - baseline_thresh[rank]
        if needed <= 0: promo_normal[rank] = "Already Achieved"
        elif needed > len(raw_future_rets): promo_normal[rank] = "Will not achieve"
        else:
            date = raw_future_rets.iloc[needed - 1]
            promo_normal[rank] = date.strftime('%d-%m-%y') if date <= target_ret else "Will not achieve"
    results = {'Normal': promo_normal}

    # Proportional VRS Drop Distribution for Sim
    np.random.seed(42)
    if vrs_drop_total > 0 and not future_seniors.empty:
        drops = np.random.choice(future_seniors.index, min(vrs_drop_total, len(future_seniors)), replace=False)
        sim_seniors = future_seniors.drop(drops)
    else:
        sim_seniors = future_seniors
    
    sim_rets = sim_seniors['Retirement_Date'].sort_values().values.copy()
    
    # 2. VRS (No CR) & 3. With CR Logic
    def run_sim(thresholds, current_rank):
        active = sim_rets.copy()
        current_date = pd.Timestamp('2026-05-01')
        promo_dates = {}
        for r, t in thresholds.items():
            # Check Triple Anchors
            if r in anchor_snos and target_sno <= anchor_snos[r]: promo_dates[r] = "Already Achieved"
            elif current_rank <= t: promo_dates[r] = "Already Achieved"
        
        while current_date <= target_ret:
            m_end = current_date + MonthEnd(0)
            active = active[active > np.datetime64(m_end)]
            rank_pos = current_rank - (len(sim_rets) - len(active))
            for r, t in thresholds.items():
                if r not in promo_dates and rank_pos <= t: promo_dates[r] = m_end.strftime('%d-%m-%y')
            current_date = (current_date + pd.DateOffset(months=1)).replace(day=1)
        return promo_dates, (current_rank - (len(sim_rets) - len(active)))

    promo_vrs_no_cr, vrs_final_sen = run_sim(baseline_thresh, adj_rank_sim)
    promo_cr, cr_final_sen = run_sim(cr_thresh, adj_rank_sim)
    
    results['VRS (No CR)'] = promo_vrs_no_cr
    results['With CR'] = promo_cr
    results['CR + VRS'] = promo_cr # Logic remains optimized for CR

    # Seniority Calculation
    seniority = {}
    for y in range(2027, target_ret.year + 1):
        jan1 = pd.Timestamp(year=y, month=1, day=1)
        rets = (raw_future_rets < jan1).sum()
        seniority[str(y)] = adj_rank_normal - rets
    
    final_sen_normal = adj_rank_normal - (raw_future_rets < target_ret).sum()
    
    return results, seniority, final_sen_normal, vrs_final_sen

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
        
        promos, sens, final_norm, final_vrs = calculate_scenarios(df, target['S. No'], target['Retirement_Date'])
        
        st.subheader("📈 Projected Promotion Dates")
        st.table(pd.DataFrame(promos).reindex(['DC', '2IC', 'COMDT', 'DIG', 'IG', 'ADG']))
        
        st.subheader("🎯 Seniority on Date of Retirement")
        colA, colB = st.columns(2)
        colA.metric("Final Seniority (Baseline)", f"Rank #{max(1, int(final_norm))}")
        colB.metric("Final Seniority (VRS Simulation)", f"Rank #{max(1, int(final_vrs))}")
        
        st.subheader("📅 Seniority Tracker (Jan 1st)")
        st.dataframe(pd.DataFrame(list(sens.items()), columns=['Year', 'Pos']).set_index('Year').T)
