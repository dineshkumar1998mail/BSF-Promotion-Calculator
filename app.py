import io
import os

import numpy as np
import pandas as pd
import streamlit as st
from pandas.tseries.offsets import MonthEnd

st.set_page_config(page_title="BSF Officers Promotion Model", layout="wide", page_icon="🛡️")

# ----------------------------- CONSTANTS -----------------------------------
RANK_ORDER = ['DC', '2IC', 'COMDT', 'DIG', 'IG', 'ADG']

FULL_RANK = {'AC': 'Assistant Commandant', 'DC': 'Deputy Commandant',
             '2IC': 'Second-in-Command', 'COMDT': 'Commandant',
             'DIG': 'Deputy Inspector General', 'IG': 'Inspector General',
             'ADG': 'Additional Director General'}

# Static fallback thresholds (seniority position at which promotion occurs)
BASELINE_THRESH = {'ADG': 1, 'IG': 22, 'DIG': 181, 'COMDT': 554, '2IC': 1143, 'DC': 2452}
CR_THRESH = {'ADG': 1, 'IG': 33, 'DIG': 223, 'COMDT': 825, '2IC': 1698, 'DC': 2910}

# Junior-most officer promoted to each rank (IRLA), as of 08-Jul-2026.
# Update anchors.csv in the repo (columns: Rank, IRLA No) for permanent changes,
# or use the sidebar for session-only changes.
DEFAULT_ANCHORS = {'COMDT': '19975580', '2IC': '10694886', 'DC': '41427187'}

VRS_RATE_DEFAULT = 2.0  # % of serving seniors exiting per year

SCENARIO_ORDER = ['Normal', 'VRS (No CR)', 'With CR', 'CR + VRS']

# ----------------------------- STYLING --------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&display=swap');

