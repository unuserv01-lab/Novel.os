"""Database schema. SQLite by default (zero setup); set DATABASE_URL for PostgreSQL."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    genre: Mapped[str] = mapped_column(String(80), default="fantasy")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class StoryBible(Base):
    __tablename__ = "story_bibles"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), unique=True)
    lore: Mapped[str] = mapped_column(Text, default="")
    world_rules: Mapped[list] = mapped_column(JSON, default=list)
    timeline: Mapped[list] = mapped_column(JSON, default=list)
    style: Mapped[str] = mapped_column(Text, default="")  # Style Bible, one per project


class Character(Base):
    __tablename__ = "characters"
    __table_args__ = (UniqueConstraint("project_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    code: Mapped[str] = mapped_column(String(40))  # e.g. CHR_KAEL_001
    name: Mapped[str] = mapped_column(String(120))
    identity: Mapped[dict] = mapped_column(JSON, default=dict)  # hair, eyes, face, body
    outfits: Mapped[dict] = mapped_column(JSON, default=dict)
    expressions: Mapped[list] = mapped_column(JSON, default=list)
    state: Mapped[dict] = mapped_column(JSON, default=dict)  # injuries, location, timeline tag
    references: Mapped[list["CharacterReference"]] = relationship(back_populates="character", cascade="all, delete-orphan")


class CharacterReference(Base):
    __tablename__ = "character_references"
    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"))
    path: Mapped[str] = mapped_column(String(500))  # relative to storage dir
    sha256: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(40), default="reference")  # reference | placeholder
    character: Mapped[Character] = relationship(back_populates="references")


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (UniqueConstraint("project_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("project_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    number: Mapped[int] = mapped_column(Integer)
    premise: Mapped[str] = mapped_column(Text)
    # draft -> scripted -> storyboarded -> rendered -> awaiting_approval -> approved -> exported
    # side states: needs_attention (panels failed QC), paused_budget (cost cap hit)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    script: Mapped[dict | None] = mapped_column(JSON, default=None)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    panels: Mapped[list["Panel"]] = relationship(back_populates="episode", order_by="Panel.index", cascade="all, delete-orphan")


class Panel(Base):
    __tablename__ = "panels"
    __table_args__ = (UniqueConstraint("episode_id", "index"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"))
    index: Mapped[int] = mapped_column(Integer)
    scene_no: Mapped[int] = mapped_column(Integer, default=1)
    spec: Mapped[dict] = mapped_column(JSON, default=dict)  # characters, location, camera, emotion, description
    layout: Mapped[dict] = mapped_column(JSON, default=dict)  # height ratio, gap (Director)
    dialog: Mapped[list] = mapped_column(JSON, default=list)  # bubbles + sfx: a layer, never baked into images
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | passed | failed
    current_asset_id: Mapped[int | None] = mapped_column(ForeignKey("generated_assets.id", use_alter=True), default=None)
    episode: Mapped[Episode] = relationship(back_populates="panels")


class GeneratedAsset(Base):
    """Every render is a new immutable version; nothing is overwritten or deleted."""

    __tablename__ = "generated_assets"
    __table_args__ = (UniqueConstraint("panel_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    panel_id: Mapped[int] = mapped_column(ForeignKey("panels.id"))
    version: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(500))
    prompt: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(120))
    references: Mapped[list] = mapped_column(JSON, default=list)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProductionJob(Base):
    __tablename__ = "production_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"))
    step: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))  # ok | failed | skipped
    detail: Mapped[str] = mapped_column(Text, default="")
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    seconds: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class QCReport(Base):
    __tablename__ = "qc_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    panel_id: Mapped[int] = mapped_column(ForeignKey("panels.id"))
    asset_id: Mapped[int] = mapped_column(ForeignKey("generated_assets.id"))
    kind: Mapped[str] = mapped_column(String(20))  # automated | model
    passed: Mapped[bool] = mapped_column(default=False)
    issues: Mapped[list] = mapped_column(JSON, default=list)


def make_engine(url: str):
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    return create_engine(url, **kwargs)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)


def session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session_scope(factory) -> Session:
    s = factory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
