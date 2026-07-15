import io
import os

import numpy as np
import pandas as pd
import streamlit as st
from pandas.tseries.offsets import MonthEnd

st.set_page_config(page_title="BSF Officers Promotion Model", layout="wide")

# ----------------------------- CONSTANTS -----------------------------------
RANK_ORDER = ['DC', '2IC', 'COMDT', 'DIG', 'IG', 'ADG']

# Static fallback thresholds (seniority position at which promotion occurs)
BASELINE_THRESH = {'ADG': 1, 'IG': 22, 'DIG': 181, 'COMDT': 554, '2IC': 1143, 'DC': 2452}
CR_THRESH = {'ADG': 1, 'IG': 33, 'DIG': 223, 'COMDT': 825, '2IC': 1698, 'DC': 2910}

# Junior-most officer promoted to each rank (IRLA), as of 08-Jul-2026.
# These are only DEFAULTS. When a new DPC / promotion order comes out, either:
#   (a) update anchors.csv in the repo (columns: Rank, IRLA No)  -> permanent, or
#   (b) type the new IRLA in the sidebar                          -> this session only.
DEFAULT_ANCHORS = {'COMDT': '19975580', '2IC': '10694886', 'DC': '41427187'}

VRS_ANNUAL_DEFAULT = 50.0


# ----------------------------- HELPERS --------------------------------------
def clean_irla(x):
    s = str(x).strip()
    if s.endswith('.0'):
        s = s[:-2]
    return s


@st.cache_data
def load_data(file_bytes=None):
    if file_bytes:
        df = pd.read_csv(io.BytesIO(file_bytes))
    else:
        df = pd.read_csv('gradation_list.csv')

    df['S. No'] = pd.to_numeric(df['S. No'], errors='coerce')
    df = df.dropna(subset=['S. No'])

    # Indian date format is DD-MM-YYYY -> dayfirst=True (was a silent bug earlier)
    df['DOB'] = pd.to_datetime(df['Date of Birth'], errors='coerce', dayfirst=True)
    df = df.dropna(subset=['DOB'])
    df = df.sort_values('S. No').reset_index(drop=True)

    # Govt superannuation rule: retire on the last day of the month in which the
    # officer attains 60. If born on the 1st of a month, retirement falls on the
    # last day of the PRECEDING month.
    sixty = df['DOB'] + pd.DateOffset(years=60)
    df['Retirement_Date'] = sixty + MonthEnd(0)
    born_first = df['DOB'].dt.day == 1
    df.loc[born_first, 'Retirement_Date'] = sixty[born_first] - MonthEnd(1)

    df['IRLA No'] = df['IRLA No'].map(clean_irla)
    return df


@st.cache_data
def load_anchor_file():
    """Optional anchors.csv in the repo overrides DEFAULT_ANCHORS permanently."""
    if os.path.exists('anchors.csv'):
        try:
            a = pd.read_csv('anchors.csv', dtype=str)
            return {str(r).strip().upper(): clean_irla(i)
                    for r, i in zip(a['Rank'], a['IRLA No'])}
        except Exception:
            return {}
    return {}


def live_position(df, sno, as_on):
    """Current seniority position of officer with serial number `sno`,
    counting only officers still serving on `as_on`."""
    return int(((df['S. No'] <= sno) & (df['Retirement_Date'] > as_on)).sum())


# ----------------------------- SIDEBAR (CALIBRATION) ------------------------
st.sidebar.header("⚙️ Model Calibration")

uploaded = st.sidebar.file_uploader(
    "Updated gradation list (optional CSV)", type=['csv'],
    help="Upload a fresh gradation list to override the bundled one. "
         "Same columns required: S. No, IRLA No, Name, Rank, Date of Birth.")

df = load_data(uploaded.getvalue() if uploaded else None)

as_on = pd.Timestamp(st.sidebar.date_input(
    "Calculations as-on date", value=pd.Timestamp.today().normalize(),
    help="All seniority positions and simulations start from this date. "
         "Defaults to today, so the model stays current automatically."))

st.sidebar.subheader("📌 Latest Promotion Anchors")
st.sidebar.caption(
    "If a new/unexpected DPC or promotion order is issued, enter the IRLA of the "
    "**junior-most officer promoted** to that rank. All thresholds recalibrate "
    "automatically. To make an update permanent for all users, edit `anchors.csv` "
    "in the repo (sidebar entries last only for this session).")

