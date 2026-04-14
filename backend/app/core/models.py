from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON, ForeignKey, LargeBinary, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime
from uuid import uuid4

Base = declarative_base()

class Client(Base):
    __tablename__ = "clients"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, nullable=False)
    status = Column(String, default="active")   # "active" | "suspended"
    created_at = Column(DateTime, default=datetime.utcnow)
    # Permissions stored as JSON object
    permissions = Column(JSON, nullable=False, default=dict)
    # Qdrant collection name for this client's face vectors
    qdrant_collection = Column(String, nullable=True)

class User(Base):
    __tablename__ = "users"
    username = Column(String, primary_key=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="client")  # "admin" | "client"
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True)  # null for admin

class WorkerKey(Base):
    __tablename__ = "worker_keys"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    api_key_hash = Column(String, nullable=False)   # bcrypt hash
    label = Column(String, nullable=False)
    last_seen = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Worker(Base):
    __tablename__ = "workers"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    worker_key_id = Column(UUID(as_uuid=True), ForeignKey("worker_keys.id"), nullable=False)
    label = Column(String, nullable=False)
    ip_address = Column(String, nullable=True)
    media_base_url = Column(String, nullable=True)
    last_seen = Column(DateTime, nullable=True)
    status = Column(String, default="offline")
    created_at = Column(DateTime, default=datetime.utcnow)

class Camera(Base):
    __tablename__ = "cameras"
    id = Column(String, primary_key=True)
    camera_id = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    location = Column(String, default='')
    description = Column(String, default='')
    stream_url = Column(String, default='')
    floor_plan_x = Column(Float, default=50.0)
    floor_plan_y = Column(Float, default=50.0)
    roi = Column(Text, nullable=True)
    added_by = Column(String)
    added_at = Column(String)
    status = Column(String, default='active')
    face_enabled = Column(Integer, default=1)
    obj_enabled = Column(Integer, default=1)
    stream_enabled = Column(Integer, default=1)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    worker_id = Column(UUID(as_uuid=True), ForeignKey("workers.id"), nullable=True)

class Sighting(Base):
    __tablename__ = "sightings"
    id = Column(String, primary_key=True)
    camera_id = Column(String)
    location = Column(String)
    timestamp = Column(String)
    uploaded_by = Column(String)
    snapshot_path = Column(String, nullable=True)
    matched = Column(Boolean)
    person_id = Column(String)
    person_name = Column(String)
    confidence = Column(Float)
    embedding = Column(LargeBinary)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    worker_id = Column(UUID(as_uuid=True), ForeignKey("workers.id"), nullable=True)

class Watchlist(Base):
    __tablename__ = "watchlist"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    added_by = Column(String)
    added_at = Column(String)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    qdrant_vector_id = Column(String, nullable=True)

class ROI(Base):
    __tablename__ = "roi"
    id = Column(String, primary_key=True)
    roi = Column(Text)
    location = Column(String)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)

# Other existing tables for Alembic to track

class PersonPhoto(Base):
    __tablename__ = "person_photos"
    id = Column(String, primary_key=True)
    person_id = Column(String, ForeignKey("watchlist.id"), nullable=False) # Updated to watchlist.id
    embedding = Column(LargeBinary, nullable=False)
    snapshot_path = Column(String)
    added_at = Column(String)

class ObjectDetection(Base):
    __tablename__ = "object_detections"
    id = Column(String, primary_key=True)
    camera_id = Column(String)
    location = Column(String)
    timestamp = Column(String)
    object_label = Column(String)
    confidence = Column(Float)
    snapshot_path = Column(String)

class AlertRule(Base):
    __tablename__ = "alert_rules"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    rule_type = Column(String, nullable=False)
    camera_id = Column(String, default='')
    conditions = Column(Text, default='{}')
    actions = Column(Text, default='{}')
    enabled = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

class NotificationConfig(Base):
    __tablename__ = "notification_config"
    key = Column(String, primary_key=True)
    value = Column(String)

class NotificationLog(Base):
    __tablename__ = "notification_log"
    id = Column(String, primary_key=True)
    channel = Column(String)
    recipient = Column(String)
    subject = Column(String)
    status = Column(String)
    error = Column(String)
    sent_at = Column(String)

class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(String, primary_key=True)
    timestamp = Column(String, nullable=False)
    username = Column(String, nullable=False)
    role = Column(String, nullable=False)
    action = Column(String, nullable=False)
    target = Column(String, default='')
    detail = Column(String, default='')
    ip_address = Column(String, default='')

class CameraStopRequest(Base):
    __tablename__ = "camera_stop_requests"
    id = Column(String, primary_key=True)
    camera_id = Column(String, nullable=False)
    worker_user = Column(String, nullable=False)
    reason = Column(String, default='')
    status = Column(String, default='pending')
    requested_at = Column(String, nullable=False)
    reviewed_by = Column(String, default=None)
    reviewed_at = Column(String, default=None)
