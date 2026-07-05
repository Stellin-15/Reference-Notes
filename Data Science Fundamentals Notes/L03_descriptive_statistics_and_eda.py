# ============================================================
# L03: Descriptive Statistics & Exploratory Data Analysis (EDA)
# ============================================================
# WHAT: Summarizing and understanding a dataset BEFORE modeling —
#       measures of central tendency and spread, distribution shape
#       (skewness/kurtosis), outlier detection, and correlation analysis.
# WHY: Every ML project in this repo (ML Frameworks Notes, MLOps Notes)
#      assumes a dataset has already been UNDERSTOOD before a model is
#      trained on it — EDA is the concrete practice of building that
#      understanding, catching data-quality problems before they become
#      model-quality problems.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
MEASURES OF CENTRAL TENDENCY summarize a "typical" value: the MEAN
(arithmetic average — sensitive to outliers), MEDIAN (the middle value
when sorted — robust to outliers), and MODE (the most frequent value).
When mean and median diverge substantially, that itself is a signal —
usually of SKEW (a lopsided distribution) or outliers pulling the mean
away from the more robust median.

MEASURES OF SPREAD quantify how much values VARY: VARIANCE and STANDARD
DEVIATION (its square root, in the same units as the original data,
generally more interpretable) measure spread around the mean; the
INTERQUARTILE RANGE (IQR = Q3 - Q1, the spread of the middle 50% of
data) is a ROBUST alternative less sensitive to outliers than standard
deviation, directly analogous to median vs mean's robustness relationship.

SKEWNESS measures a distribution's ASYMMETRY (a long tail on one side)
and KURTOSIS measures "tailedness" (how much of the variance comes from
rare, extreme outliers vs frequent, moderate deviations) — both matter
because many statistical/ML methods ASSUME roughly normal, symmetric
data, and knowing a dataset violates that assumption (e.g. household
income, which is heavily right-skewed) informs whether transformations
(log transform is common for right-skewed data) or different modeling
choices are needed.

OUTLIER DETECTION (commonly via the IQR method: values below Q1 - 1.5×IQR
or above Q3 + 1.5×IQR are flagged) identifies unusual data points that
may be genuine rare events, data-entry errors, or measurement failures —
EACH requiring a DIFFERENT response (keep, investigate, or remove), so
detection alone is only the first step; the necessary follow-up is
determining WHICH of these an outlier actually is.

