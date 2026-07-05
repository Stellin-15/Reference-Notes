# ============================================================
# L05: Linear Algebra for Machine Learning
# ============================================================
# WHAT: The core linear algebra objects and operations ML actually uses —
#       vectors, matrices, matrix multiplication, dot products, and
#       dimensionality reduction via eigenvectors (PCA).
# WHY: This repo's L01_embeddings_fundamentals.py (Agentic AI & RAG
#      Notes) and GPU Computing & Distributed Training Notes both treat
#      "vectors," "matrix multiplication," and "dimensionality" as
#      already-understood terms — this lesson builds that foundation.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
A VECTOR is an ordered list of numbers — geometrically, a point in
N-dimensional space, or an arrow from the origin to that point. In ML,
vectors represent EVERYTHING: a data point's features, a word's
embedding (this repo's Agentic AI & RAG Notes L02), a model's weight
parameters. A MATRIX is a 2D grid of numbers — a batch of data points is
naturally a matrix (rows = examples, columns = features), and a neural
network LAYER's weights are literally a matrix.

The DOT PRODUCT of two vectors (multiply corresponding elements, sum the
results) measures how much two vectors point in the SAME direction —
critically, this is EXACTLY how COSINE SIMILARITY (the standard way to
compare embedding vectors, this repo's L02/L03 in Agentic AI & RAG
Notes) is computed (the dot product, normalized by vector lengths) —
two embedding vectors with a high dot product/cosine similarity
represent semantically SIMILAR content.

MATRIX MULTIPLICATION combines two matrices via repeated dot products
(each output element is the dot product of a row from the first matrix
and a column from the second) — this is the SINGLE most computationally
expensive operation in deep learning: every neural network layer's
forward pass is fundamentally a matrix multiplication (input matrix ×
weight matrix), which is EXACTLY why GPUs (this repo's GPU Computing &
Distributed Training Notes L01-L03) are built around specialized Tensor
Cores optimized specifically for fast matrix multiplication at scale.

EIGENVECTORS and EIGENVALUES describe a matrix's fundamental "stretching
directions" — a matrix applied to its eigenvector only SCALES it (by the
eigenvalue) rather than rotating it. PRINCIPAL COMPONENT ANALYSIS (PCA),
a common DIMENSIONALITY REDUCTION technique, finds the eigenvectors of a
dataset's covariance matrix — these eigenvectors point in the directions
of MAXIMUM VARIANCE in the data, letting you project high-dimensional
data onto just a FEW of these directions (the top eigenvectors) while
preserving as much of the original information (variance) as possible.

PRODUCTION USE CASE:
A recommendation system computes user-item affinity via the DOT PRODUCT
of a user's embedding vector and each candidate item's embedding vector
(both learned via matrix factorization/neural collaborative filtering) —
the highest dot-product items are the most-recommended, a direct,
production-scale application of the same dot-product-as-similarity
concept underlying semantic search over text embeddings.

