"""
Multi-sensor evidence fusion: combines SAR confidence, EO validation,
shape/texture evidence, environmental context and temporal consistency
into a single, EXPLAINABLE final confidence score + classification.

The weighting scheme below is a transparent, hand-set demonstration
scheme (documented in the README) — it is not derived from a validated
statistical model.
"""

WEIGHTS = {
    "sar": 0.40,
    "eo": 0.25,
    "shape_texture": 0.15,
    "environment": 0.10,
    "temporal": 0.10,
}


def fuse_evidence(sar_confidence, eo_validation, eo_confidence, shape_texture_score,
                   environment_score, temporal_score):
    """All inputs are 0-100 scores except eo_validation which is a label."""
    eo_component = eo_confidence
    if eo_validation == "Conflicting":
        eo_component = 100 - eo_confidence  # conflicting evidence works against classification
    elif eo_validation == "Unavailable":
        eo_component = 50  # neutral when EO not available

    contributions = {
        "SAR evidence": round(WEIGHTS["sar"] * sar_confidence, 1),
        "EO evidence": round(WEIGHTS["eo"] * eo_component, 1),
        "Shape/texture": round(WEIGHTS["shape_texture"] * shape_texture_score, 1),
        "Environment": round(WEIGHTS["environment"] * environment_score, 1),
        "Temporal evidence": round(WEIGHTS["temporal"] * temporal_score, 1),
    }
    final_confidence = round(sum(contributions.values()), 1)

    if eo_validation == "Conflicting":
        # Conflicting secondary evidence caps how confident the system is allowed
        # to be, even when the SAR signature alone looks strong.
        final_confidence = min(final_confidence, 60.0)

    if final_confidence >= 65:
        classification = "Likely Oil"
    elif final_confidence >= 40:
        classification = "Uncertain"
    else:
        classification = "Likely Look-alike"

    return {
        "final_confidence": final_confidence,
        "classification": classification,
        "breakdown": contributions,
        "weights_used": WEIGHTS,
    }