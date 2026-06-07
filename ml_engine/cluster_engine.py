import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.exceptions import NotFittedError
import warnings

# Suppress convergence warnings during low-data scenarios
warnings.filterwarnings("ignore", category=UserWarning)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Number of customer segments:
# 0 → Occasional, 1 → Regular, 2 → VIP
N_CLUSTERS = 3

# Human-readable labels mapped to cluster indices after sorting by spending
SEGMENT_LABELS = {
    0: "Occasional",
    1: "Regular",
    2: "VIP"
}

# Tailwind-compatible color tokens for each segment (used by frontend badges)
SEGMENT_COLORS = {
    "Occasional": "slate",
    "Regular":    "sky",
    "VIP":        "amber"
}

# Random state ensures reproducible cluster assignments across restarts
RANDOM_STATE = 42


# ─────────────────────────────────────────────────────────────────────────────
# CORE TRAINING FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def train_customer_clusters(dataframe: pd.DataFrame) -> dict:
    """
    Trains a K-Means model on customer behavioral data and returns
    the trained model, scaler, and cluster assignments.

    The function normalizes input features before clustering so that
    high-value monetary figures do not dominate frequency-based features.

    Args:
        dataframe (pd.DataFrame): Must contain at minimum:
            - 'total_spent'      (float) : Cumulative spend per customer
            - 'visit_frequency'  (int)   : Total number of bookings

    Returns:
        dict with keys:
            - 'model'    : Fitted KMeans instance
            - 'scaler'   : Fitted StandardScaler instance
            - 'labels'   : np.ndarray of raw cluster indices (0, 1, 2)
            - 'segments' : List of human-readable segment names per row
            - 'mapping'  : Dict mapping raw cluster index → segment name
                           (sorted so that 0 = lowest spender, 2 = highest)

    Raises:
        ValueError: If dataframe is missing required columns or has < 3 rows.
    """

    # --- 1. INPUT VALIDATION ---
    required_cols = {"total_spent", "visit_frequency"}
    missing = required_cols - set(dataframe.columns)
    if missing:
        raise ValueError(
            f"Cluster engine requires columns {required_cols}. "
            f"Missing: {missing}"
        )

    if len(dataframe) < N_CLUSTERS:
        raise ValueError(
            f"At least {N_CLUSTERS} customer records are required to train "
            f"the clustering model. Received {len(dataframe)}."
        )

    # --- 2. FEATURE MATRIX ---
    # Select only the two behavioral dimensions for clustering
    X = dataframe[["total_spent", "visit_frequency"]].copy()

    # Fill any nulls defensively (should not occur if service layer sanitizes)
    X = X.fillna(0.0)

    # --- 3. NORMALIZATION ---
    # StandardScaler transforms each feature to mean=0, std=1.
    # This prevents 'total_spent' (large numbers) from overwhelming
    # 'visit_frequency' (small integers) during distance calculations.
    scaler   = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # --- 4. K-MEANS TRAINING ---
    # n_init=10 runs the algorithm 10 times with different centroid seeds
    # and keeps the best result (lowest inertia), improving stability.
    kmeans = KMeans(
        n_clusters=N_CLUSTERS,
        n_init=10,
        random_state=RANDOM_STATE
    )
    raw_labels = kmeans.fit_predict(X_scaled)

    # --- 5. SORT CLUSTERS BY AVERAGE SPENDING ---
    # K-Means assigns arbitrary cluster numbers (0, 1, 2).
    # We re-map them so that the cluster with the lowest average
    # total_spent is always "Occasional" and the highest is "VIP".
    cluster_means = (
        dataframe[["total_spent"]]
        .copy()
        .assign(cluster=raw_labels)
        .groupby("cluster")["total_spent"]
        .mean()
        .sort_values()  # ascending: lowest spend → index 0
    )

    # cluster_means.index holds the original K-Means cluster IDs sorted
    # from lowest to highest mean spend.
    # Map them to our stable segment indices 0, 1, 2.
    rank_mapping = {
        original_id: stable_rank
        for stable_rank, original_id in enumerate(cluster_means.index)
    }

    # Convert raw K-Means labels to stable ranked labels
    stable_labels = np.array([rank_mapping[lbl] for lbl in raw_labels])

    # Build the human-readable segment name for each customer row
    segment_names = [SEGMENT_LABELS[lbl] for lbl in stable_labels]

    # Final mapping dict: stable index → segment name (for API responses)
    segment_mapping = {idx: name for idx, name in SEGMENT_LABELS.items()}

    return {
        "model":    kmeans,
        "scaler":   scaler,
        "labels":   stable_labels,    # np.ndarray, one per customer row
        "segments": segment_names,    # list of strings, one per customer row
        "mapping":  segment_mapping   # {0: "Occasional", 1: "Regular", 2: "VIP"}
    }


# ─────────────────────────────────────────────────────────────────────────────
# PREDICTION HELPER (for classifying new / single customers)
# ─────────────────────────────────────────────────────────────────────────────

def predict_segment(
    model: KMeans,
    scaler: StandardScaler,
    mapping: dict,
    total_spent: float,
    visit_frequency: int
) -> str:
    """
    Classifies a single customer into a segment using an already-trained
    K-Means model and scaler.

    Args:
        model           : Fitted KMeans instance from train_customer_clusters()
        scaler          : Fitted StandardScaler instance from train_customer_clusters()
        mapping         : Segment mapping dict from train_customer_clusters()
        total_spent     : Customer's cumulative spend (float)
        visit_frequency : Customer's total number of bookings (int)

    Returns:
        str: One of "Occasional", "Regular", "VIP"
    """
    X_new    = np.array([[total_spent, visit_frequency]], dtype=float)
    X_scaled = scaler.transform(X_new)
    raw_label = int(model.predict(X_scaled)[0])
    return mapping.get(raw_label, "Occasional")


# ─────────────────────────────────────────────────────────────────────────────
# FALLBACK: Rule-based segmentation when data is too sparse for K-Means
# ─────────────────────────────────────────────────────────────────────────────

def rule_based_segment(total_spent: float, visit_frequency: int) -> str:
    """
    Simple threshold-based fallback used when fewer than 3 distinct customers
    exist within the active data window (K-Means cannot converge with
    < n_clusters rows).

    Thresholds (adjustable based on shop pricing):
        VIP       : spent >= 5000 OR visits >= 20
        Regular   : spent >= 1500 OR visits >= 8
        Occasional: everything else
    """
    if total_spent >= 5000 or visit_frequency >= 20:
        return "VIP"
    elif total_spent >= 1500 or visit_frequency >= 8:
        return "Regular"
    else:
        return "Occasional"


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY: Returns color token for a given segment name
# ─────────────────────────────────────────────────────────────────────────────

def get_segment_color(segment_name: str) -> str:
    """
    Returns the Tailwind color token associated with a segment.
    Used by the frontend to render the correct badge color.

    Returns:
        str: "slate" | "sky" | "amber"
    """
    return SEGMENT_COLORS.get(segment_name, "slate")