file_anchors = load_anchor_file()
anchor_inputs = {}
for r in ['DC', '2IC', 'COMDT', 'DIG', 'IG']:
    default_val = file_anchors.get(r, DEFAULT_ANCHORS.get(r, ''))
    anchor_inputs[r] = st.sidebar.text_input(f"Junior-most {r} (IRLA)", value=default_val)

vrs_annual = st.sidebar.number_input(
    "Assumed VRS / premature exits per year (across senior cadre)",
    min_value=0.0, max_value=500.0, value=VRS_ANNUAL_DEFAULT, step=5.0)

# --- Dynamic threshold recalibration from anchors ---------------------------
dyn_thresh = dict(BASELINE_THRESH)
dyn_cr_thresh = dict(CR_THRESH)
anchor_snos = {}
calib_rows = []

for r, irla_a in anchor_inputs.items():
    irla_a = clean_irla(irla_a)
    if not irla_a:
        continue
    row = df[df['IRLA No'] == irla_a]
    if row.empty:
        st.sidebar.warning(f"{r} anchor IRLA '{irla_a}' not found in list — "
                           f"using static threshold {BASELINE_THRESH[r]}.")
        continue
    sno = int(row.iloc[0]['S. No'])
    anchor_snos[r] = sno
    pos = live_position(df, sno, as_on)          # current promotion line for rank r
    delta = pos - BASELINE_THRESH[r]
    dyn_thresh[r] = max(1, pos)
    dyn_cr_thresh[r] = max(1, CR_THRESH[r] + delta)  # shift CR line by same delta
    calib_rows.append({'Rank': r, 'Anchor IRLA': irla_a, 'Anchor S.No': sno,
                       'Live promotion line': pos,
                       'Static baseline': BASELINE_THRESH[r], 'Shift': delta})


# ----------------------------- CORE MODEL -----------------------------------
def calculate_scenarios(df, target_sno, target_ret, as_on,
                        thresholds, cr_thresholds, anchor_snos, vrs_annual):
    target_sno = int(target_sno)
    seniors = df[df['S. No'] < target_sno]
    live_seniors = seniors[seniors['Retirement_Date'] > as_on].copy()
    live_rank = len(live_seniors) + 1
    future_rets = live_seniors['Retirement_Date'].sort_values().reset_index(drop=True)

    def already_achieved(rank, th):
        # Anchor check: if the junior-most promoted officer is junior to (or is)
        # the target, the target has already crossed this rank.
        if anchor_snos.get(rank) and target_sno <= anchor_snos[rank]:
            return True
        return live_rank <= th[rank]

    # ---- 1. Normal model: only natural age-60 retirements -------------------
    promo_normal = {}
    for r in RANK_ORDER:
        if already_achieved(r, thresholds):
            promo_normal[r] = "Already Achieved"
            continue
        needed = live_rank - thresholds[r]
        if needed > len(future_rets):
            promo_normal[r] = "Will not achieve"
        else:
            d = future_rets.iloc[needed - 1]
            promo_normal[r] = d.strftime('%d-%b-%Y') if d <= target_ret else "Will not achieve"

    final_sen_normal = live_rank - int((future_rets <= target_ret).sum())

    # ---- 2. Attrition simulation (VRS / CR variants) -------------------------
    def run_attrition_sim(th, use_vrs=True):
        rng = np.random.default_rng(42)   # deterministic, so results are stable
        pool = live_seniors.copy()
        n0 = max(1, len(pool))
        promo = {}
        for r in RANK_ORDER:
            if already_achieved(r, th):
                promo[r] = "Already Achieved"

        cur = as_on.replace(day=1)
        while cur <= target_ret and not pool.empty:
            m_end = cur + MonthEnd(0)

            # Step A: natural age-60 retirements this month
            pool = pool[pool['Retirement_Date'] > m_end]

            # Step B: cadre-linked VRS (rate shrinks with the pool; officers
            # removed here can't later double-count as natural retirements)
            if use_vrs and not pool.empty:
                monthly_goal = (vrs_annual * len(pool) / n0) / 12.0
                n_vrs = int(np.floor(monthly_goal + rng.random()))
                if n_vrs > 0:
                    drop_idx = rng.choice(pool.index, size=min(n_vrs, len(pool)),
                                          replace=False)
                    pool = pool.drop(drop_idx)

            # Step C: check promotion lines
            rank_pos = len(pool) + 1
            for r in RANK_ORDER:
                if r not in promo and rank_pos <= th[r]:
                    promo[r] = m_end.strftime('%d-%b-%Y')

            if rank_pos <= 1:
                break
            cur = (cur + pd.DateOffset(months=1)).replace(day=1)

        for r in RANK_ORDER:
            promo.setdefault(r, "Will not achieve")
        return promo, len(pool) + 1

    promo_vrs, final_sen_vrs = run_attrition_sim(thresholds, use_vrs=True)
    promo_cr, _ = run_attrition_sim(cr_thresholds, use_vrs=False)
    promo_cr_vrs, _ = run_attrition_sim(cr_thresholds, use_vrs=True)

    # ---- 3. Seniority tracker (1 Jan each year, normal model) ---------------
    tracker = {}
    for y in range(as_on.year + 1, target_ret.year + 1):
        jan1 = pd.Timestamp(year=y, month=1, day=1)
        tracker[str(y)] = live_rank - int((future_rets < jan1).sum())

    scenarios = {'Normal': promo_normal,
                 'VRS (No CR)': promo_vrs,
                 'With CR': promo_cr,
                 'CR + VRS': promo_cr_vrs}
    return scenarios, tracker, final_sen_vrs, final_sen_normal, live_rank


