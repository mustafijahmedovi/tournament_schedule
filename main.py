from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
import json
import uuid
from datetime import datetime

from scheduler import generate_round_robin, split_into_groups

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Database setup ----------
def init_db():
    conn = sqlite3.connect("tournaments.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tournaments (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            groups_json TEXT NOT NULL,
            schedule_json TEXT NOT NULL,
            results_json TEXT NOT NULL,
            points_win INTEGER NOT NULL DEFAULT 3,
            points_draw INTEGER NOT NULL DEFAULT 1,
            points_loss INTEGER NOT NULL DEFAULT 0,
            game_type TEXT NOT NULL DEFAULT 'football',
            knockout_json TEXT NOT NULL DEFAULT '[]',
            tournament_format TEXT NOT NULL DEFAULT 'league',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()


# ---------- Request models ----------
class CreateTournamentInput(BaseModel):
    name: str
    teams: List[str]
    num_groups: int = 1
    game_type: str = "football"
    tournament_format: str = "league"  # "league" (group stage + optional knockout) or "knockout" (direct single elimination)
    points_win: int = 3
    points_draw: int = 1
    points_loss: int = 0
    sport: str = "other"


class MatchResultInput(BaseModel):
    tournament_id: str
    group_index: int
    round_index: int
    match_index: int
    team1_score: int
    team2_score: int
    team1_wickets: Optional[int] = None
    team2_wickets: Optional[int] = None


class AddKnockoutRoundInput(BaseModel):
    tournament_id: str
    round_name: str
    matchups: List[List[str]]  # e.g. [["Team A", "Team B"], ["Team C", "Team D"]]


class KnockoutResultInput(BaseModel):
    tournament_id: str
    round_index: int
    match_index: int
    winner: str
    team1_score: Optional[int] = None
    team2_score: Optional[int] = None
    team1_wickets: Optional[int] = None
    team2_wickets: Optional[int] = None


class MatchScheduleInput(BaseModel):
    tournament_id: str
    group_index: int
    round_index: int
    match_index: int
    match_time: Optional[str] = None
    location: Optional[str] = None


class KnockoutScheduleInput(BaseModel):
    tournament_id: str
    round_index: int
    match_index: int
    match_time: Optional[str] = None
    location: Optional[str] = None


# ---------- Routes ----------
@app.get("/")
def read_root():
    return {"message": "Tournament Scheduler API is running!"}


@app.post("/tournament")
def create_tournament(input: CreateTournamentInput):
    if len(input.teams) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 teams")

    is_knockout_only = input.tournament_format == "knockout"

    if is_knockout_only:
        # Direct knockout: no group stage, all teams in one bucket for reference,
        # no round-robin schedule generated
        groups = [input.teams]
        schedule_per_group = [[]]
        results = [[]]
    else:
        if input.num_groups < 1:
            raise HTTPException(status_code=400, detail="Need at least 1 group")
        if input.num_groups > len(input.teams):
            raise HTTPException(status_code=400, detail="Cannot have more groups than teams")

        # Split teams into groups
        groups = split_into_groups(input.teams, input.num_groups)

        # Generate a round-robin schedule for each group
        schedule_per_group = []
        for group in groups:
            group_schedule = generate_round_robin(group)
            schedule_per_group.append(group_schedule)

        # Set up an empty results structure matching the schedule shape
        results = []
        for group_schedule in schedule_per_group:
            group_results = []
            for round_matches in group_schedule:
                round_results = []
                for match in round_matches:
                    round_results.append({
                        "team1_score": None, "team2_score": None,
                        "team1_wickets": None, "team2_wickets": None,
                        "played": False,
                        "match_time": None, "location": None
                    })
                group_results.append(round_results)
            results.append(group_results)

    tournament_id = str(uuid.uuid4())[:8]  # short shareable ID
    created_at = datetime.now().isoformat()

    conn = sqlite3.connect("tournaments.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tournaments (id, name, groups_json, schedule_json, results_json, points_win, points_draw, points_loss, game_type, knockout_json, tournament_format, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            tournament_id,
            input.name,
            json.dumps(groups),
            json.dumps(schedule_per_group),
            json.dumps(results),
            input.points_win,
            input.points_draw,
            input.points_loss,
            input.game_type,
            json.dumps([]),
            input.tournament_format,
            created_at
        )
    )
    conn.commit()
    conn.close()

    return {"tournament_id": tournament_id, "message": "Tournament created!"}


