"""
Context builder – assembles game context from play-by-play events
so the classifier has everything it needs without raw video.

The context includes:
  - Game score differential at time of call
  - Period and game clock
  - Prior fouls on player / team
  - Surrounding PBP events (±3 plays)
  - Player positions and movement (from PBP coordinates when available)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GameContext:
    """Structured context passed to the call classifier."""

    # Event under review
    period: int
    game_clock: str
    play_type: str
    play_info: str
    player_name: str | None
    team_code: str | None

    # Score context
    home_score: int
    away_score: int
    home_team_code: str
    away_team_code: str

    # Foul context
    player_fouls_in_game: int = 0        # fouls on this player so far
    home_team_fouls_in_period: int = 0
    away_team_fouls_in_period: int = 0
    bonus_situation: bool = False         # team in penalty/bonus

    # Surrounding play sequence
    preceding_events: list[dict] = field(default_factory=list)  # up to 3 events before
    following_events: list[dict] = field(default_factory=list)  # up to 3 events after

    # Coordinates (court position, if available)
    coordinates_x: float | None = None
    coordinates_y: float | None = None

    def to_prompt_text(self) -> str:
        """Format context as a natural-language prompt for the LLM."""
        score_diff = self.home_score - self.away_score
        diff_str = (
            f"{self.home_team_code} +{score_diff}" if score_diff > 0
            else f"{self.away_team_code} +{abs(score_diff)}" if score_diff < 0
            else "tied"
        )

        bonus_str = ""
        if self.bonus_situation:
            bonus_str = "\n- Team is in the bonus (free-throw penalty situation)."

        player_fouls_str = (
            f"\n- {self.player_name} has {self.player_fouls_in_game} fouls this game."
            if self.player_name
            else ""
        )

        period_fouls = (
            f"\n- Team fouls this period: {self.home_team_code}={self.home_team_fouls_in_period}, "
            f"{self.away_team_code}={self.away_team_fouls_in_period}."
        )

        preceding = ""
        if self.preceding_events:
            lines = [
                f"  {i+1}. [{e.get('period')}Q {e.get('game_clock')}] "
                f"{e.get('play_type')} – {e.get('play_info') or ''}"
                for i, e in enumerate(self.preceding_events)
            ]
            preceding = "\nPreceding plays:\n" + "\n".join(lines)

        following = ""
        if self.following_events:
            lines = [
                f"  {i+1}. [{e.get('period')}Q {e.get('game_clock')}] "
                f"{e.get('play_type')} – {e.get('play_info') or ''}"
                for i, e in enumerate(self.following_events)
            ]
            following = "\nFollowing plays:\n" + "\n".join(lines)

        coords_str = ""
        if self.coordinates_x is not None and self.coordinates_y is not None:
            coords_str = f"\n- Court position: x={self.coordinates_x:.1f}, y={self.coordinates_y:.1f}"

        return (
            f"GAME CONTEXT\n"
            f"Period {self.period}Q, {self.game_clock} remaining.\n"
            f"Score: {self.home_team_code} {self.home_score} – {self.away_score} {self.away_team_code} ({diff_str}).\n"
            f"\nEVENT UNDER REVIEW\n"
            f"Play type: {self.play_type}\n"
            f"Description: {self.play_info or 'N/A'}\n"
            f"Player: {self.player_name or 'Unknown'} ({self.team_code or 'Unknown' })"
            f"{player_fouls_str}{period_fouls}{bonus_str}{coords_str}"
            f"{preceding}{following}"
        )


def build_context_for_event(
    event: dict,
    all_events: list[dict],
    home_team_code: str,
    away_team_code: str,
) -> GameContext:
    """
    Build a GameContext from a raw PBP event dict and the full event list.

    Args:
        event: The specific play-by-play event to analyse.
        all_events: All events for the game (ordered by period + clock).
        home_team_code: Home team code string.
        away_team_code: Away team code string.
    """
    period = event.get("period", 1)
    team_code = event.get("team_code") or event.get("TEAM")
    player_name = event.get("player_name") or event.get("PLAYER")

    # Reconstruct per-period foul counts up to this event
    event_idx = next(
        (i for i, e in enumerate(all_events) if e is event or e.get("id") == event.get("id")),
        0,
    )

    home_period_fouls = 0
    away_period_fouls = 0
    player_fouls = 0

    for e in all_events[:event_idx]:
        pt = (e.get("play_type") or "").upper()
        if "FOUL" in pt or pt in {"FV", "FT", "FO", "F", "PFOUL", "TFOUL"}:
            e_team = e.get("team_code") or e.get("TEAM") or ""
            if e.get("period") == period:
                if e_team == home_team_code:
                    home_period_fouls += 1
                elif e_team == away_team_code:
                    away_period_fouls += 1
            if player_name and (e.get("player_name") == player_name or e.get("PLAYER") == player_name):
                player_fouls += 1

    # Bonus: FIBA = 5 team fouls in a period triggers bonus
    bonus = (
        (team_code == away_team_code and home_period_fouls >= 5)
        or (team_code == home_team_code and away_period_fouls >= 5)
    )

    preceding = [e for e in all_events[max(0, event_idx - 3):event_idx]]
    following = [e for e in all_events[event_idx + 1: event_idx + 4]]

    return GameContext(
        period=period,
        game_clock=event.get("game_clock") or event.get("MARKERTIME") or "10:00",
        play_type=event.get("play_type") or event.get("PLAYTYPE") or "",
        play_info=event.get("play_info") or event.get("PLAYINFO") or "",
        player_name=player_name,
        team_code=team_code,
        home_score=event.get("home_score") or event.get("HOMESCORE") or 0,
        away_score=event.get("away_score") or event.get("VISITSCORE") or 0,
        home_team_code=home_team_code,
        away_team_code=away_team_code,
        player_fouls_in_game=player_fouls,
        home_team_fouls_in_period=home_period_fouls,
        away_team_fouls_in_period=away_period_fouls,
        bonus_situation=bonus,
        preceding_events=[
            {
                "period": e.get("period"),
                "game_clock": e.get("game_clock") or e.get("MARKERTIME"),
                "play_type": e.get("play_type") or e.get("PLAYTYPE"),
                "play_info": e.get("play_info") or e.get("PLAYINFO"),
            }
            for e in preceding
        ],
        following_events=[
            {
                "period": e.get("period"),
                "game_clock": e.get("game_clock") or e.get("MARKERTIME"),
                "play_type": e.get("play_type") or e.get("PLAYTYPE"),
                "play_info": e.get("play_info") or e.get("PLAYINFO"),
            }
            for e in following
        ],
        coordinates_x=event.get("coordinates_x") or event.get("COORD_X"),
        coordinates_y=event.get("coordinates_y") or event.get("COORD_Y"),
    )