# ----------------------------- UI -------------------------------------------
st.title("🛡️ BSF Officers Promotion Model")
st.caption(f"All figures computed live as on **{as_on.strftime('%d-%b-%Y')}**. "
           "Promotion lines auto-recalibrate from the anchors in the sidebar.")

if calib_rows:
    with st.expander("🔧 Current calibration (dynamic promotion lines)"):
        st.table(pd.DataFrame(calib_rows).set_index('Rank'))
        st.caption("Live promotion line = current seniority position of the "
                   "junior-most officer already promoted to that rank. Cadre-Review "
                   "lines are shifted by the same amount.")

irla = st.text_input("Enter IRLA Number:")

if irla:
    res = df[df['IRLA No'] == clean_irla(irla)]
    if res.empty:
        st.error("IRLA number not found in the gradation list.")
    else:
        target = res.iloc[0]
        st.header(f"Officer: {target['Name']}")

        if target['Retirement_Date'] <= as_on:
            st.warning("This officer has already superannuated as on the selected date. "
                       "Projections below are shown for reference only.")

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Current Rank", str(target['Rank']))
        c2.metric("S.No", int(target['S. No']))
        c3.metric("DOB", target['DOB'].strftime('%d-%b-%Y'))
        c4.metric("Retirement", target['Retirement_Date'].strftime('%d-%b-%Y'))

        (promos, tracker, f_vrs, f_norm,
         live_rank) = calculate_scenarios(df, target['S. No'], target['Retirement_Date'],
                                          as_on, dyn_thresh, dyn_cr_thresh,
                                          anchor_snos, vrs_annual)
        c5.metric("Live Seniority Today", f"#{live_rank}",
                  help="Position among officers still serving as on the selected date.")

        st.divider()
        st.subheader("📈 Promotion Projections (auto-calibrated)")
        st.table(pd.DataFrame(promos).reindex(RANK_ORDER))

        st.divider()
        c_a, c_b = st.columns(2)
        c_a.metric("Final Seniority (Normal Model)", f"Rank #{max(1, int(f_norm))}",
                   help="Based purely on natural age-60 retirements.")
        c_b.metric("Final Seniority (VRS Model)", f"Rank #{max(1, int(f_vrs))}",
                   help="VRS rate reduces as cadre shrinks; no double-counting "
                        "of future retirements.")

        st.divider()
        st.subheader("📅 Seniority Tracker (1 Jan each year — Normal Model)")
        if tracker:
            st.dataframe(pd.DataFrame(list(tracker.items()),
                                      columns=['Year', 'Seniority Pos'])
                         .set_index('Year').T)
        else:
            st.info("Officer retires before the next 1 January — no tracker to show.")