@app.get("/tournament/{tournament_id}")
def get_tournament(tournament_id: str):
    conn = sqlite3.connect("tournaments.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail="Tournament not found")

    return {
        "id": row["id"],
        "name": row["name"],
        "groups": json.loads(row["groups_json"]),
        "schedule": json.loads(row["schedule_json"]),
        "results": json.loads(row["results_json"]),
        "points_win": row["points_win"],
        "points_draw": row["points_draw"],
        "points_loss": row["points_loss"],
        "game_type": row["game_type"],
        "knockout": json.loads(row["knockout_json"]),
        "tournament_format": row["tournament_format"],
        "created_at": row["created_at"]
    }


@app.post("/match-result")
def submit_match_result(input: MatchResultInput):
    conn = sqlite3.connect("tournaments.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tournaments WHERE id = ?", (input.tournament_id,))
    row = cursor.fetchone()

    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Tournament not found")

    results = json.loads(row["results_json"])

    try:
        match = results[input.group_index][input.round_index][input.match_index]
        match["team1_score"] = input.team1_score
        match["team2_score"] = input.team2_score
        match["team1_wickets"] = input.team1_wickets
        match["team2_wickets"] = input.team2_wickets
        match["played"] = True
    except IndexError:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid group/round/match index")

    cursor.execute(
        "UPDATE tournaments SET results_json = ? WHERE id = ?",
        (json.dumps(results), input.tournament_id)
    )
    conn.commit()
    conn.close()

    return {"message": "Result saved"}


@app.get("/tournament/{tournament_id}/standings")
def get_standings(tournament_id: str):
    conn = sqlite3.connect("tournaments.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail="Tournament not found")

    groups = json.loads(row["groups_json"])
    schedule = json.loads(row["schedule_json"])
    results = json.loads(row["results_json"])
    points_win = row["points_win"]
    points_draw = row["points_draw"]
    points_loss = row["points_loss"]

    all_standings = []

    for group_index, group_teams in enumerate(groups):
        # Initialize stats for every team in this group
        stats = {
            team: {"played": 0, "won": 0, "drawn": 0, "lost": 0,
                   "goals_for": 0, "goals_against": 0, "points": 0}
            for team in group_teams
        }

        group_schedule = schedule[group_index]
        group_results = results[group_index]

        for round_index, round_matches in enumerate(group_schedule):
            for match_index, match in enumerate(round_matches):
                team1, team2 = match
                result = group_results[round_index][match_index]

                # Skip byes and unplayed matches
                if team1 == "BYE" or team2 == "BYE" or not result["played"]:
                    continue

                s1, s2 = result["team1_score"], result["team2_score"]

                stats[team1]["played"] += 1
                stats[team2]["played"] += 1
                stats[team1]["goals_for"] += s1
                stats[team1]["goals_against"] += s2
                stats[team2]["goals_for"] += s2
                stats[team2]["goals_against"] += s1

                if s1 > s2:
                    stats[team1]["won"] += 1
                    stats[team1]["points"] += points_win
                    stats[team2]["lost"] += 1
                    stats[team2]["points"] += points_loss
                elif s2 > s1:
                    stats[team2]["won"] += 1
                    stats[team2]["points"] += points_win
                    stats[team1]["lost"] += 1
                    stats[team1]["points"] += points_loss
                else:
                    stats[team1]["drawn"] += 1
                    stats[team2]["drawn"] += 1
                    stats[team1]["points"] += points_draw
                    stats[team2]["points"] += points_draw

        # Build a sorted table: points desc, then goal difference desc
        table = []
        for team, s in stats.items():
            goal_diff = s["goals_for"] - s["goals_against"]
            table.append({
                "team": team,
                "played": s["played"],
                "won": s["won"],
                "drawn": s["drawn"],
                "lost": s["lost"],
                "goals_for": s["goals_for"],
                "goals_against": s["goals_against"],
                "goal_difference": goal_diff,
                "points": s["points"]
            })

        table.sort(key=lambda x: (-x["points"], -x["goal_difference"], -x["goals_for"]))
        all_standings.append(table)

    return {"standings": all_standings}


@app.post("/tournament/{tournament_id}/knockout/round")
def add_knockout_round(tournament_id: str, input: AddKnockoutRoundInput):
    conn = sqlite3.connect("tournaments.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
    row = cursor.fetchone()

    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Tournament not found")

    if len(input.matchups) < 1:
        conn.close()
        raise HTTPException(status_code=400, detail="Need at least 1 matchup")

    knockout = json.loads(row["knockout_json"])

    new_round = {
        "round_name": input.round_name,
        "matches": [
            {
                "team1": pair[0],
                "team2": pair[1],
                "team1_score": None,
                "team2_score": None,
                "team1_wickets": None,
                "team2_wickets": None,
                "winner": None,
                "played": False,
                "match_time": None,
                "location": None
            }
            for pair in input.matchups
        ]
    }

    knockout.append(new_round)

    cursor.execute(
        "UPDATE tournaments SET knockout_json = ? WHERE id = ?",
        (json.dumps(knockout), tournament_id)
    )
    conn.commit()
    conn.close()

    return {"message": "Knockout round added"}


@app.post("/knockout-result")
def submit_knockout_result(input: KnockoutResultInput):
    conn = sqlite3.connect("tournaments.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tournaments WHERE id = ?", (input.tournament_id,))
    row = cursor.fetchone()

    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Tournament not found")

    knockout = json.loads(row["knockout_json"])

    try:
        match = knockout[input.round_index]["matches"][input.match_index]
    except IndexError:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid round/match index")

    if input.winner not in [match["team1"], match["team2"]]:
        conn.close()
        raise HTTPException(status_code=400, detail="Winner must be one of the two teams in this match")

    match["team1_score"] = input.team1_score
    match["team2_score"] = input.team2_score
    match["team1_wickets"] = input.team1_wickets
    match["team2_wickets"] = input.team2_wickets
    match["winner"] = input.winner
    match["played"] = True

    cursor.execute(
        "UPDATE tournaments SET knockout_json = ? WHERE id = ?",
        (json.dumps(knockout), input.tournament_id)
    )
    conn.commit()
    conn.close()

    return {"message": "Knockout result saved"}


@app.delete("/tournament/{tournament_id}/knockout/round/{round_index}")
def delete_knockout_round(tournament_id: str, round_index: int):
    conn = sqlite3.connect("tournaments.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
    row = cursor.fetchone()

    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Tournament not found")

    knockout = json.loads(row["knockout_json"])

    try:
        knockout.pop(round_index)
    except IndexError:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid round index")

    cursor.execute(
        "UPDATE tournaments SET knockout_json = ? WHERE id = ?",
        (json.dumps(knockout), tournament_id)
    )
    conn.commit()
    conn.close()

    return {"message": "Knockout round removed"}


@app.post("/match-schedule")
def set_match_schedule(input: MatchScheduleInput):
    conn = sqlite3.connect("tournaments.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tournaments WHERE id = ?", (input.tournament_id,))
    row = cursor.fetchone()

    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Tournament not found")

    results = json.loads(row["results_json"])

    try:
        match = results[input.group_index][input.round_index][input.match_index]
    except IndexError:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid group/round/match index")

    match["match_time"] = input.match_time
    match["location"] = input.location

    cursor.execute(
        "UPDATE tournaments SET results_json = ? WHERE id = ?",
        (json.dumps(results), input.tournament_id)
    )
    conn.commit()
    conn.close()

    return {"message": "Match schedule saved"}


@app.post("/knockout-schedule")
def set_knockout_schedule(input: KnockoutScheduleInput):
    conn = sqlite3.connect("tournaments.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tournaments WHERE id = ?", (input.tournament_id,))
    row = cursor.fetchone()

    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Tournament not found")

    knockout = json.loads(row["knockout_json"])

    try:
        match = knockout[input.round_index]["matches"][input.match_index]
    except IndexError:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid round/match index")

    match["match_time"] = input.match_time
    match["location"] = input.location

    cursor.execute(
        "UPDATE tournaments SET knockout_json = ? WHERE id = ?",
        (json.dumps(knockout), input.tournament_id)
    )
    conn.commit()
    conn.close()

    return {"message": "Knockout match schedule saved"}