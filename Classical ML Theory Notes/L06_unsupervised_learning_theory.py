"""
WHAT: Principal Component Analysis derived two equivalent ways -- as
      variance-maximizing projection (eigendecomposition of the
      covariance matrix) and as the best low-rank reconstruction (SVD)
      -- plus hierarchical clustering and where t-SNE/UMAP fit relative
      to PCA.
WHY:  "PCA finds the directions of maximum variance" is usually stated
      without proof, and "PCA and SVD are related" is usually left vague
      about exactly how. This lesson derives PCA from an explicit
      optimization problem via Lagrange multipliers (mirroring L04's SVM
      derivation pattern) and shows the SVD connection is an EXACT
      algebraic identity, not an approximation.
LEVEL: Foundational.

PREREQUISITE: Data Science Fundamentals Notes L05 (linear algebra for ML
-- eigenvectors, matrix multiplication). L04 of this domain (Lagrangian
duality) for the PCA derivation's structure.
"""

import numpy as np

# ============================================================================
# CONCEPT #1 — PCA DERIVED FROM FIRST PRINCIPLES: MAXIMIZE VARIANCE OF THE
# PROJECTION
# ============================================================================
#
# Given centered data X (n rows, p features, each column mean-subtracted),
# PCA seeks a unit vector w (||w||=1) such that projecting each row x_i
# onto w -- the scalar w^T*x_i -- has MAXIMUM VARIANCE across the dataset.
# Intuition: the direction along which the data varies the most is the
# direction that preserves the most "information" (in a variance sense)
# about the original points when you compress each point down to a
# single number.
#
# The variance of the projections is:
#   Var(w^T*x) = (1/n) * sum_i (w^T*x_i)^2  =  w^T * Sigma * w
#   where Sigma = (1/n) * X^T*X   is the p x p sample covariance matrix
#   (X already centered, so this is exactly the covariance formula).
#
# Maximizing w^T*Sigma*w over all w is UNBOUNDED without a constraint
# (scale w up, the "variance" grows without limit) -- hence the ||w||=1
# constraint. This is a constrained optimization, solved with a Lagrange
# multiplier exactly like L04's SVM margin derivation:
#
#   L(w, lambda) = w^T*Sigma*w  -  lambda*(w^T*w - 1)
#   dL/dw = 2*Sigma*w - 2*lambda*w = 0
#   =>  Sigma * w = lambda * w
#
# THIS IS THE EIGENVALUE EQUATION. The optimal w is an EIGENVECTOR of the
# covariance matrix Sigma, and the corresponding eigenvalue lambda equals
# the variance captured (substitute back: w^T*Sigma*w = w^T*lambda*w =
# lambda*(w^T*w) = lambda). Since Sigma is symmetric, it has p real
# orthogonal eigenvectors with real eigenvalues -- SORT them by eigenvalue
# descending, and the top-k eigenvectors are exactly the first k PRINCIPAL
# COMPONENTS: the k mutually orthogonal directions capturing the most
# variance, subject to each being orthogonal to all previous ones (a fact
# that itself falls out of the eigenvectors of a symmetric matrix being
# automatically orthogonal -- not an extra constraint you need to impose).
#
# This derivation is worth internalizing because it explains a fact
# usually just asserted: "PCA components are ordered by variance
# explained, and are uncorrelated with each other" isn't a design choice
# -- it's a direct consequence of Sigma being symmetric and PCA being
# defined as its eigendecomposition.

def pca_via_eigendecomposition(X, n_components):
    X_centered = X - X.mean(axis=0)
    Sigma = (X_centered.T @ X_centered) / X_centered.shape[0]
    eigvals, eigvecs = np.linalg.eigh(Sigma)  # eigh: Sigma is symmetric
    # eigh returns ascending order -- reverse to get descending (most
    # variance first), matching "principal component 1 explains the most."
    order = np.argsort(eigvals)[::-1]
    eigvals, eigvecs = eigvals[order], eigvecs[:, order]
    components = eigvecs[:, :n_components]
    explained_variance_ratio = eigvals[:n_components] / eigvals.sum()
    projected = X_centered @ components
    return projected, components, explained_variance_ratio


