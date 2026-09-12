import datetime
import random
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

from .models import init_db, get_session, CaseRecord, SlickRecord, AISVesselRecord, SensitiveZoneRecord
from . import trajectory as traj_mod, impact as impact_mod, ais_correlation, data_generator
from .geo_utils import haversine_km

app = FastAPI(title="Oil Spill Intelligence & Decision Support System (SIH26143)",
              description="Prototype API. Uses SYNTHETIC data only — not connected to live satellites.")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

init_db()

# seed the database with synthetic cases on startup if empty
_session = get_session()
if _session.query(CaseRecord).count() == 0:
    data_generator.generate_all_cases()
_session.close()


# ----------------------------- serialization -----------------------------

def slick_to_dict(s: SlickRecord):
    return {
        "slick_id": s.slick_id, "case_id": s.case_id, "event_id": s.event_id,
        "center_latitude": s.center_latitude, "center_longitude": s.center_longitude,
        "length_km": s.length_km, "width_km": s.width_km, "area_km2": s.area_km2,
        "orientation_deg": s.orientation_deg, "shape": s.shape,
        "satellite": s.satellite, "sensor": s.sensor, "sensor_mode": s.sensor_mode,
        "acquisition_date": s.acquisition_date, "acquisition_time": s.acquisition_time,
        "features": s.features,
        "sar_classification": s.sar_classification, "sar_confidence": s.sar_confidence,
        "eo_validation": s.eo_validation, "eo_confidence": s.eo_confidence,
        "final_classification": s.final_classification,
        "look_alike_status": s.look_alike_status, "look_alike_reason": s.look_alike_reason,
        "fusion_breakdown": s.fusion_breakdown,
        "on_site_verification": s.on_site_verification, "report_type": s.report_type,
        "report_subtype": s.report_subtype, "observation_method": s.observation_method,
        "last_clean_observation": s.last_clean_observation,
        "first_suspicious_observation": s.first_suspicious_observation,
        "estimated_spill_start": s.estimated_spill_start, "estimated_spill_end": s.estimated_spill_end,
        "first_detection_time": s.first_detection_time, "detection_delay_minutes": s.detection_delay_minutes,
        "origin_latitude": s.origin_latitude, "origin_longitude": s.origin_longitude,
        "origin_time_window": s.origin_time_window, "backward_path": s.backward_path,
        "trajectory": s.trajectory, "original_trajectory": s.original_trajectory,
        "predicted_latitude": s.predicted_latitude, "predicted_longitude": s.predicted_longitude,
        "observed_latitude": s.observed_latitude, "observed_longitude": s.observed_longitude,
        "prediction_error_km": s.prediction_error_km, "correction_applied": s.correction_applied,
        "corrected_latitude": s.corrected_latitude, "corrected_longitude": s.corrected_longitude,
        "correction_status": s.correction_status, "correction_history": s.correction_history or [],
        "impact": s.impact, "ais_candidates": s.ais_candidates or [],
    }


def case_to_dict(c: CaseRecord, include_slicks=True):
    d = {
        "case_id": c.case_id, "title": c.title, "description": c.description,
        "scenario_tag": c.scenario_tag, "location_name": c.location_name,
        "center_lat": c.center_lat, "center_lon": c.center_lon,
        "acquisition_date": c.acquisition_date,
        "environment": {
            "wind_speed": c.wind_speed, "wind_direction": c.wind_direction,
            "current_speed": c.current_speed, "current_direction": c.current_direction,
            "wave_height": c.wave_height, "sea_surface_temp": c.sea_surface_temp,
            "timestamp": c.environmental_timestamp,
        },
        "num_slicks": len(c.slicks),
    }
    if include_slicks:
        d["slicks"] = [slick_to_dict(s) for s in c.slicks]
        d["vessels"] = [{
            "mmsi": v.mmsi, "vessel_name": v.vessel_name, "vessel_type": v.vessel_type,
            "track": v.track, "ais_gap": v.ais_gap, "behaviour_anomaly": v.behaviour_anomaly,
            "is_dark_vessel": v.is_dark_vessel,
        } for v in c.vessels]
        d["sensitive_zones"] = [{
            "name": z.name, "zone_type": z.zone_type, "center_lat": z.center_lat,
            "center_lon": z.center_lon, "radius_km": z.radius_km,
        } for z in c.zones]
    return d


# ----------------------------- request bodies -----------------------------

class RecalculateRequest(BaseModel):
    slick_id: str
    wind_speed: float
    wind_direction: float
    current_speed: float
    current_direction: float


