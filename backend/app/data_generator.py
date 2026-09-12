"""
Synthetic dataset generator.

Builds 7-8 clearly-synthetic demonstration cases covering every scenario
required by the spec (single slick, multi-slick, wind-change sensitivity,
current-change sensitivity, self-correction, sensitive-zone impact and
AIS anomaly / dark vessel). All numbers are fabricated for demonstration
and are NOT derived from real satellite, environmental or AIS data.
"""
import datetime
import random
from .models import CaseRecord, SlickRecord, AISVesselRecord, SensitiveZoneRecord, get_session
from . import detection, fusion, trajectory as traj_mod, ais_correlation, impact as impact_mod
from .geo_utils import destination_point

random.seed(7)

BASE_DATE = datetime.datetime(2026, 9, 12, 9, 12, 0)


def _iso(dt):
    return dt.isoformat()


def _make_features(oil_like=True, wind_ctx=6.0, proximity=4.0):
    if oil_like:
        return {
            "darkness_contrast": round(random.uniform(0.62, 0.90), 2),
            "edge_sharpness": round(random.uniform(0.55, 0.88), 2),
            "shape_elongation": round(random.uniform(3.5, 10.0), 2),
            "texture_variance": round(random.uniform(0.05, 0.22), 2),
            "area_km2": round(random.uniform(3.0, 30.0), 2),
            "wind_speed_ctx": wind_ctx,
            "proximity_to_shipping": proximity,
        }
    else:
        return {
            "darkness_contrast": round(random.uniform(0.15, 0.45), 2),
            "edge_sharpness": round(random.uniform(0.10, 0.40), 2),
            "shape_elongation": round(random.uniform(1.0, 2.8), 2),
            "texture_variance": round(random.uniform(0.35, 0.70), 2),
            "area_km2": round(random.uniform(0.2, 4.0), 2),
            "wind_speed_ctx": wind_ctx,
            "proximity_to_shipping": proximity,
        }


def _build_slick(case: CaseRecord, slick_idx, lat, lon, length, width, orientation,
                  oil_like, eo_validation, eo_confidence_base, acq_time, reason_hint=None,
                  detection_delay=None, sar_conf_override=None):
    slick_id = f"{case.case_id}_S{slick_idx}"
    features = _make_features(oil_like=oil_like,
                               wind_ctx=case.wind_speed,
                               proximity=round(random.uniform(0.5, 12.0), 1))
    label, sar_conf, reason = detection.classify_candidate(features)
    if sar_conf_override is not None:
        sar_conf = sar_conf_override

    shape_texture_score = min(100, features["darkness_contrast"] * 60 + features["edge_sharpness"] * 40)
    environment_score = 80 if case.wind_speed < 12 else 55  # very high wind reduces confidence
    temporal_score = 85 if oil_like else 50

    fused = fusion.fuse_evidence(
        sar_confidence=sar_conf,
        eo_validation=eo_validation,
        eo_confidence=eo_confidence_base,
        shape_texture_score=shape_texture_score,
        environment_score=environment_score,
        temporal_score=temporal_score,
    )

    is_look_alike = fused["classification"] == "Likely Look-alike"

    # ---- spill time estimation ----
    delay = detection_delay if detection_delay is not None else random.randint(7, 52)
    first_suspicious = acq_time - datetime.timedelta(minutes=delay + random.randint(10, 30))
    last_clean = first_suspicious - datetime.timedelta(minutes=random.randint(20, 60))

    # ---- backward trajectory / origin ----
    backward_path, origin_lat, origin_lon = traj_mod.backward_trajectory(
        lat, lon, case.wind_speed, case.wind_direction, case.current_speed, case.current_direction,
        hours_back=6,
    )
    origin_time = last_clean - datetime.timedelta(hours=1)

    # ---- forward trajectory ----
    forward = traj_mod.forward_trajectory(
        lat, lon, case.wind_speed, case.wind_direction, case.current_speed, case.current_direction,
        hours=10, jitter_seed=hash(slick_id) % 10000,
    )
    drift_speed, drift_dir = traj_mod.combined_drift_vector(
        case.wind_speed, case.wind_direction, case.current_speed, case.current_direction
    )

    record = SlickRecord(
        slick_id=slick_id,
        case_id=case.case_id,
        event_id=f"{case.case_id}_EVT{slick_idx}",
        center_latitude=lat,
        center_longitude=lon,
        length_km=length,
        width_km=width,
        area_km2=round(length * width * 0.7, 2),
        orientation_deg=orientation,
        shape="Elongated" if length / width > 3 else "Irregular",
        satellite="Sentinel-1 (synthetic)",
        sensor="SAR-C",
        sensor_mode="IW",
        acquisition_date=acq_time.date().isoformat(),
        acquisition_time=acq_time.time().isoformat(timespec="minutes"),
        features=features,
        sar_classification="Rejected (look-alike)" if label == "look_alike" else "Candidate",
        sar_confidence=sar_conf,
        eo_validation=eo_validation,
        eo_confidence=eo_confidence_base,
        final_classification=fused["classification"],
        look_alike_status=is_look_alike,
        look_alike_reason=(reason_hint or reason) if is_look_alike else "",
        fusion_breakdown=fused["breakdown"],
        last_clean_observation=last_clean.isoformat(timespec="minutes"),
        first_suspicious_observation=first_suspicious.isoformat(timespec="minutes"),
        estimated_spill_start=last_clean.isoformat(timespec="minutes"),
        estimated_spill_end=first_suspicious.isoformat(timespec="minutes"),
        first_detection_time=acq_time.isoformat(timespec="minutes"),
        detection_delay_minutes=delay,
        origin_latitude=origin_lat,
        origin_longitude=origin_lon,
        origin_time_window=origin_time.isoformat(timespec="minutes"),
        backward_path=backward_path,
        trajectory=forward,
        original_trajectory=forward,
        predicted_latitude=forward[-1]["latitude"],
        predicted_longitude=forward[-1]["longitude"],
        correction_status="Not yet observed",
        correction_history=[],
        impact=None,
        ais_candidates=[],
    )
    record._origin_time_dt = origin_time
    record._drift_dir = drift_dir
    return record


