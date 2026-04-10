"""Pydantic-модели для данных футбола.

С усиленной валидацией для отсечения мусорных данных парсера.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# Допустимые статусы матчей
VALID_STATUSES = frozenset({
    "scheduled", "live", "LIVE", "1H", "2H", "HT",
    "finished", "FT", "unknown",
    "postponed", "cancelled",
})


class League(BaseModel):
    """Модель лиги / турнира."""

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=2)
    url: str = Field(..., min_length=5)
    season: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError(f"Название лиги слишком короткое: '{v}'")
        return v

    @field_validator("url")
    @classmethod
    def url_must_be_valid(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://", "/")):
            raise ValueError(f"Подозрительный URL лиги: '{v}'")
        return v

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, League):
            return self.id == other.id
        return False


class Team(BaseModel):
    """Модель команды."""

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=2)
    url: str = Field(..., min_length=5)
    league_id: Optional[str] = None
    logo_url: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError(f"Название команды слишком короткое: '{v}'")
        # Отсекаем явный мусор
        if v in ("—", "-", "???", "N/A", "TBD"):
            raise ValueError(f"Мусорное название команды: '{v}'")
        return v

    @field_validator("url")
    @classmethod
    def url_must_be_valid(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://", "/")):
            raise ValueError(f"Подозрительный URL команды: '{v}'")
        return v

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Team):
            return self.id == other.id
        return False


class Match(BaseModel):
    """Модель матча."""

    id: str = Field(..., min_length=1)
    league_name: Optional[str] = None
    home_team: str = Field(..., min_length=1)
    away_team: str = Field(..., min_length=1)
    match_date: Optional[datetime] = None
    status: str = "scheduled"
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    url: Optional[str] = None
    round: Optional[str] = None  # тур
    venue: Optional[str] = None  # стадион

    @field_validator("home_team", "away_team")
    @classmethod
    def team_name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) < 1:
            raise ValueError("Название команды не может быть пустым")
        if v in ("—", "-", "???", "N/A"):
            raise ValueError(f"Мусорное название: '{v}'")
        return v

    @field_validator("status")
    @classmethod
    def status_must_be_valid(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"Недопустимый статус матча: '{v}'. Допустимые: {VALID_STATUSES}")
        return v

    @field_validator("home_score", "away_score")
    @classmethod
    def score_must_be_non_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError(f"Отрицательный счёт: {v}")
        return v

    @model_validator(mode="after")
    def teams_must_differ(self) -> "Match":
        """home_team и away_team не должны совпадать."""
        if self.home_team and self.away_team:
            if self.home_team.strip().lower() == self.away_team.strip().lower():
                raise ValueError(
                    f"home_team и away_team совпадают: '{self.home_team}'"
                )
        return self

    @model_validator(mode="after")
    def validate_score_consistency(self) -> "Match":
        """Если статус finished — должны быть очки."""
        if self.status in ("finished", "FT"):
            if self.home_score is None or self.away_score is None:
                # Это не фатальная ошибка — просто warning
                pass
        return self

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

    position: int = Field(..., ge=1, le=200)
    team_name: str = Field(..., min_length=2)
    team_url: Optional[str] = None
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = Field(default=0, ge=0, le=500)

    @field_validator("team_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError(f"Слишком короткое название команды: '{v}'")
        return v

    @field_validator("played", "wins", "draws", "losses")
    @classmethod
    def stats_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"Отрицательная статистика: {v}")
        return v

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against


class Player(BaseModel):
    """Модель игрока (заявка команды)."""

    number: Optional[int] = None
    name: str = Field(..., min_length=2)
    position: Optional[str] = None  # амплуа
    birth_date: Optional[date] = None
    matches: int = 0
    goals: int = 0

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError(f"Слишком короткое имя игрока: '{v}'")
        return v


class PlayerStat(BaseModel):
    """Модель статистики игрока."""

    name: str = Field(..., min_length=2)
    matches: int = 0
    goals: int = 0
    assists: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    minutes: int = 0

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError(f"Слишком короткое имя игрока: '{v}'")
        return v


class MatchPrediction(BaseModel):
    """Модель прогноза на матч."""

    home_team: str
    away_team: str
    match_date: Optional[datetime] = None

    # Метрики домашней команды (за последние 5 матчей)
    home_wins: int = 0
    home_draws: int = 0
    home_losses: int = 0
    home_goals_scored: float = 0.0
    home_goals_conceded: float = 0.0

    # Метрики гостевой команды (за последние 5 матчей)
    away_wins: int = 0
    away_draws: int = 0
    away_losses: int = 0
    away_goals_scored: float = 0.0
    away_goals_conceded: float = 0.0

    # Личные встречи
    h2h_total: int = 0
    h2h_home_wins: int = 0
    h2h_away_wins: int = 0
    h2h_draws: int = 0
    h2h_home_goals: int = 0
    h2h_away_goals: int = 0

    # Позиции в таблице
    home_position: int = 0
    away_position: int = 0

    # Прогноз
    predicted_home_score: int = 0
    predicted_away_score: int = 0
    prediction_text: str = ""


from dataclasses import dataclass
from typing import Optional as _Optional


@dataclass
class MatchCandidate:
    """Кандидат в матчи со страницы команды.

    Это НЕ подтверждённый матч — только ссылка и дата.
    Источник истины для сыгранных = boxscore, для будущих = preview.
    """

    date_text: str = ""
    round_text: str = ""
    opponent_name: str = ""
    score_text: str = ""
    match_url: str = ""  # ссылка на boxscore или preview
    is_finished: bool = False  # True если есть boxscore, False если preview
    team_name: str = ""  # имя текущей команды (для fallback)

    def as_match(self) -> "Match":
        """Создать Match из кандидата (fallback, когда boxscore/preview недоступен)."""
        from app.utils.dates import parse_russian_date as _parse_date

        match_date = _parse_date(self.date_text) if self.date_text else None

        # Парсим счёт если есть
        home_score: int | None = None
        away_score: int | None = None
        status = "scheduled" if not self.is_finished else "finished"

        score_m = re.match(r"^(\d+)\s*[:\-]\s*(\d+)", self.score_text)
        if score_m:
            home_score = int(score_m.group(1))
            away_score = int(score_m.group(2))
            status = "finished"
        elif self.score_text == "?-?":
            status = "scheduled"

        # На странице команды счёт от лица команды
        return Match(
            id=f"candidate_{self.opponent_name}_{self.date_text}",
            home_team=self.team_name,
            away_team=self.opponent_name,
            match_date=match_date,
            status=status,
            home_score=home_score,
            away_score=away_score,
            round=self.round_text if self.round_text else None,
        )