COMMON MISTAKES:
- Confusing DOT PRODUCT similarity with COSINE similarity when comparing
  embedding vectors of DIFFERENT magnitudes — the raw dot product is
  sensitive to vector LENGTH, not just direction; cosine similarity
  (dot product divided by both vectors' magnitudes) is needed when
  comparing vectors that aren't already normalized to unit length —
  many vector databases (Agentic AI & RAG Notes L03) default to one or
  the other, and mismatching this with how embeddings were actually
  generated silently produces incorrect similarity rankings.
- Applying PCA/dimensionality reduction WITHOUT first standardizing
  features to comparable scales — a feature measured in the thousands
  (e.g. income) will dominate the variance calculation over a feature
  measured in single digits (e.g. age), even if the smaller-scale
  feature is actually more informative, purely due to the scale
  mismatch rather than genuine importance.
- Treating matrix multiplication as commutative (A×B = B×A) — it
  generally is NOT for matrices (order matters, and the dimensions must
  even be compatible in the first place), unlike scalar multiplication.
"""

import math


# ------------------------------------------------------------------
# 1. Vectors, dot product, and cosine similarity
# ------------------------------------------------------------------
def dot_product(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def magnitude(v: list[float]) -> float:
    return math.sqrt(sum(x ** 2 for x in v))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    return dot_product(a, b) / (magnitude(a) * magnitude(b))


def similarity_demo():
    # Simplified "embedding" vectors representing three short phrases
    king = [0.9, 0.1, 0.8]
    queen = [0.85, 0.15, 0.75]      # semantically close to "king"
    banana = [0.05, 0.9, 0.1]       # semantically unrelated

    print(f"Dot product (king, queen): {dot_product(king, queen):.3f}")
    print(f"Cosine similarity (king, queen): {cosine_similarity(king, queen):.3f}")
    print(f"Cosine similarity (king, banana): {cosine_similarity(king, banana):.3f}")
    print("  -> 'king' and 'queen' have HIGH cosine similarity (semantically "
          "related); 'king' and 'banana' have LOW similarity — this is "
          "EXACTLY how a vector database ranks semantic search results.")


# ------------------------------------------------------------------
# 2. Matrix multiplication — the core neural network operation
# ------------------------------------------------------------------
def matrix_multiply(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    rows_a, cols_a = len(a), len(a[0])
    cols_b = len(b[0])
    result = [[0.0] * cols_b for _ in range(rows_a)]
    for i in range(rows_a):
        for j in range(cols_b):
            # Each output element IS a dot product: row i of A, column j of B
            result[i][j] = sum(a[i][k] * b[k][j] for k in range(cols_a))
    return result


def neural_network_layer_demo():
    # A "batch" of 2 input examples, each with 3 features
    input_batch = [
        [1.0, 0.5, 0.2],
        [0.3, 0.8, 0.1],
    ]
    # A "weight matrix" projecting 3 input features down to 2 output neurons
    weights = [
        [0.5, 0.1],
        [0.2, 0.4],
        [0.3, 0.6],
    ]

    output = matrix_multiply(input_batch, weights)
    print("Input batch (2 examples x 3 features) x Weight matrix (3 x 2 neurons):")
    print(f"  Output (2 examples x 2 neurons): {output}")
    print("  -> This IS a neural network layer's forward pass — every "
          "layer in every neural network in this repo's ML Frameworks "
          "Notes and GPU Computing Notes is fundamentally this operation, "
          "repeated at massive scale.")


# ------------------------------------------------------------------
# 3. Dimensionality reduction intuition (PCA, conceptual)
# ------------------------------------------------------------------
def pca_intuition_demo():
    print("PCA conceptual walkthrough (no eigenvector solver implemented here):")
    print("  1. Start with high-dimensional data (e.g. 768-dimension embeddings).")
    print("  2. Compute the data's COVARIANCE matrix (how features vary together).")
    print("  3. Find that matrix's EIGENVECTORS — directions of maximum variance.")
    print("  4. Project the data onto the TOP few eigenvectors (e.g. just 2 or 3).")
    print("  -> Result: a 2D/3D representation preserving as much of the")
    print("     original variance/information as possible — used for")
    print("     visualizing high-dimensional embeddings, or as a")
    print("     preprocessing step before a downstream model.")
    print("  -> CRITICAL: standardize features to comparable scales FIRST —")
    print("     otherwise a large-scale feature dominates the variance")
    print("     calculation purely due to scale, not genuine importance.")


if __name__ == "__main__":
    similarity_demo()
    print()
    neural_network_layer_demo()
    print()
    pca_intuition_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A semantic search system generates a 768-dimensional embedding vector
for a user's query (Agentic AI & RAG Notes L02), then computes COSINE
SIMILARITY (built directly on the dot product and vector magnitude
concepts in this lesson) against millions of pre-computed document
embeddings stored in a vector database (Agentic AI & RAG Notes L03) —
the entire semantic search stack is, at its mathematical core, exactly
the dot-product/cosine-similarity computation demonstrated above,
scaled to millions of vectors via specialized indexing (HNSW) rather
than a brute-force comparison against every document.
"""
