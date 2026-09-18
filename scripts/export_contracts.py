import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "apps/api"))
from operator_api.main import app  # noqa: E402 - allow running directly from a source checkout
from operator_api.schemas import MissionInput, JobPosting, CandidateProfile, RequirementMatch, MissionResult  # noqa: E402 - allow running directly from a source checkout

out = root / "packages/contracts"
(out / "schemas/v1").mkdir(parents=True, exist_ok=True)
(out / "openapi.json").write_text(json.dumps(app.openapi(), indent=2) + "\n")
for model in (MissionInput, JobPosting, CandidateProfile, RequirementMatch, MissionResult):
    (out / "schemas/v1" / f"{model.__name__}.json").write_text(
        json.dumps(model.model_json_schema(), indent=2) + "\n"
    )
