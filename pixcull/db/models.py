"""SQLModel schemas for the local project DB. V0.3+."""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    root_folder: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    strictness: str = "standard"


class Photo(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    path: str
    filename: str
    exif_datetime: Optional[datetime] = None
    scene: Optional[str] = None
    cluster_id: Optional[int] = None
    score_final: Optional[float] = None
    decision: Optional[str] = None
    manual_override: Optional[str] = None


class Cluster(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    best_photo_id: Optional[int] = None
