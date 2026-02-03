import streamlit as st
import pandas as pd
import plotly.express as px
from utils.spi import compute_spi
from scipy.stats import ks_2samp
from scipy.stats import gaussian_kde
import numpy as np
import plotly.graph_objects as go

# ==================================================
# Streamlit App Configuration
# ==================================================
st.set_page_config(page_title="SPI Explorer", layout="wide")
st.title("SPI Explorer – Drought Diagnostics (CAMELS-IND)")

MAX_GAUGES = 5

# ==================================================
# Session state initialization
# (this is Streamlit "memory")
# ==================================================
if "monthly_data" not in st.session_state:
    st.session_state.monthly_data = {}

if "spi_results" not in st.session_state:
    st.session_state.spi_results = {}

if "diagnostics" not in st.session_state:
    st.session_state.diagnostics = {}
# ==================================================
# Load metadata (cached)
# ==================================================
@st.cache_data
def load_metadata():
    name = pd.read_csv(
        "data/attributes_csv/camels_ind_name.csv",
        dtype=str
    )
    topo = pd.read_csv(
        "data/attributes_csv/camels_ind_topo.csv",
        dtype=str
    )

    name.columns = name.columns.str.strip().str.lower()
    topo.columns = topo.columns.str.strip().str.lower()

    name["gauge_id"] = name["gauge_id"].str.strip()
    topo["gauge_id"] = topo["gauge_id"].str.strip()

    return name.merge(topo, on="gauge_id", how="left")


meta = load_metadata()

# ==================================================
# Sidebar – Gauge selection
# ==================================================
st.sidebar.header("Gauge Selection")

basins = sorted(meta["river_basin"].dropna().unique())
selected_basin = st.sidebar.selectbox(
    "Select CWC River Basin",
    basins
)

basin_gauges = meta.loc[
    meta["river_basin"] == selected_basin
]

selected_gauges = st.sidebar.multiselect(
    "Select Gauge IDs",
    basin_gauges["gauge_id"].tolist(),
    max_selections=MAX_GAUGES
)

if not selected_gauges:
    st.info("Select at least one gauge to proceed.")
    st.stop()

# ==================================================
# Sidebar – SPI configuration
# ==================================================
st.sidebar.header("SPI Configuration")

spi_scale = st.sidebar.selectbox(
    "SPI Scale (months)",
    [1, 3, 6, 12]
)

baseline = st.sidebar.slider(
    "Baseline Period",
    min_value=1980,
    max_value=2015,
    value=(1981, 2010)
)

st.sidebar.header("Seasonal Non-stationarity")

split_year = st.sidebar.slider(
    "Temporal Split Year",
    min_value=1985,
    max_value=2010,
    value=2000,
    help="SPI will be split into pre- and post-split periods"
)

month_names = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December"
}

selected_month = st.sidebar.selectbox(
    "Month for comparison",
    options=list(month_names.keys()),
    format_func=lambda m: month_names[m]
)

compute_button = st.sidebar.button("Compute SPI")

# ==================================================
# Variable selection (context plotting)
# ==================================================
st.subheader("Hydro-climatic Variable")

variables = [
    "prcp(mm/day)",
    "pet",
    "pet_gleam",
    "aet_gleam",
    "sm_lvl1",
    "sm_lvl2",
    "sm_lvl3"
]

selected_var = st.selectbox(
    "Select Hydro-climatic Variable for Context",
    variables
)

col1, col2 = st.columns(2)
plot_var = col1.button("Plot")
save_var = col2.button("Save CSV")

