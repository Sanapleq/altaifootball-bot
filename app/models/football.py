"""Pydantic-модели для данных футбола."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class League(BaseModel):
    """Модель лиги / турнира."""

    id: str
    name: str
    url: str
    season: Optional[str] = None

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, League):
            return self.id == other.id
        return False


class Team(BaseModel):
    """Модель команды."""

    id: str
    name: str
    url: str
    league_id: Optional[str] = None
    logo_url: Optional[str] = None

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Team):
            return self.id == other.id
        return False


class Match(BaseModel):
    """Модель матча."""

    id: str
    league_name: Optional[str] = None
    home_team: str
    away_team: str
    match_date: Optional[datetime] = None
    status: str = "scheduled"  # scheduled, live, finished, unknown, postponed, cancelled
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    url: Optional[str] = None
    round: Optional[str] = None  # тур
    venue: Optional[str] = None  # стадион

    @property
    def is_finished(self) -> bool:
        return self.status in ("finished", "FT")

    @property
    def is_live(self) -> bool:
        return self.status in ("live", "LIVE", "1H", "2H", "HT")

    @property
    def score_display(self) -> str:
        if self.home_score is not None and self.away_score is not None:
            return f"{self.home_score}:{self.away_score}"
        return "vs"


class StandingRow(BaseModel):
    """Строка турнирной таблицы."""

    position: int
    team_name: str
    team_url: Optional[str] = None
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against