class ObservationRequest(BaseModel):
    slick_id: str
    hour: int
    observed_latitude: Optional[float] = None
    observed_longitude: Optional[float] = None


class CorrectRequest(BaseModel):
    slick_id: str


# ----------------------------- endpoints -----------------------------

@app.get("/api/cases")
def list_cases():
    session = get_session()
    cases = session.query(CaseRecord).order_by(CaseRecord.case_id).all()
    result = [case_to_dict(c, include_slicks=False) for c in cases]
    session.close()
    return result


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    session = get_session()
    c = session.query(CaseRecord).filter(CaseRecord.case_id == case_id).first()
    if not c:
        session.close()
        raise HTTPException(404, "Case not found")
    result = case_to_dict(c, include_slicks=True)
    session.close()
    return result


@app.post("/api/analyze")
def run_full_analysis(payload: dict):
    """Re-runs the full detect->validate->fuse->trajectory->AIS->impact pipeline
    conceptually for a given case (in this prototype the pipeline output is
    precomputed at generation time, so this endpoint simply returns the
    current, up-to-date case state — matching what 'RUN FULL ANALYSIS' shows
    on the dashboard)."""
    case_id = payload.get("case_id")
    return get_case(case_id)


@app.post("/api/cases/{case_id}/reset")
def reset_case(case_id: str):
    session = get_session()
    slicks = session.query(SlickRecord).filter(SlickRecord.case_id == case_id).all()
    if not slicks:
        session.close()
        raise HTTPException(404, "Case not found")
    for s in slicks:
        s.trajectory = s.original_trajectory
        s.predicted_latitude = s.original_trajectory[-1]["latitude"]
        s.predicted_longitude = s.original_trajectory[-1]["longitude"]
        s.observed_latitude = None
        s.observed_longitude = None
        s.prediction_error_km = None
        s.correction_applied = False
        s.corrected_latitude = None
        s.corrected_longitude = None
        s.correction_status = "Not yet observed"
        s.correction_history = []
        session.add(s)
    session.commit()
    result = case_to_dict(session.query(CaseRecord).filter(CaseRecord.case_id == case_id).first())
    session.close()
    return result


@app.get("/api/detection/{slick_id}")
def get_detection(slick_id: str):
    session = get_session()
    s = session.query(SlickRecord).filter(SlickRecord.slick_id == slick_id).first()
    if not s:
        session.close()
        raise HTTPException(404, "Slick not found")
    result = {
        "slick_id": s.slick_id, "sar_classification": s.sar_classification,
        "sar_confidence": s.sar_confidence, "eo_validation": s.eo_validation,
        "eo_confidence": s.eo_confidence, "final_classification": s.final_classification,
        "look_alike_status": s.look_alike_status, "look_alike_reason": s.look_alike_reason,
        "fusion_breakdown": s.fusion_breakdown, "features": s.features,
    }
    session.close()
    return result


@app.get("/api/trajectory/{slick_id}")
def get_trajectory(slick_id: str):
    session = get_session()
    s = session.query(SlickRecord).filter(SlickRecord.slick_id == slick_id).first()
    if not s:
        session.close()
        raise HTTPException(404, "Slick not found")
    result = {
        "slick_id": s.slick_id, "trajectory": s.trajectory,
        "original_trajectory": s.original_trajectory,
        "backward_path": s.backward_path,
        "origin_latitude": s.origin_latitude, "origin_longitude": s.origin_longitude,
        "origin_time_window": s.origin_time_window,
    }
    session.close()
    return result


@app.post("/api/trajectory/recalculate")
def recalculate_trajectory(req: RecalculateRequest):
    session = get_session()
    s = session.query(SlickRecord).filter(SlickRecord.slick_id == req.slick_id).first()
    if not s:
        session.close()
        raise HTTPException(404, "Slick not found")

    new_traj = traj_mod.forward_trajectory(
        s.center_latitude, s.center_longitude,
        req.wind_speed, req.wind_direction, req.current_speed, req.current_direction,
        hours=10, jitter_seed=hash(req.slick_id) % 10000,
    )
    old_final = s.trajectory[-1]
    new_final = new_traj[-1]
    deviation_km = haversine_km(old_final["latitude"], old_final["longitude"],
                                 new_final["latitude"], new_final["longitude"])

    previous_traj = s.trajectory
    s.trajectory = new_traj
    s.predicted_latitude = new_final["latitude"]
    s.predicted_longitude = new_final["longitude"]

    # re-run impact assessment against the new trajectory
    zones = session.query(SensitiveZoneRecord).filter(SensitiveZoneRecord.case_id == s.case_id).all()
    zone_dicts = [{"name": z.name, "zone_type": z.zone_type, "center_lat": z.center_lat,
                    "center_lon": z.center_lon, "radius_km": z.radius_km} for z in zones]
    top, all_zones = impact_mod.assess_impact(new_traj, zone_dicts)
    s.impact = {"top": top, "all_zones": all_zones}

    session.add(s)
    session.commit()

    result = {
        "slick_id": s.slick_id,
        "previous_trajectory": previous_traj,
        "new_trajectory": new_traj,
        "deviation_km": round(deviation_km, 2),
        "impact": s.impact,
    }
    session.close()
    return result