# ==================================================
# COMPUTE SPI (heavy computation, done once)
# ==================================================
if compute_button:

    st.session_state.monthly_data = {}
    st.session_state.spi_results = {}

    for gauge_id in selected_gauges:

        gauge_id_str = str(gauge_id).zfill(5)

        try:
            df = pd.read_csv(
                f"data/catchment_mean_forcings/{gauge_id_str}.csv"
            )
        except FileNotFoundError:
            st.warning(f"Forcing file not found for gauge {gauge_id}")
            continue

        df.columns = df.columns.str.strip().str.lower()

        # Build datetime index
        df["date"] = pd.to_datetime(df[["year", "month", "day"]])
        df = df.set_index("date")

        # Monthly aggregation (CRITICAL for SPI)
        df_monthly = df.resample("MS").sum(numeric_only=True)

        # Extract precipitation robustly
        if "prcp(mm/day)" in df_monthly.columns:
            prcp = pd.to_numeric(df_monthly["prcp(mm/day)"], errors="coerce")
        elif "prcp" in df_monthly.columns:
            prcp = pd.to_numeric(df_monthly["prcp"], errors="coerce")
        else:
            st.warning(f"No precipitation data for gauge {gauge_id}")
            continue

        if prcp.isna().mean() > 0.5:
            st.warning(f"Too many missing values for gauge {gauge_id}")
            continue

        spi = compute_spi(
            prcp=prcp,
            scale=spi_scale,
            baseline_years=baseline,
            dates=df_monthly.index
        )
        
        spi_df = spi.dropna()
        
        pre_spi = spi_df[spi_df.index.year < split_year]
        
        post_spi = spi_df[spi_df.index.year >= split_year]
        
        if len(pre_spi) >= 20 and len(post_spi) >=20:
            mean_pre = pre_spi.mean()
            mean_post = post_spi.mean()
            
            std_pre = pre_spi.std()
            std_post = post_spi.std()
            
            ks_stat, ks_p = ks_2samp(pre_spi.values, post_spi.values)
            
            diagnostics = {
                "mean_pre": mean_pre,
                "mean_post": mean_post,
                "std_pre": std_pre,
                "std_post": std_post,
                "ks_stat": ks_stat,
                "ks_pvalue": ks_p
            }
        else:
            diagnostics = None 
        
        # Store results in session state
        st.session_state.monthly_data[gauge_id] = df_monthly
        st.session_state.spi_results[gauge_id] = spi
        st.session_state.diagnostics[gauge_id] = diagnostics

    st.success("SPI computation completed.")

