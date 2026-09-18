import time
from temporalio import activity
from temporalio.exceptions import ApplicationError
from operator_api import runtime, profiles
from operator_api.schemas import JobPosting, CandidateProfile
from operator_api.db import Mission
from .analysis import match, result, verify


class Activities:
    def __init__(self, sessions):
        self.sessions = sessions

    @activity.defn
    def execute_step(self, request: dict) -> dict:
        mission_id, run_number, name = request["mission_id"], request["run_number"], request["step"]
        start = time.perf_counter()
        state = runtime.begin_step(self.sessions, mission_id, run_number, name)
        if state.get("stopped"):
            return state
        if "cached" in state:
            return state["cached"]
        if state.get("simulate_failure"):
            raise ApplicationError("Simulated temporary matching failure", type="SimulatedFailure")
        inputs = request.get("inputs", {})
        try:
            if name == "planning":
                with self.sessions() as db:
                    mission = db.get(Mission, mission_id)
                    profile = profiles.load(db, mission.workspace_id, runtime.sample_profile)
                    job = runtime.load_job(db, mission)
                payload = {
                    "candidate_profile": profile.model_dump(mode="json"),
                    "job_posting": job.model_dump(mode="json"),
                    "steps": list(runtime.STEP_NAMES),
                    "execution_mode": "synthetic-fixture",
                    "job_url": state["job_url"],
                    "model_calls": 0,
                }
            elif name == "extracting":
                payload = inputs["planning"]["job_posting"]
            elif name == "matching":
                payload = match(
                    JobPosting.model_validate(inputs["extracting"]),
                    CandidateProfile.model_validate(inputs["planning"]["candidate_profile"]),
                )
            elif name == "verifying":
                payload = verify(JobPosting.model_validate(inputs["extracting"]), inputs["matching"])
            elif name == "generating":
                payload = result(mission_id, inputs["matching"], inputs["verifying"])
            else:
                raise ValueError("Unregistered fixture activity")
        except ValueError as exc:
            raise ApplicationError(str(exc), type="InvalidFixture", non_retryable=True) from exc
        return runtime.finish_step(
            self.sessions, mission_id, run_number, name, payload, round((time.perf_counter() - start) * 1000)
        )

    @activity.defn
    def mark_failed(self, request: dict) -> None:
        runtime.fail_mission(self.sessions, request["mission_id"], request["run_number"], request["step"])
