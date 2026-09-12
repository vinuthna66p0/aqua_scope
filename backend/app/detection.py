"""
Synthetic SAR candidate detection + look-alike (false-positive) filtering.

A RandomForestClassifier is trained at startup on a synthetic, labelled
feature set (oil-like vs look-alike dark regions). This is NOT trained on
real SAR imagery — it demonstrates the *workflow* (feature extraction ->
candidate classification -> confidence score) that a real system would
follow once trained on labelled Sentinel-1 data.

Features used (all synthetic, but modeled on properties real SAR
oil-spill/look-alike discrimination literature commonly cites):
  - darkness_contrast   : how much darker the region is vs surrounding sea
  - edge_sharpness       : oil slicks often show smoother/sharper boundaries
  - shape_elongation     : elongation ratio (length/width)
  - texture_variance     : internal texture homogeneity
  - area_km2             : object size
  - wind_speed_ctx       : low wind can create look-alike dark patches
  - proximity_to_shipping: vessel wakes look-alike often close to lanes
"""
import numpy as np
from sklearn.ensemble import RandomForestClassifier

FEATURE_NAMES = [
    "darkness_contrast", "edge_sharpness", "shape_elongation",
    "texture_variance", "area_km2", "wind_speed_ctx", "proximity_to_shipping",
]

_rng = np.random.default_rng(42)


def _synthetic_training_set(n_per_class=400):
    # LIKELY OIL: high contrast, smooth/sharp edges, elongated, low texture variance
    oil = np.column_stack([
        _rng.normal(0.75, 0.08, n_per_class).clip(0.3, 1.0),
        _rng.normal(0.70, 0.10, n_per_class).clip(0.2, 1.0),
        _rng.normal(6.0, 2.0, n_per_class).clip(1.5, 15),
        _rng.normal(0.15, 0.05, n_per_class).clip(0.02, 0.5),
        _rng.normal(9.0, 5.0, n_per_class).clip(0.5, 40),
        _rng.normal(6.0, 2.5, n_per_class).clip(0.5, 15),
        _rng.normal(4.0, 3.0, n_per_class).clip(0.1, 20),
    ])
    # LOOK-ALIKE: lower/inconsistent contrast, rougher edges, less elongated, higher texture noise
    lookalike = np.column_stack([
        _rng.normal(0.40, 0.15, n_per_class).clip(0.05, 0.9),
        _rng.normal(0.35, 0.15, n_per_class).clip(0.05, 0.9),
        _rng.normal(2.2, 1.2, n_per_class).clip(1.0, 8),
        _rng.normal(0.45, 0.15, n_per_class).clip(0.05, 0.9),
        _rng.normal(3.0, 3.0, n_per_class).clip(0.05, 15),
        _rng.normal(2.5, 2.5, n_per_class).clip(0.1, 15),
        _rng.normal(1.5, 2.0, n_per_class).clip(0.05, 15),
    ])
    X = np.vstack([oil, lookalike])
    y = np.array([1] * n_per_class + [0] * n_per_class)  # 1 = oil-like, 0 = look-alike
    return X, y


_X_train, _y_train = _synthetic_training_set()
_clf = RandomForestClassifier(n_estimators=150, max_depth=6, random_state=42)
_clf.fit(_X_train, _y_train)


def classify_candidate(features: dict):
    """features: dict with keys in FEATURE_NAMES. Returns (label, confidence, reason)."""
    x = np.array([[features.get(f, 0.0) for f in FEATURE_NAMES]])
    proba = _clf.predict_proba(x)[0]  # [P(look-alike), P(oil-like)]
    oil_conf = float(proba[1])

    if oil_conf >= 0.65:
        label = "candidate_oil"
        reason = ""
    elif oil_conf >= 0.40:
        label = "candidate_uncertain"
        reason = "Mixed shape/texture evidence"
    else:
        label = "look_alike"
        # pick the dominant reason from the weakest features
        if features.get("wind_speed_ctx", 5) < 2:
            reason = "Low-wind dark-region pattern"
        elif features.get("proximity_to_shipping", 0) < 1.5 and features.get("shape_elongation", 5) < 3:
            reason = "Vessel-wake-like geometry"
        elif features.get("texture_variance", 0) > 0.4:
            reason = "High internal texture noise (natural surface feature)"
        else:
            reason = "Low contrast / weak SAR signature"
    return label, round(oil_conf * 100, 1), reason