CORRELATION (Pearson's r, ranging -1 to +1) measures the LINEAR
relationship strength between two numeric variables — critically,
correlation does NOT imply causation (a classic, important caveat: ice
cream sales and drowning deaths correlate because BOTH are driven by a
third variable, hot weather, not because one causes the other), and
Pearson's r specifically only captures LINEAR relationships, potentially
missing strong NON-linear ones entirely (a scatter plot, this domain's
L06, catches what a single correlation number can miss).

PRODUCTION USE CASE:
Before training a churn-prediction model, an EDA pass on the training
data reveals that a "monthly_charges" feature has a heavily right-skewed
distribution with several extreme outliers (customers paying 50x the
median rate — a data-entry error, on investigation) and a near-zero
correlation with churn using Pearson's r, but a strong pattern visible
in a scatter plot once outliers are removed — findings that DIRECTLY
change the modeling approach (removing the erroneous outliers, applying
a log transform, and reconsidering whether a linear-correlation-based
feature-selection step would have wrongly discarded a genuinely useful,
non-linear feature).

COMMON MISTAKES:
- Reporting ONLY the mean without checking the median or distribution
  shape — a mean can be badly misleading for skewed data (e.g. "average"
  household income is pulled upward by a small number of very high
  earners, making the median a more representative "typical" value).
- Treating EVERY detected outlier as an error to be deleted — some
  outliers are genuine, important rare events (a fraud case, a
  legitimate power user) whose removal would actively HARM a model meant
  to detect exactly those cases.
- Concluding a causal relationship from a strong correlation — the
  ice-cream/drowning example above is the canonical illustration of why
  this inference is invalid without additional evidence (e.g. a
  controlled experiment, or ruling out confounding variables).
"""

import statistics


# ------------------------------------------------------------------
# 1. Central tendency and spread
# ------------------------------------------------------------------
def summarize(data: list[float]) -> dict:
    sorted_data = sorted(data)
    n = len(sorted_data)
    q1 = sorted_data[n // 4]
    q3 = sorted_data[(3 * n) // 4]
    return {
        "mean": statistics.mean(data),
        "median": statistics.median(data),
        "stdev": statistics.stdev(data),
        "iqr": q3 - q1,
        "min": min(data),
        "max": max(data),
    }


def central_tendency_demo():
    # A right-skewed dataset (household income-like) with one extreme outlier
    incomes = [35_000, 42_000, 38_000, 45_000, 40_000, 39_000, 41_000, 5_000_000]
    stats = summarize(incomes)
    print("Income dataset (with one extreme outlier):")
    for key, value in stats.items():
        print(f"  {key}: {value:,.0f}")
    print(f"  -> Mean ({stats['mean']:,.0f}) is dragged FAR from the "
          f"median ({stats['median']:,.0f}) by the single outlier — "
          f"the median is the more representative 'typical' value here.")


# ------------------------------------------------------------------
# 2. Outlier detection via the IQR method
# ------------------------------------------------------------------
def detect_outliers_iqr(data: list[float]) -> list[float]:
    sorted_data = sorted(data)
    n = len(sorted_data)
    q1 = sorted_data[n // 4]
    q3 = sorted_data[(3 * n) // 4]
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    return [x for x in data if x < lower_bound or x > upper_bound]


def outlier_detection_demo():
    monthly_charges = [45, 50, 48, 52, 47, 49, 51, 2500, 46]  # 2500 = likely data entry error
    outliers = detect_outliers_iqr(monthly_charges)
    print(f"Detected outliers (IQR method): {outliers}")
    print("  -> Each flagged outlier needs INVESTIGATION, not automatic "
          "removal — this one (2500 vs a ~48-52 range) is almost "
          "certainly a data-entry error; a genuine high-usage customer "
          "would need a different response than deletion.")


# ------------------------------------------------------------------
# 3. Correlation — and its causation trap
# ------------------------------------------------------------------
def pearson_correlation(x: list[float], y: list[float]) -> float:
    n = len(x)
    mean_x, mean_y = statistics.mean(x), statistics.mean(y)
    numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    denom_x = math_sqrt_sum_sq(x, mean_x)
    denom_y = math_sqrt_sum_sq(y, mean_y)
    return numerator / (denom_x * denom_y)


def math_sqrt_sum_sq(values: list[float], mean: float) -> float:
    return sum((v - mean) ** 2 for v in values) ** 0.5


def correlation_demo():
    # Classic spurious-correlation illustration: ice cream sales vs drownings
    # (both driven by a THIRD variable: hot weather — no causal link between them)
    ice_cream_sales = [10, 20, 35, 50, 60, 55, 40, 25]
    drownings = [2, 4, 7, 10, 12, 11, 8, 5]

    r = pearson_correlation(ice_cream_sales, drownings)
    print(f"Correlation (ice cream sales vs drownings): r = {r:.3f}")
    print("  -> A STRONG correlation, but NOT a causal relationship — "
          "both are driven by a confounding third variable (hot "
          "weather increases both ice cream purchases AND swimming, "
          "hence drowning risk). Correlation alone can never distinguish "
          "this from genuine causation.")


if __name__ == "__main__":
    central_tendency_demo()
    print()
    outlier_detection_demo()
    print()
    correlation_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A data science team investigating a churn model's disappointing accuracy
runs a full EDA pass and discovers: (1) a "tenure_months" feature has a
bimodal, not normal, distribution (two distinct customer populations:
month-to-month and annual-contract customers, requiring separate
handling), (2) a "support_tickets" feature has several extreme outliers
traced to a small number of enterprise accounts with dedicated support
lines (a genuine pattern to preserve, not an error to remove), and (3) a
feature the team assumed was predictive shows near-zero Pearson
correlation with churn — but a closer scatter-plot look (L06) reveals a
strong NON-linear (U-shaped) relationship Pearson's r entirely missed,
directly changing the team's feature-engineering approach.
"""
