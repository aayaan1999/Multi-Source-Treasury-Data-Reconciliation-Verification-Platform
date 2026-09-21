from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import Json
from pydantic import BaseModel, Field, field_validator

from ..db import query, query_one, write
from ..security import current_user

router = APIRouter(prefix="/scenario", tags=["screen 4 - scenario modelling"], dependencies=[Depends(current_user)])


@router.get("/snapshot")
def snapshot():
    """The single-row position the React app fetches once on load. Slider recomputes happen in the browser,
    so there is deliberately no recompute endpoint."""
    row = query_one("SELECT * FROM scenario_snapshot ORDER BY calculation_date DESC LIMIT 1")
    if row is None:
        raise HTTPException(404, "No scenario snapshot loaded yet - run the pipeline first")
    return row


class ScenarioInputs(BaseModel):
    devaluation_pct: float = Field(ge=0, le=50)
    rate_change_pct: float = Field(ge=-5, le=5)
    npl_increase_pct: float = Field(ge=0, le=15)
    deposit_outflow_pct: float = Field(ge=0, le=30)


class SaveScenario(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    inputs: ScenarioInputs
    assumptions: dict
    outputs: dict

    @field_validator("name")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A scenario needs a name")
        return value


@router.post("/save", status_code=201)
def save(body: SaveScenario, user: dict = Depends(current_user)):
    """Keeps a scenario (its four inputs, the assumptions in force, and the results as shown) for the comparison table."""
    row = write(
        """INSERT INTO saved_scenarios (name, inputs, assumptions, outputs, created_by)
           VALUES (%s, %s, %s, %s, %s) RETURNING scenario_id, name, created_at""",
        (body.name, Json(body.inputs.model_dump()), Json(body.assumptions), Json(body.outputs), user["user_id"]),
    )
    return row


@router.get("/saved")
def saved():
    return query(
        """SELECT s.scenario_id, s.name, s.inputs, s.assumptions, s.outputs, s.created_at, u.name AS created_by_name
           FROM saved_scenarios s LEFT JOIN users u ON u.user_id = s.created_by
           ORDER BY s.created_at DESC LIMIT 50"""
    )
