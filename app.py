import streamlit as st
import pandas as pd
import numpy as np
from pandas.tseries.offsets import MonthEnd

st.set_page_config(page_title="BSF Officer Promotion & Seniority Calculator", layout="wide")

@st.cache_data
def load_data():
    df = pd.read_csv('gradation_list.csv')
    
    # --- AUTOMATED DATA CLEANING ---
    df['S. No'] = pd.to_numeric(df['S. No'], errors='coerce')
    df = df.dropna(subset=['S. No'])
    
    df['DOB'] = pd.to_datetime(df['Date of Birth'], errors='coerce')
    df = df.dropna(subset=['DOB'])
    
    df = df.sort_values('S. No').reset_index(drop=True)
    
    # Calculate Retirements
    df['Retirement_Date'] = df['DOB'] + pd.DateOffset(years=60) + MonthEnd(0)
    df['IRLA No'] = df['IRLA No'].astype(str).str.strip()
    
    return df

def calculate_scenarios(df, target_sno, target_ret):
    target_sno = int(target_sno)
    
    seniors = df[df['S. No'] < target_sno].copy()
    retirements = seniors['Retirement_Date'].dropna().sort_values().reset_index(drop=True)
    
    baseline_thresh = {'ADG': 1, 'IG': 22, 'DIG': 181, 'COMDT': 554, '2IC': 1143, 'DC': 2452}
    cr_thresh = {'ADG': 1, 'IG': 33, 'DIG': 223, 'COMDT': 825, '2IC': 1698, 'DC': 2910}
    
    results = {}
    rank_order = ['DC', '2IC', 'COMDT', 'DIG', 'IG', 'ADG']
    
    # 1. Normal (Baseline)
    promo_normal = {}
    for rank in rank_order:
        needed = target_sno - baseline_thresh[rank]
        if needed <= 0:
            promo_normal[rank] = "Already Achieved"
        elif needed > len(retirements):
            promo_normal[rank] = "Will not achieve"
        else:
            date = retirements.iloc[needed - 1]
            promo_normal[rank] = date.date() if date <= target_ret else "Will not achieve"
    results['Normal'] = promo_normal
    
    # 2. With CR (Cadre Restructuring)
    promo_cr = {}
    for rank in rank_order:
        needed = target_sno - cr_thresh[rank]
        if needed <= 0:
            promo_cr[rank] = "Already Achieved"
        elif needed > len(retirements):
            promo_cr[rank] = "Will not achieve"
        else:
            date = retirements.iloc[needed - 1]
            promo_cr[rank] = date.date() if date <= target_ret else "Will not achieve"
    results['With CR'] = promo_cr
    
    # 3. With CR + VRS (Simulation)
    np.random.seed(42)
    active_rets = seniors['Retirement_Date'].dropna().values.copy()
    current_date = pd.Timestamp('2026-05-01')
    acc_comdt = 0.0; acc_2ic = 0.0; acc_dc = 0.0; acc_ac = 0.0
    promo_vrs = {}
    
    # Pre-check for "Already Achieved" before starting the clock
    for rank, thresh in cr_thresh.items():
        if target_sno <= thresh:
            promo_vrs[rank] = "Already Achieved"
            
    final_vrs_seniority = target_sno
            
    while current_date <= target_ret:
        month_end = current_date + MonthEnd(0)
        active_rets = active_rets[active_rets > np.datetime64(month_end)]
        n_seniors = len(active_rets)
        rank_pos = n_seniors + 1
        
        # Track the absolute final position for VRS scenario
        final_vrs_seniority = rank_pos
        
        for rank, thresh in cr_thresh.items():
            if rank not in promo_vrs and rank_pos <= thresh:
                promo_vrs[rank] = month_end.date()
                
        if rank_pos <= 1: 
            final_vrs_seniority = 1
            break
        
        # Apply Rank-Tiered VRS Attrition
        s_comdt = min(n_seniors, cr_thresh['COMDT'])
        s_2ic = max(0, min(n_seniors, cr_thresh['2IC']) - cr_thresh['COMDT'])
        s_dc = max(0, min(n_seniors, cr_thresh['DC']) - cr_thresh['2IC'])
        s_ac = max(0, n_seniors - cr_thresh['DC'])

        acc_comdt += (5.0/12.0) * (s_comdt/cr_thresh['COMDT']) if cr_thresh['COMDT'] else 0
        acc_2ic += (10.0/12.0) * (s_2ic/873.0)
        acc_dc += (20.0/12.0) * (s_dc/1212.0)
        acc_ac += (40.0/12.0) * (s_ac/1528.0)
        
        drops = int(acc_comdt) + int(acc_2ic) + int(acc_dc) + int(acc_ac)
        acc_comdt -= int(acc_comdt); acc_2ic -= int(acc_2ic); acc_dc -= int(acc_dc); acc_ac -= int(acc_ac)
        
        if drops > 0 and len(active_rets) > 0:
            indices = np.random.choice(range(len(active_rets)), min(drops, len(active_rets)), replace=False)
            active_rets = np.delete(active_rets, indices)
            
        current_date = (current_date + pd.DateOffset(months=1)).replace(day=1)
        
    results['CR + VRS'] = promo_vrs
    
    # Seniority Calculation
    seniority = {}
    for y in range(2027, target_ret.year + 1):
        jan1 = pd.Timestamp(year=y, month=1, day=1)
        rets_before = (retirements < jan1).sum()
        seniority[str(y)] = target_sno - rets_before
        
    # Add final retirement date column
    rets_before_ret = (retirements < target_ret).sum()
    baseline_final_sen = target_sno - rets_before_ret
    seniority[f"Ret. ({target_ret.strftime('%b %y')})"] = baseline_final_sen
        
    return results, seniority, baseline_final_sen, final_vrs_seniority

