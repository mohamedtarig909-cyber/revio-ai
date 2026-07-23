"""Lightweight first-party traffic tracking.

One row per page view, written by the public /api/v1/track endpoint. No cookies
and no third-party analytics: the visitor id is a random string the browser
keeps in localStorage, so we can count unique visitors without identifying
anyone. Powers the Traffic section of the owner dashboard.
"""
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PageView(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "page_views"

    path: Mapped[str] = mapped_column(String(300), default="/", index=True)
    referrer: Mapped[str] = mapped_column(String(300), default="")
    visitor_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    country: Mapped[str] = mapped_column(String(80), default="")
