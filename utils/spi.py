import numpy as np
import pandas as pd
from scipy.stats import gamma, norm


def compute_spi(prcp, scale, baseline_years, dates):
    """
    Robust SPI computation that NEVER crashes.
    Returns NaNs if SPI is not statistically computable.
    """

    # Build series
    prcp = pd.to_numeric(prcp, errors="coerce")
    df = pd.DataFrame({"prcp": prcp}, index=dates)

    # Rolling accumulation
    acc = df["prcp"].rolling(scale, min_periods=scale).sum()
    acc = acc.dropna()

    if acc.empty:
        return pd.Series(index=acc.index, data=np.nan)

    # Baseline slice
    baseline_mask = (
        (acc.index.year >= baseline_years[0]) &
        (acc.index.year <= baseline_years[1])
    )

    baseline_data = acc.loc[baseline_mask].values

    # Clean data HARD
    baseline_data = baseline_data[np.isfinite(baseline_data)]
    baseline_data = baseline_data[baseline_data > 0]

    # Absolute stop conditions
    if len(baseline_data) < 30:
        return pd.Series(index=acc.index, data=np.nan)

    if np.allclose(baseline_data, baseline_data[0]):
        return pd.Series(index=acc.index, data=np.nan)

    # Gamma fit (fully protected)
    try:
        shape, loc, scale_param = gamma.fit(baseline_data, floc=0)
    except Exception:
        return pd.Series(index=acc.index, data=np.nan)

    # Transform to SPI
    cdf = gamma.cdf(acc, shape, loc=0, scale=scale_param)
    cdf = np.clip(cdf, 1e-6, 1 - 1e-6)

    spi = norm.ppf(cdf)

    return pd.Series(spi, index=acc.index)