# ============================================================================
# CONCEPT #2 — PCA VIA SVD: THE SAME ANSWER, DERIVED DIFFERENTLY, AND WHY
# PRODUCTION LIBRARIES USE SVD NOT EIGENDECOMPOSITION
# ============================================================================
#
# Every matrix X (n x p) has a Singular Value Decomposition:
#   X = U * S * V^T
# where U (n x n) and V (p x p) are orthogonal, S (n x p) is diagonal with
# non-negative entries (the singular values, sigma_1 >= sigma_2 >= ...)
# on the diagonal.
#
# THE EXACT ALGEBRAIC LINK TO CONCEPT #1: compute X^T*X using the SVD:
#   X^T*X = (U*S*V^T)^T * (U*S*V^T) = V*S^T*U^T*U*S*V^T = V*S^T*S*V^T
#   (U^T*U = I because U is orthogonal)
#   = V * S^2 * V^T           (S^T*S is diagonal with entries sigma_i^2)
#
# Compare to the covariance matrix's eigendecomposition Sigma = W*Lambda*W^T
# (W = eigenvectors, Lambda = eigenvalues, and Sigma = X^T*X / n). Matching
# terms: V = W (the SVD's right singular vectors ARE the covariance
# matrix's eigenvectors) and sigma_i^2 / n = lambda_i (squared singular
# values, scaled by n, equal the eigenvalues). This is not an
# approximation or a coincidence -- it is the same mathematical object
# computed two different ways, which is EXACTLY why sklearn's PCA and
# essentially every production implementation compute PCA via SVD of X
# directly, rather than explicitly forming X^T*X and eigendecomposing it:
#
#   NUMERICAL REASON SVD WINS: forming X^T*X squares the CONDITION NUMBER
#   of the problem (if X has condition number kappa, X^T*X has condition
#   number kappa^2) -- for even moderately ill-conditioned data, computing
#   eigenvectors of X^T*X directly can be substantially less numerically
#   accurate than computing the SVD of X itself, which never explicitly
#   forms X^T*X. This is a real, measurable numerical-stability
#   difference, not a stylistic preference between two "equally good"
#   methods.

def pca_via_svd(X, n_components):
    X_centered = X - X.mean(axis=0)
    U, S, Vt = np.linalg.svd(X_centered, full_matrices=False)
    components = Vt[:n_components].T  # V's columns = covariance eigenvectors
    eigvals = (S ** 2) / X_centered.shape[0]  # sigma_i^2/n = lambda_i, as derived above
    explained_variance_ratio = eigvals[:n_components] / eigvals.sum()
    projected = X_centered @ components
    return projected, components, explained_variance_ratio


# ============================================================================
# CONCEPT #3 — PCA MINIMIZES RECONSTRUCTION ERROR (the OTHER equivalent
# derivation, useful for a different intuition: compression, not variance)
# ============================================================================
#
# A completely separate starting point arrives at the identical answer:
# among all rank-k approximations X_hat of X, which one minimizes the
# total squared reconstruction error ||X - X_hat||^2 (Frobenius norm)?
#
# THE ECKART-YOUNG THEOREM answers this exactly: the best rank-k
# approximation (in this squared-error sense) is obtained by keeping only
# the top-k singular values/vectors of the SVD and zeroing the rest:
#   X_hat_k = U_k * S_k * V_k^T
# This is the SAME V_k (right singular vectors) that Concept #2 showed
# equals the PCA components. So "PCA finds the directions of maximum
# variance" and "PCA finds the best low-rank reconstruction of the data"
# are not two different properties PCA happens to have -- they are
# PROVABLY THE SAME optimization problem, viewed from two directions
# (maximize variance captured vs. minimize information/energy discarded
# -- these are complementary because total variance is fixed, so
# maximizing captured variance is arithmetically identical to minimizing
# discarded variance/reconstruction error).
#
# WHY THIS SECOND VIEW MATTERS PRACTICALLY: it's the derivation that
# generalizes to non-square, non-covariance settings -- e.g. it's exactly
# the mathematical justification for using truncated SVD to compress a
# recommendation-system ratings matrix, or to build low-rank
# approximations of word-embedding co-occurrence matrices (classic LSA).
# "Best low-rank approximation" is the more portable framing; "directions
# of maximum variance" is the more common one in intro ML courses,
# because they're literally the same theorem.