# ==================================================
# DISPLAY SPI + DOWNLOAD (after computation)
# ==================================================
if st.session_state.spi_results:

    st.header("SPI Results")

    for gauge_id, spi in st.session_state.spi_results.items():

        st.subheader(f"Gauge {gauge_id}")

        if spi.isna().all():
            st.warning("SPI could not be computed for this gauge.")
            continue

        spi_df = spi.reset_index()
        spi_df.columns = ["date", "SPI"]

        fig_spi = px.line(
            spi_df,
            x="date",
            y="SPI",
            title=f"SPI-{spi_scale} (Baseline {baseline[0]}–{baseline[1]})"
        )
        fig_spi.add_hline(y=0, line_dash="dash")
        st.plotly_chart(fig_spi, use_container_width=True)
        
                # ----------------------------------------
        # Seasonal non-stationarity (month-specific)
        # ----------------------------------------
        st.markdown(
            f"### Seasonal SPI distribution – {month_names[selected_month]}"
        )

        spi_clean = spi.dropna()

        # Split by time
        pre_spi = spi_clean[spi_clean.index.year < split_year]
        post_spi = spi_clean[spi_clean.index.year >= split_year]

        # Select month
        pre_spi_m = pre_spi[pre_spi.index.month == selected_month]
        post_spi_m = post_spi[post_spi.index.month == selected_month]

        if len(pre_spi_m) >= 10 and len(post_spi_m) >= 10:

            df_dist = pd.DataFrame({
                "SPI": pd.concat([pre_spi_m, post_spi_m]),
                "Period": (
                    ["Pre-split"] * len(pre_spi_m)
                    + ["Post-split"] * len(post_spi_m)
                )
            })

            x_min = min(df_dist["SPI"]) - 0.5
            x_max = max(df_dist["SPI"]) + 0.5
            x_grid = np.linspace(x_min, x_max, 300)

            fig_dist = go.Figure()

            # Pre-split KDE
            kde_pre = gaussian_kde(pre_spi_m.values)
            fig_dist.add_trace(
                go.Scatter(
                    x=x_grid,
                    y=kde_pre(x_grid),
                    mode="lines",
                    name="Pre-split",
                    line=dict(width=3)
                )
            )

            # Post-split KDE
            kde_post = gaussian_kde(post_spi_m.values)
            fig_dist.add_trace(
                go.Scatter(
                    x=x_grid,
                    y=kde_post(x_grid),
                    mode="lines",
                    name="Post-split",
                    line=dict(width=3)
                )
            )

            fig_dist.update_layout(
                title=(
                    f"{month_names[selected_month]} SPI KDE "
                    f"(Pre vs Post {split_year})"
                ),
                xaxis_title="SPI",
                yaxis_title="Density",
                template="plotly_white"
            )

            st.plotly_chart(fig_dist, use_container_width=True)
        else:
            st.info(
                "Insufficient data for month-specific distribution comparison."
            )


        st.download_button(
            label="Download SPI CSV",
            data=spi_df.to_csv(index=False),
            file_name=f"SPI_{gauge_id}.csv",
            mime="text/csv"
        )
        
                # -------------------------
        # Non-stationarity summary
        # -------------------------
        diag = st.session_state.diagnostics.get(gauge_id)

        if diag is None:
            st.info("Insufficient data for non-stationarity diagnostics.")
        else:
            st.markdown("**Non-stationarity diagnostics (SPI)**")

            st.write(
                pd.DataFrame(
                    {
                        "Pre-split": [diag["mean_pre"], diag["std_pre"]],
                        "Post-split": [diag["mean_post"], diag["std_post"]],
                    },
                    index=["Mean SPI", "Std SPI"]
                )
            )

            st.write(
                f"**KS statistic:** {diag['ks_stat']:.3f}  \n"
                f"**KS p-value:** {diag['ks_pvalue']:.3f}"
            )

            if diag["ks_pvalue"] < 0.05:
                st.warning("SPI distribution differs significantly across the split.")
            else:
                st.success("No strong evidence of distributional change.")


# ==================================================
# PLOT SELECTED VARIABLE (on demand)
# ==================================================
if plot_var:

    st.header(f"{selected_var} (Monthly)")

    for gauge_id, df_monthly in st.session_state.monthly_data.items():

        st.subheader(f"Gauge {gauge_id}")

        var_col = selected_var.lower()

        if var_col == "prcp(mm/day)":
            if "prcp(mm/day)" in df_monthly.columns:
                series = df_monthly["prcp(mm/day)"]
            elif "prcp" in df_monthly.columns:
                series = df_monthly["prcp"]
            else:
                st.warning("Variable not available.")
                continue
        else:
            if var_col not in df_monthly.columns:
                st.warning("Variable not available.")
                continue
            series = df_monthly[var_col]

        var_df = pd.DataFrame({
            "date": df_monthly.index,
            selected_var: series
        })

        fig = px.line(
            var_df,
            x="date",
            y=selected_var,
            title=f"{selected_var} – Gauge {gauge_id}"
        )
        st.plotly_chart(fig, use_container_width=True)

# ==================================================
# SAVE SELECTED VARIABLE CSV (on demand)
# ==================================================
if save_var:

    st.header(f"Download {selected_var} CSV")

    for gauge_id, df_monthly in st.session_state.monthly_data.items():

        var_col = selected_var.lower()

        if var_col not in df_monthly.columns and var_col != "prcp(mm/day)":
            continue

        out_df = pd.DataFrame({
            "date": df_monthly.index,
            selected_var: df_monthly[var_col]
        })

        st.download_button(
            label=f"Download {selected_var} – Gauge {gauge_id}",
            data=out_df.to_csv(index=False),
            file_name=f"{selected_var}_{gauge_id}.csv",
            mime="text/csv"
        )
