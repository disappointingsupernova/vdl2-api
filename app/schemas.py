from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class AddressSummary(BaseModel):
    icao: Optional[str]
    type: Optional[str] = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: Optional[str]
    timestamp_ms: Optional[int]
    ingested_at: str
    station_id: Optional[str]
    frequency_hz: Optional[int]
    source: AddressSummary
    destination: AddressSummary
    direction: Optional[str]
    message_type: Optional[str]
    aircraft_registration: Optional[str]
    flight_id: Optional[str]
    message_text: Optional[str]
    raw: Dict[str, Any]


class MessagesResponse(BaseModel):
    messages: List[MessageOut]
    count: int
    first_id: Optional[int]
    last_id: Optional[int]
    has_more: bool


class HealthResponse(BaseModel):
    status: str
    database: str
    collector: str
    last_message_at: Optional[str]
    last_message_age_seconds: Optional[float]
    total_messages: int


class StatsResponse(BaseModel):
    messages_total: int
    messages_last_minute: int
    messages_last_hour: int
    messages_by_frequency: Dict[str, int]
    unique_aircraft_last_hour: int


class AircraftSummary(BaseModel):
    icao: str
    first_seen: Optional[str]
    last_seen: Optional[str]
    message_count: int
    registration: Optional[str]
    flight_id: Optional[str]


class AircraftListResponse(BaseModel):
    aircraft: List[AircraftSummary]