@app.post("/api/observation/update")
def simulate_new_observation(req: ObservationRequest):
    """Simulate receiving a new satellite pass. If observed lat/lon are not
    supplied, a synthetic observed position is generated by perturbing the
    predicted position at the given hour (representative of real-world drift
    model error, not measured from any real satellite)."""
    session = get_session()
    s = session.query(SlickRecord).filter(SlickRecord.slick_id == req.slick_id).first()
    if not s:
        session.close()
        raise HTTPException(404, "Slick not found")

    predicted = next((p for p in s.trajectory if p["hour"] == req.hour), s.trajectory[-1])

    if req.observed_latitude is not None and req.observed_longitude is not None:
        obs_lat, obs_lon = req.observed_latitude, req.observed_longitude
    else:
        rng = random.Random(hash(req.slick_id + str(req.hour)))
        # perturbation grows with hour to mimic accumulating forecast error
        magnitude_km = 3 + req.hour * 0.6
        bearing = rng.uniform(0, 360)
        from .geo_utils import destination_point
        obs_lat, obs_lon = destination_point(predicted["latitude"], predicted["longitude"],
                                              bearing, magnitude_km)
        obs_lat, obs_lon = round(obs_lat, 4), round(obs_lon, 4)

    error_km = haversine_km(predicted["latitude"], predicted["longitude"], obs_lat, obs_lon)

    s.predicted_latitude = predicted["latitude"]
    s.predicted_longitude = predicted["longitude"]
    s.observed_latitude = obs_lat
    s.observed_longitude = obs_lon
    s.prediction_error_km = round(error_km, 2)
    s.correction_applied = False
    s.correction_status = f"New observation received at +{req.hour}h — correction pending"

    session.add(s)
    session.commit()

    result = {
        "slick_id": s.slick_id, "hour": req.hour,
        "predicted": {"latitude": predicted["latitude"], "longitude": predicted["longitude"]},
        "observed": {"latitude": obs_lat, "longitude": obs_lon},
        "prediction_error_km": s.prediction_error_km,
    }
    session.close()
    return result


@app.post("/api/trajectory/correct")
def apply_trajectory_correction(req: CorrectRequest):
    session = get_session()
    s = session.query(SlickRecord).filter(SlickRecord.slick_id == req.slick_id).first()
    if not s:
        session.close()
        raise HTTPException(404, "Slick not found")
    if s.observed_latitude is None:
        session.close()
        raise HTTPException(400, "No new observation available — simulate an observation first.")

    obs_hour = next((p["hour"] for p in s.trajectory
                      if abs(p["latitude"] - s.predicted_latitude) < 1e-6
                      and abs(p["longitude"] - s.predicted_longitude) < 1e-6), None)
    if obs_hour is None:
        obs_hour = s.trajectory[-1]["hour"]

    corrected_traj, error_km = traj_mod.apply_correction(
        s.trajectory, s.observed_latitude, s.observed_longitude, obs_hour
    )

    corrected_final = corrected_traj[-1]
    s.correction_history = (s.correction_history or []) + [{
        "timestamp": datetime.datetime.utcnow().isoformat(timespec="minutes"),
        "predicted": {"latitude": s.predicted_latitude, "longitude": s.predicted_longitude},
        "observed": {"latitude": s.observed_latitude, "longitude": s.observed_longitude},
        "error_km": error_km,
    }]
    s.trajectory = corrected_traj
    s.correction_applied = True
    s.corrected_latitude = corrected_final["latitude"]
    s.corrected_longitude = corrected_final["longitude"]
    s.correction_status = f"Corrected using observation at +{obs_hour}h (error {error_km} km)"

    # re-run impact assessment on corrected trajectory
    zones = session.query(SensitiveZoneRecord).filter(SensitiveZoneRecord.case_id == s.case_id).all()
    zone_dicts = [{"name": z.name, "zone_type": z.zone_type, "center_lat": z.center_lat,
                    "center_lon": z.center_lon, "radius_km": z.radius_km} for z in zones]
    top, all_zones = impact_mod.assess_impact(corrected_traj, zone_dicts)
    s.impact = {"top": top, "all_zones": all_zones}

    session.add(s)
    session.commit()

    result = {
        "slick_id": s.slick_id, "corrected_trajectory": corrected_traj,
        "prediction_error_km": error_km, "correction_status": s.correction_status,
        "impact": s.impact,
    }
    session.close()
    return result