def _make_vessel(case_id, mmsi, name, vtype, start_lat, start_lon, course, speed_knots,
                  start_time, hours=6, ais_gap=False, behaviour_anomaly="None"):
    track = []
    lat, lon = start_lat, start_lon
    speed_kmh = speed_knots * 1.852
    for h in range(hours):
        t = start_time + datetime.timedelta(hours=h)
        track.append({
            "timestamp": t.isoformat(timespec="minutes"),
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "speed": speed_knots,
            "course": course,
        })
        lat, lon = destination_point(lat, lon, course, speed_kmh)
    return AISVesselRecord(
        case_id=case_id, mmsi=mmsi, vessel_name=name, vessel_type=vtype,
        track=track, ais_gap=ais_gap, behaviour_anomaly=behaviour_anomaly, is_dark_vessel=False,
    )


def _finalize_case(session, case, slicks, vessels, zones):
    session.add(case)
    for z in zones:
        session.add(SensitiveZoneRecord(case_id=case.case_id, **z))
    session.add_all(vessels)
    session.flush()

    vessel_dicts = [{
        "mmsi": v.mmsi, "vessel_name": v.vessel_name, "vessel_type": v.vessel_type,
        "track": v.track, "ais_gap": v.ais_gap, "behaviour_anomaly": v.behaviour_anomaly,
        "is_dark_vessel": v.is_dark_vessel,
    } for v in vessels]

    for s in slicks:
        if not s.look_alike_status:
            ranked = ais_correlation.rank_candidates(
                vessel_dicts, s.origin_latitude, s.origin_longitude,
                _iso(s._origin_time_dt), s._drift_dir,
            )
            s.ais_candidates = ranked[:5]

            zone_dicts = [{"name": z["name"], "zone_type": z["zone_type"],
                            "center_lat": z["center_lat"], "center_lon": z["center_lon"],
                            "radius_km": z["radius_km"]} for z in zones]
            top, all_zones = impact_mod.assess_impact(s.trajectory, zone_dicts)
            s.impact = {"top": top, "all_zones": all_zones}
        else:
            s.ais_candidates = []
            s.impact = {"top": None, "all_zones": []}
        session.add(s)


