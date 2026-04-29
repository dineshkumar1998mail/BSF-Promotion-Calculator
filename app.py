import streamlit as st
import pandas as pd
import numpy as np
from pandas.tseries.offsets import MonthEnd

st.set_page_config(page_title="BSF Officer Promotion & Seniority Calculator", layout="wide")

@st.cache_data
def load_data():
    # Make sure your CSV file is named 'gradation_list.csv' and placed in the same folder
    df = pd.read_csv('gradation_list.csv')
    df['S. No'] = pd.to_numeric(df['S. No'], errors='coerce')
    df = df.dropna(subset=['S. No']).sort_values('S. No')
    df['DOB'] = pd.to_datetime(df['Date of Birth'], errors='coerce')
    df['Retirement_Date'] = df['DOB'] + pd.DateOffset(years=60) + MonthEnd(0)
    # Ensure IRLA No is a string for exact matching
    df['IRLA No'] = df['IRLA No'].astype(str).str.strip()
    return df

def calculate_scenarios(df, target_sno, target_ret):
    target_sno = int(target_sno)
    seniors = df[df['S. No'] < target_sno].copy()
    retirements = seniors['Retirement_Date'].dropna().sort_values().reset_index(drop=True)
    
    # Define thresholds
    baseline_thresh = {'IG': 21, 'DIG': 180, 'COMDT': 553, '2IC': 1142, 'DC': 2451}
    cr_thresh = {'IG': 32, 'DIG': 222, 'COMDT': 824, '2IC': 1697, 'DC': 2909}
    
    results = {}
    
    # 1. Normal (Baseline)
    promo_normal = {}
    for rank in ['DC', '2IC', 'COMDT', 'DIG', 'IG']:
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
    for rank in ['DC', '2IC', 'COMDT', 'DIG', 'IG']:
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
    
    while current_date <= target_ret:
        month_end = current_date + MonthEnd(0)
        active_rets = active_rets[active_rets > np.datetime64(month_end)]
        n_seniors = len(active_rets)
        rank_pos = n_seniors + 1
        
        for rank, thresh in cr_thresh.items():
            if rank not in promo_vrs and rank_pos <= thresh:
                promo_vrs[rank] = month_end.date()
                
        if rank_pos <= 1: break
        
        # Apply VRS
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
    
    # Seniority Calculation (Baseline)
    seniority = {}
    for y in range(2027, target_ret.year + 1):
        jan1 = pd.Timestamp(year=y, month=1, day=1)
        rets_before = (retirements < jan1).sum()
        seniority[y] = target_sno - rets_before
        
    return results, seniority

# --- UI Setup ---
st.title("🛡️ BSF Officer Promotion & Seniority Calculator")
st.markdown("Enter an IRLA Number to project future postings, cadre restructuring benefits, and seniority.")

try:
    df = load_data()
except Exception as e:
    st.error("Error loading CSV file. Please ensure 'gradation_list.csv' is in the same folder.")
    st.stop()

irla_input = st.text_input("Enter IRLA Number:", placeholder="e.g. 12349432")

if irla_input:
    # Find Officer
    officer = df[df['IRLA No'] == irla_input.strip()]
    
    if officer.empty:
        st.warning("IRLA Number not found in the gradation list.")
    else:
        target = officer.iloc[0]
        st.header(f"Profile: {target['Name']}")
        
        # Display Details
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Current Rank", target['Rank'])
        col2.metric("Gradation S.No", int(target['S. No']))
        col3.metric("Date of Birth", target['DOB'].strftime('%d-%b-%Y') if pd.notnull(target['DOB']) else "N/A")
        col4.metric("Retirement Date", target['Retirement_Date'].strftime('%d-%b-%Y') if pd.notnull(target['Retirement_Date']) else "N/A")
        
        st.divider()
        
        # Calculate
        with st.spinner("Simulating retirement models and attrition scenarios..."):
            promotions, seniority = calculate_scenarios(df, target['S. No'], target['Retirement_Date'])
            
        st.subheader("📈 Projected Promotion Dates")
        
        # Prepare table for promotions
        ranks = ['DC', '2IC', 'COMDT', 'DIG', 'IG']
        promo_df = pd.DataFrame({
            'Rank': ranks,
            'Normal (Age-60 Only)': [promotions['Normal'].get(r, 'Will not achieve') for r in ranks],
            'With CR (New Vacancies)': [promotions['With CR'].get(r, 'Will not achieve') for r in ranks],
            'With CR + VRS Attrition': [promotions['CR + VRS'].get(r, 'Will not achieve') for r in ranks]
        })
        st.table(promo_df.set_index('Rank'))
        
        st.divider()
        
        st.subheader("📅 Projected Jan 1st Seniority (Baseline)")
        sen_df = pd.DataFrame(list(seniority.items()), columns=['Year', 'Seniority Position'])
        sen_df['Year'] = sen_df['Year'].astype(str)
        st.dataframe(sen_df.set_index('Year').T)