/* ---- Service-dossier palette: parchment paper, olive ink, brass accents ---- */
.stApp {background-color: #F5F3EC; color: #232821;}
[data-testid="stSidebar"] {background-color: #EDEAE0; border-right: 1px solid #D8D3C2;}
[data-testid="stHeader"] {background: transparent;}
p, li, label, .stMarkdown {color: #232821;}
.stCaption, [data-testid="stCaptionContainer"] {color: #6E6F5E !important;}
.block-container {padding-top: 1.2rem;}

h3 {font-family: 'Source Serif 4', Georgia, serif; color: #2E3618;
    border-bottom: 1px solid #D8D3C2; padding-bottom: .3rem; font-weight: 600;}

.bsf-header {
    background: #FDFCF8;
    border-top: 4px double #A6802A;
    border-bottom: 4px double #A6802A;
    border-left: 1px solid #D8D3C2;
    border-right: 1px solid #D8D3C2;
    text-align: center;
    padding: 1.5rem 2rem 1.2rem;
    margin-bottom: 1.4rem;
}
.bsf-header .motto {color: #A6802A; font-size: .78rem; letter-spacing: .28em;
    text-transform: uppercase; margin-bottom: .4rem;}
.bsf-header h1 {font-family: 'Source Serif 4', Georgia, serif; color: #2E3618;
    font-size: 2rem; margin: 0 0 .35rem; font-weight: 700;}
.bsf-header .stars {color: #A6802A; letter-spacing: .7em; font-size: .8rem;
    margin-bottom: .45rem;}
.bsf-header .sub {color: #5C6150; margin: 0; font-size: .9rem;}

.officer-card {
    background: #39431F;
    border-left: 6px solid #A6802A;
    border-radius: 4px;
    padding: .95rem 1.4rem;
    margin-bottom: .9rem;
}
.officer-card span {color: #D9B75B; font-weight: 600; font-size: .72rem;
    letter-spacing: .26em; text-transform: uppercase;}
.officer-card h2 {color: #FBFAF3; margin: .15rem 0 0; font-size: 1.5rem;
    font-family: 'Source Serif 4', Georgia, serif;}

.verdict-card {
    background: #FDFCF8;
    border: 1px solid #D8D3C2;
    border-left: 5px solid #39431F;
    border-radius: 4px;
    padding: 1rem 1.3rem;
    margin: .4rem 0 1.2rem;
    font-size: 1.03rem;
    color: #232821;
}
.verdict-card .v-label {color: #A6802A; font-size: .7rem; letter-spacing: .26em;
    text-transform: uppercase; font-weight: 700; margin-bottom: .35rem;}
.verdict-card b {color: #2E3618;}

[data-testid="stMetric"] {
    background: #FDFCF8;
    border: 1px solid #D8D3C2;
    border-top: 3px solid #A6802A;
    border-radius: 4px;
    padding: .7rem .9rem;
    box-shadow: 0 1px 3px rgba(35,40,33,.07);
}
[data-testid="stMetricLabel"] {color: #5C6150; text-transform: uppercase;
    letter-spacing: .06em;}
[data-testid="stMetricValue"] {color: #232821;
    font-family: 'Source Serif 4', Georgia, serif;}

[data-testid="stDownloadButton"] button {
    background: #39431F; color: #FBFAF3;
    border: 1px solid #2E3618; border-radius: 4px;
}
[data-testid="stDownloadButton"] button:hover {
    background: #4A5729; color: #FFFFFF; border-color: #A6802A;
}

/* ---- Prominent IRLA search box (main page only) ---- */
[data-testid="stTextInput"] input {
    font-size: 1.2rem;
    padding: .8rem 1rem;
    border: 2px solid #39431F;
    border-radius: 8px;
    background: #FFFFFF;
    color: #232821;
}
[data-testid="stTextInput"] input:focus {
    border-color: #A6802A;
    box-shadow: 0 0 0 3px rgba(166,128,42,.25);
}
/* keep sidebar inputs at normal size */
[data-testid="stSidebar"] [data-testid="stTextInput"] input {
    font-size: 1rem;
    padding: .45rem .6rem;
    border: 1px solid #C9C3B2;
    border-radius: 6px;
    box-shadow: none;
}
</style>
""", unsafe_allow_html=True)


# ----------------------------- HELPERS --------------------------------------
def clean_irla(x):
    s = str(x).strip()
    if s.endswith('.0'):
        s = s[:-2]
    return s


def normalize_rank(r):
    """Map free-text rank strings from the CSV to standard codes."""
    s = str(r).upper().replace('.', ' ').strip()
    if 'ADG' in s or 'ADDITIONAL DIRECTOR' in s:
        return 'ADG'
    if 'DIG' in s or 'DY INSPECTOR' in s or 'DEPUTY INSPECTOR' in s:
        return 'DIG'
    if s == 'IG' or 'INSPECTOR GENERAL' in s or s.startswith('IG '):
        return 'IG'
    if 'COMDT' in s and ('DY' in s or 'DEPUTY' in s):
        return 'DC'
    if '2IC' in s or 'SECOND' in s or '2-I-C' in s or '2 I C' in s:
        return '2IC'
    if 'COMDT' in s or 'COMMANDANT' in s:
        if 'ASST' in s or 'ASSISTANT' in s:
            return 'AC'
        return 'COMDT'
    if s in ('DC',):
        return 'DC'
    if s in ('AC',) or 'ASST' in s or 'ASSISTANT' in s:
        return 'AC'
    return s  # fallback: show raw string


@st.cache_data
def load_data(file_bytes=None):
    if file_bytes:
        df = pd.read_csv(io.BytesIO(file_bytes))
    else:
        df = pd.read_csv('gradation_list.csv')

    df['S. No'] = pd.to_numeric(df['S. No'], errors='coerce')
    df = df.dropna(subset=['S. No'])

    # Indian date format is DD-MM-YYYY -> dayfirst=True
    df['DOB'] = pd.to_datetime(df['Date of Birth'], errors='coerce', dayfirst=True)
    df = df.dropna(subset=['DOB'])
    df = df.sort_values('S. No').reset_index(drop=True)

    # Superannuation: last day of the month of 60th birthday;
    # if born on the 1st, last day of the PRECEDING month.
    sixty = df['DOB'] + pd.DateOffset(years=60)
    df['Retirement_Date'] = sixty + MonthEnd(0)
    born_first = df['DOB'].dt.day == 1
    df.loc[born_first, 'Retirement_Date'] = sixty[born_first] - MonthEnd(1)

    df['IRLA No'] = df['IRLA No'].map(clean_irla)
    return df


@st.cache_data
def load_anchor_file():
    if os.path.exists('anchors.csv'):
        try:
            a = pd.read_csv('anchors.csv', dtype=str)
            return {str(r).strip().upper(): clean_irla(i)
                    for r, i in zip(a['Rank'], a['IRLA No'])}
        except Exception:
            return {}
    return {}


def live_position(df, sno, as_on):
    return int(((df['S. No'] <= sno) & (df['Retirement_Date'] > as_on)).sum())


# ----------------------------- SIDEBAR (CALIBRATION) ------------------------
st.sidebar.header("Model Calibration")

uploaded = st.sidebar.file_uploader(
    "Updated gradation list (optional CSV)", type=['csv'],
    help="Same columns required: S. No, IRLA No, Name, Rank, Date of Birth.")

df = load_data(uploaded.getvalue() if uploaded else None)

as_on = pd.Timestamp(st.sidebar.date_input(
    "Calculations as-on date", value=pd.Timestamp.today().normalize(),
    help="All seniority positions and simulations start from this date."))

st.sidebar.subheader("Latest Promotion Anchors")
st.sidebar.caption(
    "After a new DPC/promotion order, enter the IRLA of the **junior-most officer "
    "promoted** to that rank — thresholds recalibrate automatically. Sidebar entries "
    "last only this session; edit `anchors.csv` in the repo for permanent updates.")

file_anchors = load_anchor_file()
anchor_inputs = {}
for r in ['DC', '2IC', 'COMDT', 'DIG', 'IG']:
    default_val = file_anchors.get(r, DEFAULT_ANCHORS.get(r, ''))
    anchor_inputs[r] = st.sidebar.text_input(f"Junior-most {r} (IRLA)", value=default_val)

vrs_rate = st.sidebar.number_input(
    "Assumed VRS / premature exit rate (% of serving seniors per year)",
    min_value=0.0, max_value=20.0, value=VRS_RATE_DEFAULT, step=0.5,
    help="Applied as a percentage of the officer's own senior pool, so the "
         "assumption scales correctly for junior and senior officers alike.")

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
        st.sidebar.warning(f"{r} anchor IRLA '{irla_a}' not found — "
                           f"using static threshold {BASELINE_THRESH[r]}.")
        continue
    sno = int(row.iloc[0]['S. No'])
    anchor_snos[r] = sno
    pos = live_position(df, sno, as_on)
    delta = pos - BASELINE_THRESH[r]
    dyn_thresh[r] = max(1, pos)
    dyn_cr_thresh[r] = max(1, CR_THRESH[r] + delta)
    calib_rows.append({'Rank': r, 'Anchor IRLA': irla_a, 'Anchor S.No': sno,
                       'Live promotion line': pos,
                       'Static baseline': BASELINE_THRESH[r], 'Shift': delta})


# ----------------------------- CORE MODEL -----------------------------------
def calculate_scenarios(df, target_sno, target_ret, as_on,
                        thresholds, cr_thresholds, anchor_snos, vrs_rate):
    target_sno = int(target_sno)
    seniors = df[df['S. No'] < target_sno]
    live_seniors = seniors[seniors['Retirement_Date'] > as_on].copy()
    live_rank = len(live_seniors) + 1
    future_rets = live_seniors['Retirement_Date'].sort_values().reset_index(drop=True)

    def already_achieved(rank, th):
        if anchor_snos.get(rank) and target_sno <= anchor_snos[rank]:
            return True
        return live_rank <= th[rank]

    # ---- 1. Normal model ----------------------------------------------------
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

    # ---- 2. Attrition simulation --------------------------------------------
    def run_attrition_sim(th, use_vrs=True):
        rng = np.random.default_rng(42)
        pool = live_seniors.copy()
        promo = {}
        for r in RANK_ORDER:
            if already_achieved(r, th):
                promo[r] = "Already Achieved"

        cur = as_on.replace(day=1)
        while cur <= target_ret and not pool.empty:
            m_end = cur + MonthEnd(0)
            pool = pool[pool['Retirement_Date'] > m_end]

            if use_vrs and not pool.empty:
                # percentage of the CURRENT pool -> tapers naturally as it shrinks
                monthly_goal = (vrs_rate / 100.0) * len(pool) / 12.0
                n_vrs = int(np.floor(monthly_goal + rng.random()))
                if n_vrs > 0:
                    drop_idx = rng.choice(pool.index, size=min(n_vrs, len(pool)),
                                          replace=False)
                    pool = pool.drop(drop_idx)

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

    # ---- 3. Seniority tracker ------------------------------------------------
    tracker = {}
    for y in range(as_on.year + 1, target_ret.year + 1):
        jan1 = pd.Timestamp(year=y, month=1, day=1)
        tracker[str(y)] = live_rank - int((future_rets < jan1).sum())

    scenarios = {'Normal': promo_normal,
                 'VRS (No CR)': promo_vrs,
                 'With CR': promo_cr,
                 'CR + VRS': promo_cr_vrs}
    return scenarios, tracker, final_sen_vrs, final_sen_normal, live_rank


# ----------------------------- VERDICT & TIMELINE ---------------------------
def highest_outcome(promos):
    """Highest rank reached in a scenario, with its date (or 'Already Achieved')."""
    best_rank, best_val = None, None
    for r in RANK_ORDER:
        v = promos.get(r, "Will not achieve")
        if v != "Will not achieve":
            best_rank, best_val = r, v
    return best_rank, best_val


def make_verdict(scenarios, current_code):
    n_rank, n_val = highest_outcome(scenarios['Normal'])
    c_rank, c_val = highest_outcome(scenarios['CR + VRS'])

    if n_rank is None:
        base = (f"Most likely outcome: retires as "
                f"<b>{FULL_RANK.get(current_code, current_code)}</b> — "
                f"no further promotion projected under the normal model.")
        final_normal = current_code
    elif n_val == "Already Achieved":
        base = (f"Most likely outcome: retires as "
                f"<b>{FULL_RANK.get(n_rank, n_rank)}</b> (present rank); "
                f"no further promotion projected under the normal model.")
        final_normal = n_rank
    else:
        base = (f"Most likely outcome: retires as <b>{FULL_RANK.get(n_rank, n_rank)}</b>, "
                f"promotion expected around <b>{n_val}</b>.")
        final_normal = n_rank

    idx = {r: i for i, r in enumerate(RANK_ORDER)}
    if c_rank and (final_normal not in idx or idx[c_rank] > idx.get(final_normal, -1)):
        when = "" if c_val == "Already Achieved" else f" around <b>{c_val}</b>"
        base += (f" Under <b>Cadre Review + VRS</b>, "
                 f"<b>{FULL_RANK.get(c_rank, c_rank)}</b> becomes possible{when}.")
    elif c_rank:
        base += " Cadre Review does not change the final rank — it only advances the dates."
    return base


# ----------------------------- REPORT ----------------------------------------
def build_html_report(target, verdict_html, scenarios, tracker,
                      as_on, vrs_rate, calib_rows):
    proj = pd.DataFrame(scenarios).reindex(RANK_ORDER)
    rows_html = ""
    for r in RANK_ORDER:
        cells = "".join(
            f"<td class='{ 'ok' if scenarios[s][r]=='Already Achieved' else ('na' if scenarios[s][r]=='Will not achieve' else 'dt')}'>"
            f"{scenarios[s][r]}</td>" for s in SCENARIO_ORDER)
        rows_html += f"<tr><th>{r}</th>{cells}</tr>"

    tracker_html = ""
    if tracker:
        yrs = "".join(f"<th>{y}</th>" for y in tracker)
        pos = "".join(f"<td>{p}</td>" for p in tracker.values())
        tracker_html = (f"<h3>Seniority on 1 January (Normal Model)</h3>"
                        f"<table><tr><th>Year</th>{yrs}</tr>"
                        f"<tr><th>Position</th>{pos}</tr></table>")

    calib_note = ""
    if calib_rows:
        calib_note = "<p class='small'>Promotion lines calibrated to actual promotion anchors: " + \
            "; ".join(f"{c['Rank']} line at #{c['Live promotion line']}" for c in calib_rows) + ".</p>"

    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>Promotion Projection — {target['Name']}</title>
<style>
body{{font-family:Georgia,'Times New Roman',serif;color:#232821;max-width:820px;
margin:24px auto;padding:0 20px;background:#F5F3EC;}}
.header{{background:#FDFCF8;border-top:4px double #A6802A;border-bottom:4px double #A6802A;
border-left:1px solid #D8D3C2;border-right:1px solid #D8D3C2;text-align:center;
padding:18px 24px 14px;}}
.header .motto{{color:#A6802A;font-size:11px;letter-spacing:.28em;text-transform:uppercase;}}
.header h1{{margin:6px 0 3px;font-size:22px;color:#2E3618;}}
.header p{{margin:0;color:#5C6150;font-size:12px;}}
.verdict{{background:#FDFCF8;border:1px solid #D8D3C2;border-left:5px solid #39431F;
padding:12px 16px;margin:16px 0;font-size:15px;}}
table{{border-collapse:collapse;width:100%;margin:10px 0 18px;font-size:13px;
background:#FDFCF8;}}
th,td{{border:1px solid #D8D3C2;padding:7px 10px;text-align:center;}}
th{{background:#39431F;color:#FBFAF3;font-weight:600;}}
tr th:first-child{{background:#4A5729;}}
td.ok{{background:#EAF0E2;color:#33531F;font-weight:600;}}
td.na{{color:#77785F;font-style:italic;}}
td.dt{{color:#39431F;font-weight:600;}}
h3{{color:#2E3618;border-bottom:2px solid #A6802A;padding-bottom:4px;}}
.small{{font-size:12px;color:#5C6150;}}
.disclaimer{{font-size:11px;color:#8A8B7A;border-top:1px solid #D8D3C2;
padding-top:10px;margin-top:24px;}}
</style></head><body>
<div class='header'><div class='motto'>जीवन पर्यन्त कर्तव्य &nbsp;·&nbsp; Duty Unto Death</div>
<h1>BSF Officers Promotion Projection</h1>
<p>Generated {pd.Timestamp.today().strftime('%d-%b-%Y')} &nbsp;|&nbsp; Computed as on {as_on.strftime('%d-%b-%Y')}</p></div>

<h3>Officer Details</h3>
<table>
<tr><th>Name</th><td>{target['Name']}</td><th>IRLA No</th><td>{target['IRLA No']}</td></tr>
<tr><th>Present Rank</th><td>{target['Rank']}</td><th>Seniority S.No</th><td>{int(target['S. No'])}</td></tr>
<tr><th>Date of Birth</th><td>{target['DOB'].strftime('%d-%b-%Y')}</td><th>Superannuation</th><td>{target['Retirement_Date'].strftime('%d-%b-%Y')}</td></tr>
</table>

<div class='verdict'><b>Assessment:</b> {verdict_html}</div>

<h3>Promotion Projections</h3>
<table><tr><th>Rank</th>{''.join(f'<th>{s}</th>' for s in SCENARIO_ORDER)}</tr>{rows_html}</table>

{tracker_html}

<h3>Assumptions</h3>
<p class='small'>Normal: natural age-60 retirements only. VRS scenarios assume
{vrs_rate:.1f}% of serving seniors exiting prematurely per year (applied to the
shrinking pool, so absolute numbers taper over time). CR scenarios assume expanded
Cadre-Review sanctioned strength. No supersession, deputation vacancy or DPC delay
is modelled.</p>
{calib_note}

<p class='disclaimer'>This is an unofficial statistical projection based on the
published gradation list. It has no bearing on actual DPC outcomes, which depend on
vacancies, empanelment, service records and government decisions. For personal
planning only.</p>
</body></html>"""


def build_text_report(target, verdict_plain, scenarios, as_on):
    lines = ["BSF OFFICERS PROMOTION PROJECTION",
             f"Generated {pd.Timestamp.today().strftime('%d-%b-%Y')} | As on {as_on.strftime('%d-%b-%Y')}",
             "-" * 46,
             f"Officer   : {target['Name']} (IRLA {target['IRLA No']})",
             f"Rank/S.No : {target['Rank']} / {int(target['S. No'])}",
             f"DOB       : {target['DOB'].strftime('%d-%b-%Y')}",
             f"Retirement: {target['Retirement_Date'].strftime('%d-%b-%Y')}",
             "-" * 46,
             f"VERDICT: {verdict_plain}",
             "-" * 46, "PROJECTIONS:"]
    for s in SCENARIO_ORDER:
        lines.append(f"\n[{s}]")
        for r in RANK_ORDER:
            lines.append(f"  {r:6s}: {scenarios[s][r]}")
    lines += ["-" * 46,
              "Unofficial statistical projection. Actual DPC outcomes depend on",
              "vacancies, empanelment and service records."]
    return "\n".join(lines)


# ----------------------------- UI -------------------------------------------
st.markdown(f"""
<div class="bsf-header">
  <div class="motto">जीवन पर्यन्त कर्तव्य &nbsp;·&nbsp; Duty Unto Death</div>
  <h1>BSF Officers Promotion Model</h1>
  <div class="stars">★ ★ ★</div>
  <p class="sub">Seniority-based projection &nbsp;·&nbsp; computed as on
  <b>{as_on.strftime('%d-%b-%Y')}</b> &nbsp;·&nbsp; calibrated to the latest promotion orders</p>
</div>""", unsafe_allow_html=True)

st.markdown("#### 🔍 Type IRLA and press Enter")
irla = st.text_input("Type IRLA and press Enter", label_visibility="collapsed",
                     placeholder="Type IRLA and press Enter  (e.g. 19975580)",
                     help="Your IRLA number as printed in the gradation list")

if irla:
    res = df[df['IRLA No'] == clean_irla(irla)]
    if res.empty:
        st.error("IRLA number not found in the gradation list.")
    else:
        target = res.iloc[0]
        current_code = normalize_rank(target['Rank'])

        if target['Retirement_Date'] <= as_on:
            st.warning("This officer has already superannuated as on the selected date. "
                       "Projections are shown for reference only.")

        (scenarios, tracker, f_vrs, f_norm,
         live_rank) = calculate_scenarios(df, target['S. No'], target['Retirement_Date'],
                                          as_on, dyn_thresh, dyn_cr_thresh,
                                          anchor_snos, vrs_rate)

        st.markdown(f"""
        <div class="officer-card">
          <span>{FULL_RANK.get(current_code, target['Rank'])}</span>
          <h2>{target['Name']}</h2>
        </div>""", unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("S.No", int(target['S. No']))
        c2.metric("DOB", target['DOB'].strftime('%d-%b-%Y'))
        c3.metric("Retirement", target['Retirement_Date'].strftime('%d-%b-%Y'))
        yrs_left = max(0.0, (target['Retirement_Date'] - as_on).days / 365.25)
        c4.metric("Service Left", f"{yrs_left:.1f} yrs")

        # ---- Verdict ----
        verdict_html = make_verdict(scenarios, current_code)
        st.markdown(f"<div class='verdict-card'><div class='v-label'>Assessment</div>"
                    f"{verdict_html}</div>", unsafe_allow_html=True)

        # ---- Projections table ----
        st.subheader("Promotion Projections")
        proj = pd.DataFrame(scenarios).reindex(RANK_ORDER)[SCENARIO_ORDER]

        def cell_style(v):
            if v == "Already Achieved":
                return 'background-color:#EAF0E2;color:#33531F;font-weight:600'
            if v == "Will not achieve":
                return 'color:#77785F;font-style:italic'
            return 'color:#39431F;font-weight:600'

        styler = proj.style
        styler = styler.map(cell_style) if hasattr(styler, 'map') else styler.applymap(cell_style)
        st.dataframe(styler, use_container_width=True)

        c_a, c_b = st.columns(2)
        c_a.metric("Final Seniority (Normal Model)", f"Rank #{max(1, int(f_norm))}",
                   help="Based purely on natural age-60 retirements.")
        c_b.metric("Final Seniority (VRS Model)", f"Rank #{max(1, int(f_vrs))}",
                   help="VRS applied as a % of serving seniors; no double-counting.")

        # ---- Tracker ----
        st.subheader("Seniority Tracker (1 Jan each year — Normal Model)")
        if tracker:
            st.dataframe(pd.DataFrame(list(tracker.items()),
                                      columns=['Year', 'Seniority Pos'])
                         .set_index('Year').T, use_container_width=True)
        else:
            st.info("Officer retires before the next 1 January — no tracker to show.")

        # ---- Downloadable report ----
        st.divider()
        st.subheader("Download One-Page Report")
        verdict_plain = (verdict_html.replace('<b>', '').replace('</b>', ''))
        html_report = build_html_report(target, verdict_html, scenarios,
                                        tracker, as_on, vrs_rate, calib_rows)
        text_report = build_text_report(target, verdict_plain, scenarios, as_on)

        d1, d2 = st.columns(2)
        d1.download_button("Full Report (HTML — open & print/save as PDF)",
                           data=html_report,
                           file_name=f"promotion_projection_{target['IRLA No']}.html",
                           mime="text/html", use_container_width=True)
        d2.download_button("Text Summary (WhatsApp-friendly)",
                           data=text_report,
                           file_name=f"promotion_summary_{target['IRLA No']}.txt",
                           mime="text/plain", use_container_width=True)
