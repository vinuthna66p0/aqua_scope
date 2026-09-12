"""
SQLAlchemy models for the Oil Spill Intelligence & Decision Support System.

NOTE ON DESIGN: Several nested/repeating structures (trajectory point arrays,
AIS candidate lists, hourly uncertainty, correction history) are stored as
JSON columns rather than fully normalized child tables. This keeps the schema
readable for a hackathon prototype while still being backed by a real
SQLite database via SQLAlchemy, and can be normalized further if the project
grows. Everything else (cases, slicks, vessels, sensitive zones) is modeled
as proper relational tables.
"""
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean, ForeignKey, JSON, DateTime
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import datetime

DATABASE_URL = "sqlite:///./oilspill.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
Base = declarative_base()


class CaseRecord(Base):
    __tablename__ = "cases"

    case_id = Column(String, primary_key=True)          # e.g. "CASE_01"
    title = Column(String)
    description = Column(String)
    scenario_tag = Column(String)                        # short label for dashboard
    location_name = Column(String)
    center_lat = Column(Float)
    center_lon = Column(Float)
    acquisition_date = Column(String)
    ais_window_hours = Column(Integer, default=24)

    wind_speed = Column(Float)
    wind_direction = Column(Float)
    current_speed = Column(Float)
    current_direction = Column(Float)
    wave_height = Column(Float)
    sea_surface_temp = Column(Float)
    environmental_timestamp = Column(String)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    slicks = relationship("SlickRecord", back_populates="case", cascade="all, delete-orphan")
    vessels = relationship("AISVesselRecord", back_populates="case", cascade="all, delete-orphan")
    zones = relationship("SensitiveZoneRecord", back_populates="case", cascade="all, delete-orphan")


class SlickRecord(Base):
    __tablename__ = "slicks"

    slick_id = Column(String, primary_key=True)           # e.g. "CASE_03_S1"
    case_id = Column(String, ForeignKey("cases.case_id"))
    event_id = Column(String)

    # LOCATION
    center_latitude = Column(Float)
    center_longitude = Column(Float)

    # GEOMETRY
    length_km = Column(Float)
    width_km = Column(Float)
    area_km2 = Column(Float)
    orientation_deg = Column(Float)
    shape = Column(String)

    # SATELLITE
    satellite = Column(String)
    sensor = Column(String)
    sensor_mode = Column(String)
    acquisition_date = Column(String)
    acquisition_time = Column(String)

    # raw synthetic image features (used by the classifier)
    features = Column(JSON)

    # CLASSIFICATION
    sar_classification = Column(String)      # candidate / rejected
    sar_confidence = Column(Float)
    eo_validation = Column(String)           # Supporting / Conflicting / Unavailable
    eo_confidence = Column(Float)
    final_classification = Column(String)    # Likely Oil / Uncertain / Likely Look-alike
    look_alike_status = Column(Boolean, default=False)
    look_alike_reason = Column(String, default="")
    fusion_breakdown = Column(JSON)          # explainable scoring components

    # VALIDATION (operational-style metadata)
    on_site_verification = Column(String, default="Not Verified")
    report_type = Column(String, default="Satellite Detection")
    report_subtype = Column(String, default="Automatic")
    observation_method = Column(String, default="SAR + EO")

    # TIME
    last_clean_observation = Column(String)
    first_suspicious_observation = Column(String)
    estimated_spill_start = Column(String)
    estimated_spill_end = Column(String)
    first_detection_time = Column(String)
    detection_delay_minutes = Column(Float)

    # ORIGIN (backward trajectory result)
    origin_latitude = Column(Float)
    origin_longitude = Column(Float)
    origin_time_window = Column(String)
    backward_path = Column(JSON)

    # TRAJECTORY (forward, current state)
    trajectory = Column(JSON)                # list of {hour,lat,lon,direction,distance_km,uncertainty_km}
    original_trajectory = Column(JSON)       # snapshot of the very first computed trajectory

    # SELF-CORRECTION (latest state)
    predicted_latitude = Column(Float)
    predicted_longitude = Column(Float)
    observed_latitude = Column(Float)
    observed_longitude = Column(Float)
    prediction_error_km = Column(Float)
    correction_applied = Column(Boolean, default=False)
    corrected_latitude = Column(Float)
    corrected_longitude = Column(Float)
    correction_status = Column(String, default="Not yet observed")
    correction_history = Column(JSON, default=list)

    # IMPACT
    impact = Column(JSON)   # {zone, zone_type, distance_km, eta_hours, intersects, priority}

    ais_candidates = Column(JSON)  # ranked list, denormalized snapshot for fast reads

    case = relationship("CaseRecord", back_populates="slicks")


class AISVesselRecord(Base):
    __tablename__ = "ais_vessels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String, ForeignKey("cases.case_id"))
    mmsi = Column(String)
    vessel_name = Column(String)
    vessel_type = Column(String)
    track = Column(JSON)     # list of {timestamp, lat, lon, speed, course}
    ais_gap = Column(Boolean, default=False)
    behaviour_anomaly = Column(String, default="None")
    is_dark_vessel = Column(Boolean, default=False)  # no AIS at all (used for unmatched scenario)

    case = relationship("CaseRecord", back_populates="vessels")


class SensitiveZoneRecord(Base):
    __tablename__ = "sensitive_zones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String, ForeignKey("cases.case_id"))
    name = Column(String)
    zone_type = Column(String)   # mangrove / coral reef / fishing zone / protected marine area / water intake
    center_lat = Column(Float)
    center_lon = Column(Float)
    radius_km = Column(Float)

    case = relationship("CaseRecord", back_populates="zones")


def init_db():
    Base.metadata.create_all(bind=engine)


def get_session():
    return SessionLocal()