"""
Synthetic advection model for oil slick trajectories.

This is NOT a validated oceanographic model. It is a simplified,
transparent, wind+current driven drift model intended to demonstrate the
prototype's workflow (forward prediction, backward reconstruction,
environmental-change recalculation and observation-based correction).

Drift velocity = current_vector + WIND_DRIFT_FACTOR * wind_vector
(the standard simplification used in many introductory oil-spill drift
demonstrations: oil is pushed by ~3% of wind speed in addition to the
surface current). Direction fields (wind_direction / current_direction)
are given in the meteorological/oceanographic "FROM" convention
(e.g. wind_direction=240 means wind blowing FROM the SW), so the drift
contribution points at (direction + 180) mod 360.
"""
import math
import random
from .geo_utils import destination_point, bearing_between, haversine_km

WIND_DRIFT_FACTOR = 0.03  # oil moves at ~3% of wind speed (classic rule of thumb)


def _vector_from_speed_dir(speed, from_direction_deg):
    """Convert a meteorological 'from' direction + speed into a (dx, dy) unit-ish vector
    pointing in the direction the water/air is actually moving TOWARD."""
    to_dir = (from_direction_deg + 180) % 360
    rad = math.radians(to_dir)
    dx = speed * math.sin(rad)  # east component
    dy = speed * math.cos(rad)  # north component
    return dx, dy


def combined_drift_vector(wind_speed, wind_direction, current_speed, current_direction):
    wx, wy = _vector_from_speed_dir(wind_speed, wind_direction)
    cx, cy = _vector_from_speed_dir(current_speed, current_direction)
    dx = cx + WIND_DRIFT_FACTOR * wx
    dy = cy + WIND_DRIFT_FACTOR * wy
    speed_kmh = math.hypot(dx, dy) * 3.6  # m/s -> km/h
    direction_to = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    return speed_kmh, direction_to


def uncertainty_km(hour):
    """Model uncertainty that grows roughly with sqrt(time), a common property of
    dispersion-driven forecast error. Not a real validated error budget."""
    return round(0.9 * math.sqrt(hour) + 0.15 * hour, 2)


def forward_trajectory(start_lat, start_lon, wind_speed, wind_direction,
                        current_speed, current_direction, hours=10, jitter_seed=None):
    """Return an hour-by-hour list of predicted positions (deterministic core +
    a small stochastic jitter to emulate a lightweight particle/Monte-Carlo feel)."""
    rng = random.Random(jitter_seed)
    speed_kmh, direction_to = combined_drift_vector(
        wind_speed, wind_direction, current_speed, current_direction
    )

    points = []
    lat, lon = start_lat, start_lon
    cum_distance = 0.0
    points.append({
        "hour": 0, "latitude": round(lat, 4), "longitude": round(lon, 4),
        "direction_deg": round(direction_to, 1), "distance_km": 0.0,
        "uncertainty_km": 0.0,
    })
    for h in range(1, hours + 1):
        # gentle stochastic wobble so the path is not a perfectly straight line
        wobble = rng.uniform(-4, 4)
        step_dir = (direction_to + wobble) % 360
        step_dist = speed_kmh * 1.0
        lat, lon = destination_point(lat, lon, step_dir, step_dist)
        cum_distance += step_dist
        points.append({
            "hour": h,
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "direction_deg": round(step_dir, 1),
            "distance_km": round(cum_distance, 2),
            "uncertainty_km": uncertainty_km(h),
        })
    return points


def backward_trajectory(detect_lat, detect_lon, wind_speed, wind_direction,
                         current_speed, current_direction, hours_back=6):
    """Reverse the drift vector to reconstruct a probable origin track."""
    speed_kmh, direction_to = combined_drift_vector(
        wind_speed, wind_direction, current_speed, current_direction
    )
    reverse_dir = (direction_to + 180) % 360
    lat, lon = detect_lat, detect_lon
    path = [{"hour": 0, "latitude": round(lat, 4), "longitude": round(lon, 4)}]
    for h in range(1, hours_back + 1):
        lat, lon = destination_point(lat, lon, reverse_dir, speed_kmh)
        path.append({"hour": -h, "latitude": round(lat, 4), "longitude": round(lon, 4)})
    return path, path[-1]["latitude"], path[-1]["longitude"]


def apply_correction(trajectory, observed_lat, observed_lon, hour_of_observation):
    """Compare the predicted position at `hour_of_observation` with an observed
    position, compute the error, and produce an updated (bias-corrected)
    trajectory for all hours from that point forward."""
    predicted = next((p for p in trajectory if p["hour"] == hour_of_observation), trajectory[-1])
    error_km = haversine_km(predicted["latitude"], predicted["longitude"], observed_lat, observed_lon)

    # bias = observed - predicted, applied to all future points (simple but transparent correction)
    lat_bias = observed_lat - predicted["latitude"]
    lon_bias = observed_lon - predicted["longitude"]

    corrected = []
    for p in trajectory:
        if p["hour"] < hour_of_observation:
            corrected.append(p)
        else:
            corrected.append({
                **p,
                "latitude": round(p["latitude"] + lat_bias, 4),
                "longitude": round(p["longitude"] + lon_bias, 4),
                "corrected": True,
            })
    return corrected, round(error_km, 2)