# --- UI Setup ---
st.title("🛡️ BSF Officer Promotion & Seniority Calculator")
st.markdown("Enter an IRLA Number to project future postings, cadre restructuring benefits, and seniority.")

try:
    df = load_data()
except Exception as e:
    st.error(f"Error loading CSV file: {e}")
    st.stop()

irla_input = st.text_input("Enter IRLA Number:", placeholder="e.g. 12349432")

if irla_input:
    officer = df[df['IRLA No'] == str(irla_input).strip()]
    
    if officer.empty:
        st.warning("IRLA Number not found in the gradation list. Please check the number and try again.")
    else:
        target = officer.iloc[0]
        st.header(f"Profile: {target['Name']}")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Current Rank", target['Rank'])
        col2.metric("Gradation S.No", int(target['S. No']))
        col3.metric("Date of Birth", target['DOB'].strftime('%d-%b-%Y'))
        col4.metric("Retirement Date", target['Retirement_Date'].strftime('%d-%b-%Y'))
        
        st.divider()
        
        with st.spinner("Simulating retirement models and attrition scenarios..."):
            promotions, seniority, base_final_sen, vrs_final_sen = calculate_scenarios(df, target['S. No'], target['Retirement_Date'])
            
        st.subheader("📈 Projected Promotion Dates")
        ranks = ['DC', '2IC', 'COMDT', 'DIG', 'IG', 'ADG']
        promo_df = pd.DataFrame({
            'Rank': ranks,
            'Normal (Age-60 Only)': [promotions['Normal'].get(r, 'Will not achieve') for r in ranks],
            'With CR (New Vacancies)': [promotions['With CR'].get(r, 'Will not achieve') for r in ranks],
            'With CR + VRS Attrition': [promotions['CR + VRS'].get(r, 'Will not achieve') for r in ranks]
        })
        st.table(promo_df.set_index('Rank'))
        
        st.divider()

        # --- NEW SECTION: SENIORITY AT RETIREMENT ---
        st.subheader("🎯 Seniority on Date of Retirement")
        colA, colB = st.columns(2)
        colA.metric(label="Without VRS (Baseline)", value=f"Rank #{base_final_sen}")
        colB.metric(label="With VRS (Simulation)", value=f"Rank #{vrs_final_sen}")

        st.divider()
        
        st.subheader("📅 Projected Jan 1st Seniority Tracker (Baseline)")
        sen_df = pd.DataFrame(list(seniority.items()), columns=['Timeline', 'Seniority Position'])
        st.dataframe(sen_df.set_index('Timeline').T)