def generate_all_cases():
    session = get_session()
    # wipe existing data for idempotent regeneration
    session.query(SlickRecord).delete()
    session.query(AISVesselRecord).delete()
    session.query(SensitiveZoneRecord).delete()
    session.query(CaseRecord).delete()
    session.commit()

    cases_meta = []

    # ---------------- CASE 01: single slick, normal conditions ----------------
    c1 = CaseRecord(case_id="CASE_01", title="Single Slick — Normal Conditions",
                     description="One clear oil slick detected under calm, typical environmental conditions.",
                     scenario_tag="Single slick (normal)", location_name="Arabian Sea, off Goa coast",
                     center_lat=15.30, center_lon=72.60, acquisition_date="2026-09-12",
                     wind_speed=8.0, wind_direction=240, current_speed=0.6, current_direction=260,
                     wave_height=1.2, sea_surface_temp=28.4, environmental_timestamp=_iso(BASE_DATE))
    acq = BASE_DATE
    s1 = _build_slick(c1, 1, 15.30, 72.60, 12.4, 3.1, 42, True, "Supporting", 82, acq)
    zones1 = [dict(name="Malvan Marine Sanctuary", zone_type="Protected marine area",
                    center_lat=15.9, center_lon=73.45, radius_km=15)]
    vessels1 = [
        _make_vessel("CASE_01", "419123456", "Ocean Star", "Tanker", 15.05, 72.55, 32, 11, acq - datetime.timedelta(hours=5)),
        _make_vessel("CASE_01", "419223456", "Blue Wave", "Cargo", 14.95, 72.65, 40, 9, acq - datetime.timedelta(hours=5)),
        _make_vessel("CASE_01", "419323456", "Sea Pride", "Tanker", 15.10, 72.40, 55, 13, acq - datetime.timedelta(hours=5)),
    ]
    _finalize_case(session, c1, [s1], vessels1, zones1)
    cases_meta.append(c1)

    # ---------------- CASE 02: two simultaneous slicks ----------------
    c2 = CaseRecord(case_id="CASE_02", title="Two Simultaneous Slicks",
                     description="Two independent slicks detected in the same SAR scene, each tracked separately.",
                     scenario_tag="Two slicks", location_name="Arabian Sea, Konkan coast",
                     center_lat=16.10, center_lon=72.90, acquisition_date="2026-09-12",
                     wind_speed=10.0, wind_direction=250, current_speed=0.7, current_direction=255,
                     wave_height=1.4, sea_surface_temp=28.0, environmental_timestamp=_iso(BASE_DATE))
    s2a = _build_slick(c2, 1, 16.10, 72.90, 9.8, 2.4, 30, True, "Supporting", 78, acq)
    s2b = _build_slick(c2, 2, 16.30, 73.10, 6.5, 1.8, 100, True, "Supporting", 70, acq)
    zones2 = [dict(name="Konkan Coral Patch", zone_type="Coral reef",
                    center_lat=16.6, center_lon=73.5, radius_km=10)]
    vessels2 = [
        _make_vessel("CASE_02", "419423456", "Horizon Trader", "Bulk Carrier", 15.9, 72.8, 45, 12, acq - datetime.timedelta(hours=4)),
        _make_vessel("CASE_02", "419523456", "MV Explorer", "Cargo", 16.4, 73.2, 210, 10, acq - datetime.timedelta(hours=4)),
    ]
    _finalize_case(session, c2, [s2a, s2b], vessels2, zones2)
    cases_meta.append(c2)

    # ---------------- CASE 03: three slicks + multiple look-alikes ----------------
    c3 = CaseRecord(case_id="CASE_03", title="Three Slicks + Multiple Look-alikes",
                     description="Three oil-like slicks plus several look-alike dark regions in the same scene.",
                     scenario_tag="Three slicks + look-alikes", location_name="Arabian Sea",
                     center_lat=15.20, center_lon=72.80, acquisition_date="2026-09-12",
                     wind_speed=8.0, wind_direction=240, current_speed=0.6, current_direction=260,
                     wave_height=1.2, sea_surface_temp=28.4, environmental_timestamp=_iso(BASE_DATE))
    s3a = _build_slick(c3, 1, 15.20, 72.80, 12.4, 3.1, 42, True, "Supporting", 88, acq)
    s3b = _build_slick(c3, 2, 15.05, 72.55, 5.2, 2.6, 15, True, "Conflicting", 55, acq)  # -> Uncertain
    s3c = _build_slick(c3, 3, 14.90, 72.95, 8.9, 2.1, 70, True, "Supporting", 75, acq)
    lookalike1 = _build_slick(c3, 4, 15.35, 72.65, 2.0, 1.6, 5, False, "Unavailable", 50, acq,
                               reason_hint="Vessel-wake-like geometry")
    zones3 = [dict(name="Malvan Marine Sanctuary", zone_type="Protected marine area",
                    center_lat=15.9, center_lon=73.45, radius_km=15),
              dict(name="Vengurla Fishing Grounds", zone_type="Fishing zone",
                    center_lat=14.6, center_lon=73.2, radius_km=12)]
    vessels3 = [
        _make_vessel("CASE_03", "419123456", "Ocean Star", "Tanker", 15.05, 72.75, 30, 11, acq - datetime.timedelta(hours=5)),
        _make_vessel("CASE_03", "419223456", "Blue Wave", "Cargo", 14.95, 72.85, 42, 9, acq - datetime.timedelta(hours=5)),
        _make_vessel("CASE_03", "419323456", "Sea Pride", "Tanker", 15.15, 72.60, 50, 13, acq - datetime.timedelta(hours=5)),
        _make_vessel("CASE_03", "419923456", "Horizon", "Bulk Carrier", 14.85, 73.05, 300, 10, acq - datetime.timedelta(hours=5)),
        _make_vessel("CASE_03", "420023456", "MV Explorer", "Cargo", 15.40, 72.50, 210, 8, acq - datetime.timedelta(hours=5)),
    ]
    _finalize_case(session, c3, [s3a, s3b, s3c, lookalike1], vessels3, zones3)
    cases_meta.append(c3)

    # ---------------- CASE 04: strong wind-direction change ----------------
    c4 = CaseRecord(case_id="CASE_04", title="Strong Wind-Direction Change",
                     description="A slick whose forecast trajectory is highly sensitive to wind-direction shifts — "
                                  "use the Environment Simulator to rotate the wind and watch the path deviate.",
                     scenario_tag="Wind change scenario", location_name="Arabian Sea",
                     center_lat=17.00, center_lon=71.80, acquisition_date="2026-09-12",
                     wind_speed=14.0, wind_direction=200, current_speed=0.4, current_direction=250,
                     wave_height=1.6, sea_surface_temp=27.6, environmental_timestamp=_iso(BASE_DATE))
    s4 = _build_slick(c4, 1, 17.00, 71.80, 10.2, 2.8, 55, True, "Supporting", 80, acq)
    zones4 = [dict(name="Ratnagiri Coastal Zone", zone_type="Sensitive coastal zone",
                    center_lat=17.5, center_lon=72.6, radius_km=14)]
    vessels4 = [
        _make_vessel("CASE_04", "421123456", "Coastal Runner", "Tanker", 16.8, 71.7, 25, 12, acq - datetime.timedelta(hours=5)),
    ]
    _finalize_case(session, c4, [s4], vessels4, zones4)
    cases_meta.append(c4)

    # ---------------- CASE 05: ocean-current change ----------------
    c5 = CaseRecord(case_id="CASE_05", title="Ocean-Current Change",
                     description="A slick dominated by ocean-current forcing — adjust the current speed/direction "
                                  "in the Environment Simulator to see the recalculated path.",
                     scenario_tag="Current change scenario", location_name="Arabian Sea",
                     center_lat=14.40, center_lon=73.30, acquisition_date="2026-09-12",
                     wind_speed=5.0, wind_direction=210, current_speed=1.3, current_direction=280,
                     wave_height=1.0, sea_surface_temp=28.8, environmental_timestamp=_iso(BASE_DATE))
    s5 = _build_slick(c5, 1, 14.40, 73.30, 8.6, 2.2, 20, True, "Supporting", 76, acq)
    zones5 = [dict(name="Malvan Marine Sanctuary", zone_type="Protected marine area",
                    center_lat=15.9, center_lon=73.45, radius_km=15)]
    vessels5 = [
        _make_vessel("CASE_05", "422123456", "Arabian Pearl", "Tanker", 14.2, 73.2, 15, 10, acq - datetime.timedelta(hours=5)),
    ]
    _finalize_case(session, c5, [s5], vessels5, zones5)
    cases_meta.append(c5)

    # ---------------- CASE 06: self-correction scenario ----------------
    c6 = CaseRecord(case_id="CASE_06", title="Self-Correcting Trajectory",
                     description="A new simulated satellite pass disagrees with the original forecast, "
                                  "triggering the closed-loop correction workflow.",
                     scenario_tag="Self-correction scenario", location_name="Arabian Sea",
                     center_lat=15.30, center_lon=72.60, acquisition_date="2026-09-12",
                     wind_speed=9.0, wind_direction=235, current_speed=0.65, current_direction=245,
                     wave_height=1.3, sea_surface_temp=28.2, environmental_timestamp=_iso(BASE_DATE))
    s6 = _build_slick(c6, 1, 15.30, 72.60, 11.0, 2.9, 38, True, "Supporting", 84, acq)
    zones6 = [dict(name="Malvan Marine Sanctuary", zone_type="Protected marine area",
                    center_lat=15.9, center_lon=73.45, radius_km=15)]
    vessels6 = [
        _make_vessel("CASE_06", "423123456", "Deccan Voyager", "Tanker", 15.1, 72.5, 35, 11, acq - datetime.timedelta(hours=5)),
    ]
    _finalize_case(session, c6, [s6], vessels6, zones6)
    cases_meta.append(c6)

    # ---------------- CASE 07: sensitive-zone intersection ----------------
    c7 = CaseRecord(case_id="CASE_07", title="Sensitive-Zone Impact",
                     description="Forecast trajectory intersects a protected marine zone within the 10-hour window.",
                     scenario_tag="Sensitive zone impact", location_name="Arabian Sea, near Malvan",
                     center_lat=15.55, center_lon=73.05, acquisition_date="2026-09-12",
                     wind_speed=11.0, wind_direction=225, current_speed=0.8, current_direction=230,
                     wave_height=1.5, sea_surface_temp=28.1, environmental_timestamp=_iso(BASE_DATE))
    s7 = _build_slick(c7, 1, 15.55, 73.05, 9.4, 2.5, 48, True, "Supporting", 81, acq)
    # place the zone directly on the forward drift path (~hour 7) so it clearly intersects
    zones7 = [dict(name="Malvan Marine Sanctuary", zone_type="Protected marine area",
                    center_lat=15.724, center_lon=73.245, radius_km=10),
              dict(name="Devgad Water-Intake Station", zone_type="Water-intake area",
                    center_lat=16.05, center_lon=73.55, radius_km=6)]
    vessels7 = [
        _make_vessel("CASE_07", "424123456", "Konkan Star", "Tanker", 15.4, 72.95, 40, 12, acq - datetime.timedelta(hours=5)),
    ]
    _finalize_case(session, c7, [s7], vessels7, zones7)
    cases_meta.append(c7)

    # ---------------- CASE 08: AIS anomaly + dark vessel ----------------
    c8 = CaseRecord(case_id="CASE_08", title="AIS Anomaly / Dark-Vessel Scenario",
                     description="A SAR-detected vessel-like object near the origin has no matching AIS transmission, "
                                  "and a nearby vessel shows an AIS transmission gap.",
                     scenario_tag="AIS anomaly / dark vessel", location_name="Arabian Sea",
                     center_lat=15.75, center_lon=72.30, acquisition_date="2026-09-12",
                     wind_speed=7.0, wind_direction=255, current_speed=0.5, current_direction=260,
                     wave_height=1.1, sea_surface_temp=28.5, environmental_timestamp=_iso(BASE_DATE))
    s8 = _build_slick(c8, 1, 15.75, 72.30, 10.8, 2.7, 60, True, "Supporting", 79, acq)
    zones8 = [dict(name="Vengurla Fishing Grounds", zone_type="Fishing zone",
                    center_lat=14.6, center_lon=73.2, radius_km=12)]
    vessels8 = [
        _make_vessel("CASE_08", "425123456", "Northern Cargo", "Cargo", 15.6, 72.2, 30, 10,
                      acq - datetime.timedelta(hours=5), ais_gap=True, behaviour_anomaly="AIS gap of 95 minutes near origin"),
        _make_vessel("CASE_08", "425223456", "Lakshadweep Trader", "Tanker", 15.9, 72.1, 200, 9,
                      acq - datetime.timedelta(hours=5)),
    ]
    _finalize_case(session, c8, [s8], vessels8, zones8)

    # dark vessel: SAR-like detection with NO AIS record at all
    dark_vessel = AISVesselRecord(
        case_id="CASE_08", mmsi="UNMATCHED", vessel_name="Unidentified (SAR only)",
        vessel_type="Unknown", track=[{
            "timestamp": _iso(acq - datetime.timedelta(hours=1)),
            "latitude": s8.origin_latitude + 0.03, "longitude": s8.origin_longitude - 0.02,
            "speed": 0, "course": 0,
        }],
        ais_gap=False, behaviour_anomaly="No AIS transmission detected", is_dark_vessel=True,
    )
    session.add(dark_vessel)
    cases_meta.append(c8)

    session.commit()
    session.close()
    return [c.case_id for c in cases_meta]