def reconstruction_error(X, n_components):
    """Confirms Concept #3 numerically: reconstructing X from its top-k
    PCA components has strictly less error than from ANY other choice of
    k orthogonal directions, verified here against a few random
    alternative k-dim subspaces (a full proof of Eckart-Young is out of
    scope, but this demonstrates the claim on concrete alternatives)."""
    X_centered = X - X.mean(axis=0)
    _, components, _ = pca_via_svd(X, n_components)
    projected = X_centered @ components
    reconstructed = projected @ components.T
    pca_error = np.sum((X_centered - reconstructed) ** 2)

    rng = np.random.default_rng(2)
    random_errors = []
    for _ in range(20):
        random_dirs, _ = np.linalg.qr(rng.normal(size=(X.shape[1], n_components)))
        proj = X_centered @ random_dirs
        recon = proj @ random_dirs.T
        random_errors.append(np.sum((X_centered - recon) ** 2))

    return pca_error, min(random_errors)


# ============================================================================
# CONCEPT #4 — HIERARCHICAL CLUSTERING, AND WHERE PCA/T-SNE/UMAP DIFFER IN
# PURPOSE
# ============================================================================
#
# HIERARCHICAL (AGGLOMERATIVE) CLUSTERING: start with every point as its
# own cluster; repeatedly merge the two CLOSEST clusters (by some linkage
# criterion -- single/complete/average/Ward) until one cluster remains,
# recording the merge order as a dendrogram. Unlike k-means (L05), it
# requires no upfront choice of K -- you choose K after the fact by
# "cutting" the dendrogram at whatever height gives the desired number of
# clusters, and the FULL merge hierarchy (not just one clustering) is
# available for inspection. Cost is O(n^2 log n) or worse depending on
# linkage, versus k-means' roughly-linear-per-iteration cost -- this is
# the main reason hierarchical clustering is used on hundreds/thousands
# of points, not millions.
#
# WHY LINKAGE CHOICE MATTERS (a real design decision, not a default to
# ignore): single linkage (distance = closest pair between two clusters)
# can produce long, straggly "chaining" clusters -- two genuinely distinct
# blobs connected by a thin bridge of intermediate points get merged into
# one cluster. Complete linkage (distance = farthest pair) avoids
# chaining but can be overly sensitive to outliers (one far point inflates
# the "distance" between otherwise-close clusters). Ward's method
# (minimize the increase in within-cluster variance from each merge) is
# closest in spirit to k-means' objective and is the most common default
# for roughly-spherical-cluster assumptions.
#
# PCA VS T-SNE/UMAP -- NOT INTERCHANGEABLE TOOLS FOR "DIMENSIONALITY
# REDUCTION," DESPITE BOTH PRODUCING A 2D SCATTER PLOT:
#   - PCA is a LINEAR, GLOBAL-STRUCTURE-PRESERVING projection (per
#     Concept #3, it explicitly minimizes GLOBAL reconstruction error).
#     Distances in PCA space are directly, if imperfectly, related to
#     distances in the original space. It's deterministic and invertible
#     (up to the discarded components).
#   - t-SNE/UMAP are NONLINEAR, LOCAL-STRUCTURE-PRESERVING embeddings --
#     they explicitly optimize to keep points that were NEAR each other
#     in the original high-dimensional space near each other in the 2D
#     embedding, at the deliberate cost of NOT preserving global distances
#     or densities faithfully. This is why comparing the SIZE or
#     inter-cluster DISTANCE of blobs in a t-SNE plot is a well-documented
#     misinterpretation (a common one even among practitioners) -- t-SNE's
#     objective simply doesn't optimize for that; only intra-cluster
#     proximity/local neighborhoods are meaningful. t-SNE and UMAP are
#     also stochastic and non-invertible (there's no way to map a new
#     point into an existing t-SNE embedding without re-running the whole
#     algorithm), unlike PCA.
# PRACTICAL RULE: use PCA when you need an interpretable, invertible,
# variance-ranked reduction (e.g. as a preprocessing step before a linear
# model, or when you need to reduce a NEW point without re-fitting). Use
# t-SNE/UMAP when the deliverable is purely a VISUALIZATION for spotting
# local cluster structure, and you're not going to draw quantitative
# conclusions from the geometry of the resulting plot.


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A recommendation team wants to compress a 50,000-item x 2,000-user
# sparse ratings matrix, AND separately wants a slide-deck visualization
# of "user segments." These are DIFFERENT problems, correctly solved with
# different tools from this lesson:
#   - The compression problem is directly Concept #3's low-rank-
#     reconstruction framing: truncated SVD gives the mathematically-
#     optimal rank-k approximation of the ratings matrix (this is the
#     classical matrix-factorization recommender-system approach) --
#     using PCA/SVD here isn't a visualization convenience, it's the
#     literal best solution to "minimize reconstruction error at this
#     rank," proven by Eckart-Young.
#   - The visualization problem should use UMAP (or t-SNE), NOT PCA's
#     top-2 components -- with 2,000 users compressed to only 2 PCA
#     dimensions, most of the variance in a genuinely high-dimensional
#     user-behavior space is lost (2 components rarely capture more than
#     a small fraction of total variance in real behavioral data), and
#     the resulting plot will look like an uninformative blob. UMAP's
#     local-structure focus is far more likely to visually separate
#     genuine user segments, at the explicit cost (which the presenter
#     MUST caveat) that inter-cluster distances/sizes in the plot are not
#     quantitatively meaningful.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Running PCA on unstandardized features. Per Concept #1, PCA
#    maximizes VARIANCE of the projection -- if one feature is measured in
#    a unit with naturally huge numeric range (e.g. income in dollars vs.
#    age in years), it will dominate the "variance" captured by PC1 for
#    reasons entirely about unit choice, not genuine informativeness.
#    Standardize (zero mean, unit variance) before PCA unless you have a
#    specific reason not to (e.g. all features already share meaningful,
#    comparable units).
# 2. Forming X^T*X explicitly and eigendecomposing it in code, instead of
#    calling SVD directly on X. Per Concept #2, this squares the
#    condition number and measurably degrades numerical accuracy on
#    anything but well-conditioned toy data -- a real bug class in hand-
#    rolled PCA implementations, not a pedantic style complaint.
# 3. Interpreting distances or cluster sizes on a t-SNE/UMAP plot as
#    meaningful (Concept #4). This is common enough to call out
#    explicitly: "cluster A looks twice as big as cluster B" or "clusters
#    C and D are far apart, so they're very different" are NOT claims
#    these algorithms' objectives support -- only "points within a visible
#    cluster were near each other in the original space" is.
# 4. Choosing the number of PCA components by an arbitrary round number
#    (e.g. "always keep 2, for plotting") rather than by inspecting the
#    explained_variance_ratio / a scree plot / a downstream-task
#    validation metric. The right k depends entirely on how much variance
#    the data's true structure actually concentrates into few directions
#    -- there's no universal correct k.


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    # Correlated 2D data stretched along one direction -- an easy case to
    # visually/numerically confirm PCA finds the stretched axis.
    base = rng.normal(size=(300, 2))
    transform = np.array([[3, 1], [0, 0.5]])  # stretches + shears
    X = base @ transform.T

    print("=" * 70)
    print("PCA VIA EIGENDECOMPOSITION vs PCA VIA SVD: identical result")
    print("=" * 70)
    _, comp_eig, var_eig = pca_via_eigendecomposition(X, n_components=2)
    _, comp_svd, var_svd = pca_via_svd(X, n_components=2)
    print(f"Explained variance ratio (eigendecomposition): {np.round(var_eig, 4)}")
    print(f"Explained variance ratio (SVD):                 {np.round(var_svd, 4)}")
    print(f"Components match up to sign flip: "
          f"{np.allclose(np.abs(comp_eig), np.abs(comp_svd), atol=1e-6)}")
    print("-> Confirms Concept #2's claim: these are the same computation,")
    print("   not two different techniques that happen to agree.")

    print("\n" + "=" * 70)
    print("PCA MINIMIZES RECONSTRUCTION ERROR vs. random orthogonal directions")
    print("=" * 70)
    pca_err, best_random_err = reconstruction_error(X, n_components=1)
    print(f"Reconstruction error using top-1 PCA component:    {pca_err:.4f}")
    print(f"Best of 20 random 1D projections' reconstruction:   {best_random_err:.4f}")
    print(f"PCA error <= best random error? {pca_err <= best_random_err + 1e-6}")
    print("-> Numerically confirms Eckart-Young: no other single direction")
    print("   reconstructs the data better than PCA's top component.")