@app.get("/api/ais/{slick_id}")
def get_ais_candidates(slick_id: str):
    session = get_session()
    s = session.query(SlickRecord).filter(SlickRecord.slick_id == slick_id).first()
    if not s:
        session.close()
        raise HTTPException(404, "Slick not found")
    dark_vessels = session.query(AISVesselRecord).filter(
        AISVesselRecord.case_id == s.case_id, AISVesselRecord.is_dark_vessel == True  # noqa: E712
    ).all()
    result = {
        "slick_id": s.slick_id,
        "candidates": s.ais_candidates or [],
        "dark_vessel_flags": [{
            "mmsi": v.mmsi, "vessel_name": v.vessel_name,
            "nearest_position": v.track[0] if v.track else None,
            "behaviour_anomaly": v.behaviour_anomaly,
        } for v in dark_vessels],
        "disclaimer": "Investigative candidates only — not legal proof of responsibility.",
    }
    session.close()
    return result


@app.get("/api/impact/{slick_id}")
def get_impact(slick_id: str):
    session = get_session()
    s = session.query(SlickRecord).filter(SlickRecord.slick_id == slick_id).first()
    if not s:
        session.close()
        raise HTTPException(404, "Slick not found")
    result = s.impact
    session.close()
    return result


@app.get("/api/event/{event_id}")
def get_event(event_id: str):
    session = get_session()
    s = session.query(SlickRecord).filter(SlickRecord.event_id == event_id).first()
    if not s:
        session.close()
        raise HTTPException(404, "Event not found")
    result = slick_to_dict(s)
    session.close()
    return result


@app.get("/api/metadata_table")
def get_metadata_table():
    """Flat, sortable/filterable 'Detection Metadata' table across all cases."""
    session = get_session()
    slicks = session.query(SlickRecord).all()
    cases_by_id = {c.case_id: c for c in session.query(CaseRecord).all()}
    rows = []
    for s in slicks:
        case = cases_by_id.get(s.case_id)
        rows.append({
            "event_id": s.event_id, "case_id": s.case_id, "class": s.final_classification,
            "center_latitude": s.center_latitude, "center_longitude": s.center_longitude,
            "length_km": s.length_km, "area_km2": s.area_km2, "satellite": s.satellite,
            "sensor_mode": s.sensor_mode, "on_site_verification": s.on_site_verification,
            "report_type": s.report_type, "report_sub_type": s.report_subtype,
            "observation_method": s.observation_method, "width_km": s.width_km,
            "orientation_deg": s.orientation_deg, "eo_validation": s.eo_validation,
            "sar_confidence": s.sar_confidence, "eo_confidence": s.eo_confidence,
            "final_classification": s.final_classification, "look_alike_status": s.look_alike_status,
            "spill_time_window": f"{s.estimated_spill_start} - {s.estimated_spill_end}",
            "detection_time": s.first_detection_time,
            "wind_speed": case.wind_speed if case else None,
            "wind_direction": case.wind_direction if case else None,
            "current_speed": case.current_speed if case else None,
            "current_direction": case.current_direction if case else None,
            "origin_latitude": s.origin_latitude, "origin_longitude": s.origin_longitude,
            "origin_time": s.origin_time_window,
            "prediction_error_km": s.prediction_error_km, "correction_status": s.correction_status,
            "ais_top_candidate": (s.ais_candidates[0]["vessel_name"] if s.ais_candidates else None),
            "ais_top_score": (s.ais_candidates[0]["candidate_score"] if s.ais_candidates else None),
            "impact_zone": (s.impact.get("top", {}) or {}).get("zone_name") if s.impact else None,
            "impact_priority": (s.impact.get("top", {}) or {}).get("priority") if s.impact else None,
        })
    session.close()
    return rows


@app.post("/api/regenerate")
def regenerate():
    """Regenerates the entire synthetic dataset from scratch (for demo/reset purposes)."""
    ids = data_generator.generate_all_cases()
    return {"regenerated_cases": ids}


@app.get("/api/health")
def health():
    return {"status": "ok", "note": "Synthetic data prototype — not connected to live satellites."}


# serve the frontend (mounted last so /api/* routes above take priority)
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")