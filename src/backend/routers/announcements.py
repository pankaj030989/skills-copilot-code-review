"""
Announcement endpoints for the High School Management System API
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..database import announcements_collection, teachers_collection

router = APIRouter(prefix="/announcements", tags=["announcements"])


class AnnouncementPayload(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    expires_at: datetime
    start_date: Optional[datetime] = None


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _to_iso_utc(value: datetime) -> str:
    return _normalize_datetime(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _now_iso_utc() -> str:
    return _to_iso_utc(datetime.now(timezone.utc))


def _require_teacher(teacher_username: Optional[str]) -> str:
    if not teacher_username:
        raise HTTPException(status_code=401, detail="Authentication required for this action")

    teacher = teachers_collection.find_one({"_id": teacher_username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")

    return teacher_username


def _serialize_announcement(document: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": document["_id"],
        "message": document["message"],
        "start_date": document.get("start_date"),
        "expires_at": document["expires_at"],
        "created_by": document.get("created_by"),
        "created_at": document.get("created_at"),
        "updated_at": document.get("updated_at"),
    }


@router.get("", response_model=List[Dict[str, Any]])
@router.get("/", response_model=List[Dict[str, Any]])
def get_active_announcements() -> List[Dict[str, Any]]:
    """Get currently active announcements for public display."""
    now_iso = _now_iso_utc()
    query = {
        "expires_at": {"$gt": now_iso},
        "$or": [
            {"start_date": None},
            {"start_date": {"$exists": False}},
            {"start_date": {"$lte": now_iso}},
        ],
    }

    announcements: List[Dict[str, Any]] = []
    for announcement in announcements_collection.find(query).sort("expires_at", 1):
        announcements.append(_serialize_announcement(announcement))

    return announcements


@router.get("/all", response_model=List[Dict[str, Any]])
def get_all_announcements(teacher_username: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """Get all announcements for management, including expired and scheduled items."""
    _require_teacher(teacher_username)

    announcements: List[Dict[str, Any]] = []
    for announcement in announcements_collection.find().sort("expires_at", -1):
        announcements.append(_serialize_announcement(announcement))

    return announcements


@router.post("", response_model=Dict[str, Any])
@router.post("/", response_model=Dict[str, Any])
def create_announcement(payload: AnnouncementPayload, teacher_username: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Create a new announcement."""
    username = _require_teacher(teacher_username)

    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Announcement message cannot be empty")

    expires_at_iso = _to_iso_utc(payload.expires_at)
    start_date_iso = _to_iso_utc(payload.start_date) if payload.start_date else None
    if start_date_iso and start_date_iso >= expires_at_iso:
        raise HTTPException(status_code=400, detail="Start date must be before expiration date")

    now_iso = _now_iso_utc()
    announcement = {
        "_id": str(uuid4()),
        "message": message,
        "start_date": start_date_iso,
        "expires_at": expires_at_iso,
        "created_by": username,
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    announcements_collection.insert_one(announcement)

    return _serialize_announcement(announcement)


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(
    announcement_id: str,
    payload: AnnouncementPayload,
    teacher_username: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Update an existing announcement."""
    _require_teacher(teacher_username)

    existing = announcements_collection.find_one({"_id": announcement_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Announcement not found")

    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Announcement message cannot be empty")

    expires_at_iso = _to_iso_utc(payload.expires_at)
    start_date_iso = _to_iso_utc(payload.start_date) if payload.start_date else None
    if start_date_iso and start_date_iso >= expires_at_iso:
        raise HTTPException(status_code=400, detail="Start date must be before expiration date")

    updated_values = {
        "message": message,
        "start_date": start_date_iso,
        "expires_at": expires_at_iso,
        "updated_at": _now_iso_utc(),
    }

    announcements_collection.update_one({"_id": announcement_id}, {"$set": updated_values})
    updated = announcements_collection.find_one({"_id": announcement_id})

    if not updated:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return _serialize_announcement(updated)


@router.delete("/{announcement_id}", response_model=Dict[str, str])
def delete_announcement(announcement_id: str, teacher_username: Optional[str] = Query(None)) -> Dict[str, str]:
    """Delete an announcement."""
    _require_teacher(teacher_username)

    result = announcements_collection.delete_one({"_id": announcement_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted"}