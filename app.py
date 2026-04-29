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
    retirements = seniors['Retirement_Date'].dropna().sort_values().reset_index(drop=True)
    
    initial_rank = len(seniors) + 1
    
    baseline_thresh = {'ADG': 1, 'IG': 22, 'DIG': 181, 'COMDT': 554, '2IC': 1143, 'DC': 2452}
    cr_thresh = {'ADG': 1, 'IG': 33, 'DIG': 223, 'COMDT': 825, '2IC': 1698, 'DC': 2910}
    
    # --- THE NEW REALITY CHECK: 30-04-2026 PROMOTIONS ---
    # Find IRLA 11323334 and calculate "Extras" as historical VRS
    cutoff_officer = df[df['IRLA No'] == '11323334']
    base_extras = 0
    cr_extras = 0
    
    if not cutoff_officer.empty:
        cutoff_sno = int(cutoff_officer.iloc[0]['S. No'])
        cutoff_true_rank = len(df[df['S. No'] <= cutoff_sno])
        
        # If the target is junior to the cutoff, they benefit from all "extras" taking VRS
        if target_sno > cutoff_sno:
            base_extras = max(0, cutoff_true_rank - baseline_thresh['DC'])
            cr_extras = max(0, cutoff_true_rank - cr_thresh['DC'])
        # If the target is senior or equal to the cutoff, they only benefit from extras ahead of THEM
        else:
            base_extras = max(0, initial_rank - baseline_thresh['DC'])
            cr_extras = max(0, initial_rank - cr_thresh['DC'])

    # Adjust the starting rank positions
    adj_initial_base = max(1, initial_rank - base_extras)
    adj_initial_cr = max(1, initial_rank - cr_extras)

    # Remove the historical VRS officers from the retirement pools so they aren't double-counted
    np.random.seed(42)
    
    rets_base = retirements.values.copy()
    if base_extras > 0 and len(rets_base) > 0:
        drop_idx = np.random.choice(range(len(rets_base)), min(base_extras, len(rets_base)), replace=False)
        rets_base = np.delete(rets_base, drop_idx)
    rets_base_series = pd.Series(rets_base).sort_values().reset_index(drop=True)

    rets_cr = retirements.values.copy()
    if cr_extras > 0 and len(rets_cr) > 0:
        drop_idx = np.random.choice(range(len(rets_cr)), min(cr_extras, len(rets_cr)), replace=False)
        rets_cr = np.delete(rets_cr, drop_idx)
    rets_cr_series = pd.Series(rets_cr).sort_values().reset_index(drop=True)

    results = {}
    rank_order = ['DC', '2IC', 'COMDT', 'DIG', 'IG', 'ADG']
    
    # --- 1. Normal (Baseline) ---
    promo_normal = {}
    for rank in rank_order:
        needed = adj_initial_base - baseline_thresh[rank]
        if needed <= 0:
            promo_normal[rank] = "Already Achieved"
        elif needed > len(rets_base_series):
            promo_normal[rank] = "Will not achieve"
        else:
            date = rets_base_series.iloc[needed - 1]
            promo_normal[rank] = date.date() if date <= target_ret else "Will not achieve"
    results['Normal'] = promo_normal
    
    # --- 2. VRS (No CR) ---
    np.random.seed(42)
    active_rets_base = rets_base.copy()
    current_date = pd.Timestamp('2026-05-01')
    acc_comdt_b = 0.0; acc_2ic_b = 0.0; acc_dc_b = 0.0; acc_ac_b = 0.0
    promo_base_vrs = {}
    
    for rank, thresh in baseline_thresh.items():
        if adj_initial_base <= thresh:
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
            
        current_date = (current_date + pd.DateOffset(months=1)).replace(day=1)
        
    results['VRS (No CR)'] = promo_base_vrs

    # --- 3. With CR (New Vacancies) ---
    promo_cr = {}
    for rank in rank_order:
        needed = adj_initial_cr - cr_thresh[rank]
        if needed <= 0:
            promo_cr[rank] = "Already Achieved"
        elif needed > len(rets_cr_series):
            promo_cr[rank] = "Will not achieve"
        else:
            date = rets_cr_series.iloc[needed - 1]
            promo_cr[rank] = date.date() if date <= target_ret else "Will not achieve"
    results['With CR'] = promo_cr
    
    # --- 4. With CR + VRS ---
    np.random.seed(42)
    active_rets = rets_cr.copy()
    current_date = pd.Timestamp('2026-05-01')
    acc_comdt = 0.0; acc_2ic = 0.0; acc_dc = 0.0; acc_ac = 0.0
    promo_vrs = {}
    
    for rank, thresh in cr_thresh.items():
        if adj_initial_cr <= thresh:
            promo_vrs[rank] = "Already Achieved"
            
    final_vrs_seniority = adj_initial_cr
            
    while current_date <= target_ret:
        month_end = current_date + MonthEnd(0)
        active_rets = active_rets[active_rets > np.datetime64(month_end)]
        n_seniors = len(active_rets)
        rank_pos = n_seniors + 1
        
        final_vrs_seniority = rank_pos
        
        for rank, thresh in cr_thresh.items():
            if rank not in promo_vrs and rank_pos <= thresh:
                promo_vrs[rank] = month_end.date()
                
        if rank_pos <= 1: 
            final_vrs_seniority = 1
            break
        
        s_comdt = min(n_seniors, cr_thresh['COMDT'])
        s_2ic = max(0, min(n_seniors, cr_thresh['2IC']) - cr_thresh['COMDT'])
        s_dc = max(0, min(n_seniors, cr_thresh['DC']) - cr_thresh['2IC'])
        s_ac = max(0, n_seniors - cr_thresh['DC'])

        acc_comdt += (5.0/12.0) * (s_comdt/cr_thresh['COMDT']) if cr_thresh['COMDT'] else 0
        acc_2ic += (10.0/12.0) * (s_2ic/873.0)
        acc_dc += (20.0/12.0) * (s_dc/1212.0)
        acc_ac += (40.0/12.0) * (s_ac/1528.0)
        
        drops = int(acc_comdt) + int(acc_2ic) + int(acc_dc) + int(acc_ac)
        
        acc_comdt -= int(acc_comdt)
        acc_2ic -= int(acc_2ic)
        acc_dc -= int(acc_dc)
        acc_ac -= int(acc_ac)
        
        if drops > 0 and len(active_rets) > 0:
            indices = np.random.choice(range(len(active_rets)), min(drops, len(active_rets)), replace=False)
            active_rets = np.delete(active_rets, indices)
            
        current_date = (current_date + pd.DateOffset(months=1)).replace(day=1)
        
    results['CR + VRS'] = promo_vrs
    
    # --- Seniority Calculation ---
    seniority = {}
    for y in range(2027, target_ret.year + 1):
        jan1 = pd.Timestamp(year=y, month=1, day=1)
        rets_before = (pd.Series(rets_base) < jan1).sum()
        seniority[str(y)] = adj_initial_base - rets_before
        
    rets_before_ret = (pd.Series(rets_base) < target_ret).sum()
    baseline_final_sen = adj_initial_base - rets_before_ret
    seniority[f"Ret. ({target_ret.strftime('%b %y')})"] = baseline_final_sen
        
    return results, seniority, baseline_final_sen, final_vrs_seniority, base_extras

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
            promotions, seniority, base_final_sen, vrs_final_sen, extras = calculate_scenarios(df, target['S. No'], target['Retirement_Date'])
            
        if extras > 0:
            st.info(f"**Reality Adjustment Applied:** Automatically accounted for **{extras}** officers who took VRS to accommodate the April 2026 DC promotions.")
            
        st.subheader("📈 Projected Promotion Dates")
        ranks = ['DC', '2IC', 'COMDT', 'DIG', 'IG', 'ADG']
        
        promo_df = pd.DataFrame({
            'Rank': ranks,
            'Normal (Age-60 Only)': [promotions['Normal'].get(r, 'Will not achieve') for r in ranks],
            'With VRS Attrition (No CR)': [promotions['VRS (No CR)'].get(r, 'Will not achieve') for r in ranks],
            'With CR (New Vacancies)': [promotions['With CR'].get(r, 'Will not achieve') for r in ranks],
            'With CR + VRS Attrition': [promotions['CR + VRS'].get(r, 'Will not achieve') for r in ranks]
        })
        st.table(promo_df.set_index('Rank'))
        
        st.divider()

        st.subheader("🎯 Seniority on Date of Retirement")
        colA, colB = st.columns(2)
        colA.metric(label="Without VRS (Baseline)", value=f"Rank #{base_final_sen}")
        colB.metric(label="With VRS (Simulation)", value=f"Rank #{vrs_final_sen}")

        st.divider()
        
        st.subheader("📅 Projected Jan 1st Seniority Tracker (Baseline)")
        sen_df = pd.DataFrame(list(seniority.items()), columns=['Timeline', 'Seniority Position'])
        st.dataframe(sen_df.set_index('Timeline').T)
