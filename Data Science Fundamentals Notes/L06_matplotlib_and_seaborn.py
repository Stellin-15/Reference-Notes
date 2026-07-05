# ============================================================
# L06: Data Visualization with Matplotlib and Seaborn
# ============================================================
# WHAT: Python's two standard plotting libraries — Matplotlib (the
#       low-level, highly customizable foundation) and Seaborn (a
#       higher-level statistical-visualization layer built on top of it)
#       — and which chart type fits which analytical question.
# WHY: L03's EDA (descriptive statistics) frequently needs VISUAL
#      confirmation — a correlation number alone can hide a strong
#      non-linear relationship a scatter plot reveals instantly; this
#      lesson provides the concrete tools for that visual layer.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
MATPLOTLIB is Python's foundational plotting library — LOW-LEVEL and
highly customizable (every pixel is, in principle, controllable), but
this flexibility means common statistical charts require more code than
feels proportional to the task. SEABORN is built ON TOP of Matplotlib,
providing HIGH-LEVEL functions specifically for STATISTICAL
visualization (distributions, categorical comparisons, correlation
heatmaps) with sensible defaults — most day-to-day EDA visualization
uses Seaborn for speed, dropping to raw Matplotlib when a specific
customization Seaborn doesn't expose is needed.

CHOOSING THE RIGHT CHART TYPE is the actual skill here, not memorizing
API syntax: a HISTOGRAM shows a single numeric variable's DISTRIBUTION
shape (directly visualizing L03's skewness/outlier concepts); a
SCATTER PLOT shows the RELATIONSHIP between two numeric variables
(catching non-linear patterns a single Pearson correlation number
misses entirely); a BOX PLOT compares a numeric variable's distribution
ACROSS categories (showing median, IQR, and outliers per category
simultaneously); a BAR CHART compares a single aggregated value ACROSS
categories; a HEATMAP visualizes a MATRIX of values (most commonly, a
full correlation matrix across many variables at once, extending L03's
pairwise correlation to many variables simultaneously).

A common EDA workflow: compute a CORRELATION MATRIX across all numeric
features, visualize it as a heatmap to spot strong relationships at a
glance, then drill into individual PAIRS with scatter plots to check
whether each strong correlation is genuinely LINEAR (as Pearson's r
assumes) or actually a different shape entirely.

PRODUCTION USE CASE:
A data scientist investigating why a regression model performs poorly
on a subset of data plots RESIDUALS (prediction errors) against each
input feature using scatter plots — a clear PATTERN in the residuals for
one specific feature (rather than random scatter) reveals the model is
systematically missing a relationship with that feature, a diagnostic
insight a single aggregate error metric (like RMSE) would never surface.

COMMON MISTAKES:
- Relying SOLELY on correlation numbers (L03) without ever plotting a
  scatter plot — "Anscombe's Quartet" is the classic illustration: four
  datasets with NEARLY IDENTICAL summary statistics (mean, variance,
  correlation) that look COMPLETELY different when actually plotted
  (linear, curved, one outlier driving everything, etc.) — a stark
  reminder that summary statistics alone can hide critical structure.
- Choosing a bar chart to show a DISTRIBUTION (use a histogram instead)
  or a line chart to compare unrelated CATEGORIES (implying an ordering/
  trend that doesn't exist) — each chart type carries an implicit claim
  about the data's structure, and using the wrong one can mislead
  viewers even with entirely accurate underlying numbers.
- Overplotting (thousands of overlapping points in a scatter plot,
  rendering as one indistinguishable blob) without addressing it via
  transparency (alpha blending), sampling, or a 2D density/hexbin plot —
  a chart that's technically accurate but visually uninterpretable fails
  its actual purpose.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Matplotlib — low-level, foundational
# ------------------------------------------------------------------
MATPLOTLIB_EXAMPLE = textwrap.dedent("""\
    import matplotlib.pyplot as plt

    # A histogram — visualizing a single variable's DISTRIBUTION shape
    # (directly visualizing L03's skewness/outlier concepts)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(monthly_charges, bins=30, edgecolor='black')
    ax.set_xlabel('Monthly Charges')
    ax.set_ylabel('Frequency')
    ax.set_title('Distribution of Monthly Charges')
    plt.savefig('distribution.png', dpi=150, bbox_inches='tight')

    # A scatter plot — visualizing the RELATIONSHIP between two variables,
    # catching non-linear patterns a Pearson correlation number would miss
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(tenure_months, monthly_charges, alpha=0.3)   # alpha handles overplotting
    ax.set_xlabel('Tenure (months)')
    ax.set_ylabel('Monthly Charges')
    plt.savefig('scatter.png', dpi=150, bbox_inches='tight')
""")

# ------------------------------------------------------------------
# 2. Seaborn — high-level statistical visualization
# ------------------------------------------------------------------
SEABORN_EXAMPLE = textwrap.dedent("""\
    import seaborn as sns
    import matplotlib.pyplot as plt

    # A box plot — comparing a numeric variable's distribution ACROSS
    # categories (median, IQR, and outliers per category at a glance)
    sns.boxplot(data=df, x='contract_type', y='monthly_charges')
    plt.title('Monthly Charges by Contract Type')
    plt.savefig('boxplot.png', dpi=150, bbox_inches='tight')

    # A correlation HEATMAP — visualizing many pairwise correlations at
    # once, extending L03's single-pair Pearson correlation to a full matrix
    correlation_matrix = df[numeric_columns].corr()
    sns.heatmap(correlation_matrix, annot=True, cmap='coolwarm', center=0)
    plt.title('Feature Correlation Matrix')
    plt.savefig('heatmap.png', dpi=150, bbox_inches='tight')

    # A pair plot — scatter plots for EVERY pair of numeric variables at
    # once, a fast way to visually scan for non-linear relationships
    # across an entire dataset in one command
    sns.pairplot(df[numeric_columns], diag_kind='kde')
    plt.savefig('pairplot.png', dpi=150, bbox_inches='tight')
""")

# ------------------------------------------------------------------
# 3. Anscombe's Quartet — why you must actually LOOK at the data
# ------------------------------------------------------------------
ANSCOMBES_QUARTET_LESSON = textwrap.dedent("""\
    Anscombe's Quartet: four datasets, each with:
      - Nearly identical mean (x and y)
      - Nearly identical variance
      - Nearly identical Pearson correlation (~0.816)
      - Nearly identical linear regression line

    Yet when actually PLOTTED:
      Dataset 1: a genuine linear relationship with normal scatter
      Dataset 2: a clear CURVED (non-linear) relationship
      Dataset 3: a perfect linear relationship EXCEPT one outlier
                 that's entirely responsible for the correlation
      Dataset 4: most points share the SAME x value; one outlier
                 point alone creates the appearance of correlation

    Lesson: summary statistics (L03) can be IDENTICAL across datasets
    with completely different underlying structure. A scatter plot
    catches this instantly; correlation numbers alone never will.
""")


if __name__ == "__main__":
    print(MATPLOTLIB_EXAMPLE)
    print(SEABORN_EXAMPLE)
    print(ANSCOMBES_QUARTET_LESSON)

"""
PRODUCTION CONTEXT EXAMPLE:
A data science team automates a "model monitoring" report that plots
prediction RESIDUALS as a scatter plot against each input feature,
alongside a correlation heatmap of ALL features, every time a model is
retrained — a residual scatter plot with a visible curved pattern (not
random noise) against a specific feature flagged, in one real incident,
a systematic underprediction for high-tenure customers that a single
aggregate accuracy metric had completely masked, directly leading to a
feature-engineering fix (adding a tenure-squared term) that a
metrics-only monitoring approach would never have surfaced.
"""
