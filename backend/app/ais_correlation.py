"""
AIS correlation: rank candidate vessels against a slick's reconstructed
origin (location + time window) using explainable sub-scores.

Output scores are INVESTIGATIVE RANKINGS ONLY and do not constitute proof
of responsibility (see README / dashboard disclaimer).
"""
import datetime
from .geo_utils import haversine_km, bearing_between


def _closest_track_point(track, origin_time: datetime.datetime):
    """Find the AIS track point closest in time to the origin window."""
    best = None
    best_dt = None
    for pt in track:
        t = datetime.datetime.fromisoformat(pt["timestamp"])
        dt = abs((t - origin_time).total_seconds())
        if best_dt is None or dt < best_dt:
            best_dt = dt
            best = pt
    return best, best_dt / 60.0 if best_dt is not None else None  # minutes


def score_vessel(track, vessel_type, mmsi, origin_lat, origin_lon, origin_time: datetime.datetime,
                  drift_direction_deg, ais_gap=False, behaviour_anomaly="None"):
    point, time_diff_min = _closest_track_point(track, origin_time)
    distance_km = haversine_km(origin_lat, origin_lon, point["latitude"], point["longitude"])

    spatial_match = distance_km <= 25
    temporal_match = time_diff_min is not None and time_diff_min <= 180

    vessel_course = point.get("course", 0)
    course_diff = min(abs(vessel_course - drift_direction_deg), 360 - abs(vessel_course - drift_direction_deg))
    if course_diff <= 30:
        trajectory_match = "Consistent"
    elif course_diff <= 70:
        trajectory_match = "Partial"
    else:
        trajectory_match = "Inconsistent"

    # explainable weighted scoring (0-100)
    spatial_score = max(0, 100 - distance_km * 3)
    temporal_score = max(0, 100 - (time_diff_min or 999) * 0.4)
    traj_score = {"Consistent": 100, "Partial": 55, "Inconsistent": 15}[trajectory_match]
    behaviour_score = 80 if behaviour_anomaly != "None" else 40
    gap_penalty = -15 if ais_gap else 0

    score = (0.35 * spatial_score + 0.30 * temporal_score + 0.25 * traj_score
             + 0.10 * behaviour_score) + gap_penalty
    score = max(0, min(100, score))

    return {
        "mmsi": mmsi,
        "vessel_type": vessel_type,
        "distance_km": round(distance_km, 1),
        "time_difference_min": round(time_diff_min, 1) if time_diff_min is not None else None,
        "spatial_match": spatial_match,
        "temporal_match": temporal_match,
        "trajectory_consistency": trajectory_match,
        "behaviour_anomaly": behaviour_anomaly,
        "ais_gap": ais_gap,
        "candidate_score": round(score, 1),
        "nearest_position": {"latitude": point["latitude"], "longitude": point["longitude"],
                              "timestamp": point["timestamp"]},
    }


def rank_candidates(vessels, origin_lat, origin_lon, origin_time_iso, drift_direction_deg):
    origin_time = datetime.datetime.fromisoformat(origin_time_iso)
    scored = []
    for v in vessels:
        if v.get("is_dark_vessel"):
            continue  # dark vessels are handled separately (no AIS to score)
        result = score_vessel(
            v["track"], v["vessel_type"], v["mmsi"], origin_lat, origin_lon,
            origin_time, drift_direction_deg,
            ais_gap=v.get("ais_gap", False),
            behaviour_anomaly=v.get("behaviour_anomaly", "None"),
        )
        result["vessel_name"] = v["vessel_name"]
        scored.append(result)

    scored.sort(key=lambda r: r["candidate_score"], reverse=True)
    for i, r in enumerate(scored, start=1):
        r["candidate_rank"] = i
    return scored