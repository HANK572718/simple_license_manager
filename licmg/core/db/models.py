"""SQLAlchemy ORM models for licmg."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Project(Base):
    """A licensed software project.

    Audit fields (git_remote, project_root, git_user_name, git_user_email)
    are recorded at creation time so the registry remains meaningful even after
    the source tree is moved or the plugin is reinstalled.
    """

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    env_prefix: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String, default="1.0.0")
    fp_version: Mapped[int] = mapped_column(Integer, default=1)
    validity_days: Mapped[int] = mapped_column(Integer, default=365)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    # Audit / provenance fields — auto-detected from git at project creation
    git_remote: Mapped[str | None] = mapped_column(String, nullable=True)
    project_root: Mapped[str | None] = mapped_column(String, nullable=True)
    git_user_name: Mapped[str | None] = mapped_column(String, nullable=True)
    git_user_email: Mapped[str | None] = mapped_column(String, nullable=True)

    keys: Mapped[list["Key"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    licenses: Mapped[list["License"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Key(Base):
    """An RSA key pair record; private key is stored on disk only."""

    __tablename__ = "keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    version: Mapped[int] = mapped_column(Integer)
    algorithm: Mapped[str] = mapped_column(String, default="rsa2048")
    public_key_pem: Mapped[str] = mapped_column(Text)
    public_key_fp: Mapped[str] = mapped_column(String)
    private_key_path: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="keys")


class License(Base):
    """A signed license record."""

    __tablename__ = "licenses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    client_name: Mapped[str] = mapped_column(String)
    machine_fp: Mapped[str] = mapped_column(String)
    fp_version: Mapped[int] = mapped_column(Integer, default=1)
    key_version: Mapped[int] = mapped_column(Integer)
    mac_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    license_json: Mapped[str] = mapped_column(Text)
    lic_file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="licenses")
