"""Sensitive-zone impact assessment: checks a forward trajectory against
synthetic sensitive zones and estimates arrival time / priority."""
from .geo_utils import haversine_km


def assess_impact(trajectory, zones):
    """Return the single most urgent zone assessment for this trajectory
    (the one with earliest / closest potential intersection), plus the
    full list of all zone distances for transparency."""
    results = []
    for zone in zones:
        best_hour = None
        min_distance = None
        intersects = False
        for point in trajectory:
            d = haversine_km(point["latitude"], point["longitude"], zone["center_lat"], zone["center_lon"])
            if min_distance is None or d < min_distance:
                min_distance = d
                best_hour = point["hour"]
            if d <= zone["radius_km"]:
                intersects = True
                best_hour = point["hour"]
                min_distance = d
                break

        if intersects:
            status = "Intersects"
            priority = "HIGH"
        elif min_distance <= zone["radius_km"] * 2.5:
            status = "Approaches"
            priority = "MEDIUM"
        else:
            status = "Remains away"
            priority = "LOW"

        results.append({
            "zone_name": zone["name"],
            "zone_type": zone["zone_type"],
            "distance_km": round(min_distance, 1),
            "estimated_arrival_hours": best_hour if (intersects or status == "Approaches") else None,
            "status": status,
            "potential_impact": intersects,
            "priority": priority,
        })

    results.sort(key=lambda r: (r["priority"] != "HIGH", r["priority"] != "MEDIUM", r["distance_km"]))
    top = results[0] if results else None
    return top, results