from pydantic import BaseModel, Field, ConfigDict
from typing import Literal
class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")
class Candidate(Strict):
    title: str
    angle: str
    query: str
class Candidates(Strict):
    candidates: list[Candidate] = Field(min_length=1,max_length=12)
class Evidence(Strict):
    source_id: str
    quote: str = Field(min_length=20,max_length=1000)
class Claim(Strict):
    id: str
    text: str
    evidence: list[Evidence] = Field(min_length=1,max_length=4)
class Dossier(Strict):
    title: str
    summary: str
    claims: list[Claim] = Field(min_length=4,max_length=12)
    uncertainties: list[str]
class Verdict(Strict):
    accepted: bool
    score: int = Field(ge=0,le=10)
    issues: list[str]
    correction: str
class VisualVerdict(Strict):
    accepted: bool
    score: int = Field(ge=0,le=100)
    issues: list[str]
    correction: str
class FactVerdict(Strict):
    claim_id: str
    supported: bool
    reason: str
class FactReview(Strict):
    claims: list[FactVerdict]
    independent_sources: bool
    issues: list[str]
class Scene(Strict):
    id: int = Field(ge=1,le=12)
    narration: str
    claim_ids: list[str] = Field(min_length=1)
    visual: str
    image_prompt: str
class Script(Strict):
    title: str
    description: str
    visual_bible: str
    scenes: list[Scene] = Field(min_length=5,max_length=9)
