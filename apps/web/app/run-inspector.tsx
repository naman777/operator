"use client";
import { useState, useEffect } from "react";
import type { components } from "@operator/contracts";
import { request } from "../lib/api";
import { useMissionRun } from "../lib/use-mission-run";
type Mission = components["schemas"]["MissionView"];
type Match = components["schemas"]["RequirementMatch"];
type Job = components["schemas"]["JobPosting"];
type Profile = components["schemas"]["CandidateProfile"];

type Artifact = components["schemas"]["ArtifactView"];

const ARTIFACT_LABELS: Record<string, string> = {
  cover_letter: "Cover Letter",
  resume_suggestions: "Resume Suggestions",
  recruiter_message: "Recruiter Message",
  interview_brief: "Interview Brief",
};

const labels: Record<string, string> = {
  planning: "Plan sample run",
  extracting: "Load job fixture",
  matching: "Match evidence",
  verifying: "Verify provenance",
  generating: "Store sample report",
};

export function RunInspector({
  mission,
  token,
  onBack,
}: {
  mission: Mission;
  token: string;
  onBack: () => void;
}) {
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState("none");
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [artifactTab, setArtifactTab] = useState("");
  const [artifactError, setArtifactError] = useState("");
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [copyMessage, setCopyMessage] = useState("");

  const { run, events, connection, streamError } = useMissionRun(
    mission.id,
    token,
    revision,
  );
  const current = run?.mission ?? mission;
  const terminal = ["completed", "cancelled"].includes(current.status);

  const artifactIds = run?.result?.artifact_ids.join(",") ?? "";
  useEffect(() => {
    if (current.status !== "completed" || !token) {
      setArtifacts([]);
      return;
    }
    const controller = new AbortController();
    setArtifactLoading(true);
    setArtifactError("");
    request<Artifact[]>(`/v1/missions/${mission.id}/artifacts`, token, {
      signal: controller.signal,
    })
      .then((data) => {
        if (controller.signal.aborted) return;
        setArtifacts(data);
        setArtifactTab((previous) =>
          data.some((item) => item.id === previous)
            ? previous
            : (data[0]?.id ?? ""),
        );
      })
      .catch((cause) => {
        if (!controller.signal.aborted)
          setArtifactError((cause as Error).message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setArtifactLoading(false);
      });
    return () => controller.abort();
  }, [current.status, mission.id, token, artifactIds]);
  async function copyArtifact(artifact: Artifact) {
    try {
      await navigator.clipboard.writeText(
        artifact.content.text ??
          (artifact.content.suggestions ?? []).join("\n"),
      );
      setCopyMessage("Copied to clipboard.");
    } catch {
      setCopyMessage(
        "Clipboard access failed. Select the draft text to copy it manually.",
      );
    }
  }
  const job = run?.steps.find((step) => step.name === "extracting")?.output as
    Job | undefined;
  const matched = run?.steps.find((step) => step.name === "matching")
    ?.output as { profile?: Profile } | undefined;
  async function act(action: "start" | "cancel" | "retry") {
    setBusy(true);
    setError("");
    try {
      if (action === "start" && mode !== "none")
        await request(`/v1/missions/${mission.id}/simulate-failure`, token, {
          method: "POST",
          body: JSON.stringify({ mode }),
        });
      await request(`/v1/missions/${mission.id}/${action}`, token, {
        method: "POST",
      });
      setRevision((value) => value + 1);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function evidenceFor(match: Match) {
    return (
      matched?.profile?.evidence.filter((evidence) =>
        match.evidence_ids.includes(evidence.id),
      ) ?? []
    );
  }
  return (
    <>
      <button className="back" onClick={onBack}>
        Back to missions
      </button>
      {(error || streamError) && (
        <div role="alert" className="error">
          {error || streamError}
        </div>
      )}
      <section className="panel">
        <div className="panel-title">
          <h2>{current.goal}</h2>
          <span className={`tag status-${current.status}`}>
            {current.status}
          </span>
        </div>
        <p className="muted break">{current.job_url}</p>
        <div className="notice">
          Synthetic fixture analysis. This run uses saved sample data and
          deterministic skill matching. It does not browse the web, call a
          model, or submit applications. Generated application drafts require
          your review.
        </div>
        <div className="run-controls">
          {current.status === "draft" && (
            <>
              <label htmlFor="failure-mode">
                Failure simulation
                <select
                  id="failure-mode"
                  value={mode}
                  onChange={(e) => setMode(e.target.value)}
                  disabled={busy}
                >
                  <option value="none">None</option>
                  <option value="transient">Fail once, then recover</option>
                  <option value="exhausted">
                    Exhaust retries, then retry manually
                  </option>
                </select>
              </label>
              <button
                className="primary"
                onClick={() => act("start")}
                disabled={busy || !run}
              >
                Start sample run
              </button>
            </>
          )}
          {current.status === "failed" && (
            <button
              className="primary"
              onClick={() => act("retry")}
              disabled={busy}
            >
              Retry from checkpoint
            </button>
          )}
          {!terminal && (
            <button
              className="secondary"
              onClick={() => act("cancel")}
              disabled={busy}
            >
              Cancel mission
            </button>
          )}
          <small aria-live="polite">
            {connection} / Run {run?.run_number ?? 0}
          </small>
        </div>
        {current.status === "queued" && (
          <p className="muted">
            Waiting for the workflow worker. Your start request is durably
            queued, including if Temporal is temporarily unavailable.
          </p>
        )}
        <div className="workflow">
          {Object.entries(labels).map(([name, label], index) => {
            const step = run?.steps.find((value) => value.name === name);
            return (
              <div
                className={`step step-${step?.status || "pending"}`}
                key={name}
              >
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{label}</strong>
                <small>
                  {step?.status ?? "Not started"}
                  {step?.attempt ? ` / Attempt ${step.attempt}` : ""}
                </small>
              </div>
            );
          })}
        </div>
      </section>
      {run?.result && (
        <section className="panel report">
          <div className="panel-title">
            <h2>Sample fit report</h2>
            <strong className="score">
              {run.result.score}
              <small>out of 100</small>
            </strong>
          </div>
          <p className="muted">
            Eligibility: {run.result.eligibility}. Skill fit does not establish
            work authorization or other missing constraints.
          </p>
          {(run.result.eligibility_checks?.length ?? 0) > 0 && (
            <div className="eligibility-grid">
              {(run.result.eligibility_checks ?? []).map((check) => (
                <div
                  key={check.check}
                  className={`eligibility-card eligibility-${check.status}`}
                >
                  <span className="eligibility-icon">
                    {check.status === "pass"
                      ? "✓"
                      : check.status === "fail"
                        ? "✗"
                        : "?"}
                  </span>
                  <div>
                    <strong>{check.check.replace(/_/g, " ")}</strong>
                    <p>{check.detail}</p>
                    {check.candidate_value && (
                      <small>Candidate: {check.candidate_value}</small>
                    )}
                    {check.required_value && (
                      <small>Requirement: {check.required_value}</small>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          <div className="match-list">
            {run.result.matches.map((match) => (
              <article className="evidence" key={match.requirement_id}>
                <div className="panel-title">
                  <strong>
                    {job?.requirements.find(
                      (requirement) => requirement.id === match.requirement_id,
                    )?.text ?? match.requirement_id}
                  </strong>
                  <span className="tag">{match.status}</span>
                </div>
                <p>{match.explanation}</p>
                {evidenceFor(match).map((evidence) => (
                  <blockquote key={evidence.id}>
                    {evidence.text}
                    <small>
                      {evidence.document_id} / {evidence.source_location} /{" "}
                      {evidence.id}
                    </small>
                  </blockquote>
                ))}
              </article>
            ))}
          </div>
          <details>
            <summary>Job sources and scoring rubric</summary>
            <p className="muted">
              Required skills weigh 2; preferred skills weigh 1. An exact skill
              match supported by candidate evidence receives full weight.
              Missing evidence receives zero. The score is the supported weight
              divided by total weight.
            </p>
            {job?.sources.map((source) => (
              <blockquote key={source.id}>
                {source.excerpt}
                <small>
                  {source.title} / {source.url} / Synthetic source
                </small>
              </blockquote>
            ))}
          </details>
        </section>
      )}
      {artifactLoading && <p role="status">Loading saved drafts...</p>}
      {artifactError && (
        <div role="alert" className="error">
          Could not load drafts: {artifactError}
        </div>
      )}
      {copyMessage && <p role="status">{copyMessage}</p>}
      {artifacts.length > 0 && (
        <section className="panel artifacts-panel">
          <div className="panel-title">
            <h2>Application Artifacts</h2>
            <span className="tag">{artifacts.length} DRAFTS</span>
          </div>
          <p className="muted">
            Drafts assembled from the stored candidate evidence and job sources.
            Review the text and citations before using them; nothing has been
            sent.
          </p>
          <div className="artifact-tabs">
            {artifacts.map((a) => (
              <button
                key={a.id}
                className={`artifact-tab${artifactTab === a.id ? " active" : ""}`}
                onClick={() => {
                  setArtifactTab(a.id);
                  setCopyMessage("");
                }}
                aria-pressed={artifactTab === a.id}
              >
                {ARTIFACT_LABELS[a.type] ?? a.type}
              </button>
            ))}
          </div>
          {artifacts.map((a) =>
            a.id === artifactTab ? (
              <div key={a.id} className="artifact-body">
                <div className="artifact-meta">
                  <span className="tag">
                    v{a.version} · {a.status}
                  </span>
                  <button className="copy-btn" onClick={() => copyArtifact(a)}>
                    Copy
                  </button>
                </div>
                {a.type === "resume_suggestions" ? (
                  <ol className="suggestions-list">
                    {(a.content.suggestions ?? []).map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ol>
                ) : (
                  <pre className="artifact-text">{a.content.text ?? ""}</pre>
                )}
                <details className="artifact-citations">
                  <summary>
                    Source citations ({a.content.citations?.length ?? 0})
                  </summary>
                  {(a.content.citations ?? []).map((citation) => (
                    <blockquote
                      key={`${citation.kind}-${citation.reference_id}`}
                    >
                      {citation.excerpt}
                      <small>
                        {citation.kind} / {citation.reference_id}
                      </small>
                      {citation.document_id && (
                        <small>
                          {citation.document_id} / {citation.source_location}
                        </small>
                      )}
                      {citation.url && (
                        <small className="break">{citation.url}</small>
                      )}
                      <small>
                        Requirements:{" "}
                        {citation.requirement_ids?.join(", ") || "Job context"}
                      </small>
                    </blockquote>
                  ))}
                </details>
              </div>
            ) : null,
          )}
        </section>
      )}
      <div className="two-col run-details">
        <section className="panel">
          <h2>Step outputs</h2>
          {run?.steps.length ? (
            run.steps.map((step) => (
              <details className="step-output" key={step.id}>
                <summary>
                  {labels[step.name]}{" "}
                  <span className="subtle">
                    {step.status} / {step.latency_ms ?? "--"} ms
                  </span>
                </summary>
                <small>Attempts: {step.attempt}</small>
                {step.error && <p className="error">{step.error}</p>}
                <pre>
                  {step.output
                    ? JSON.stringify(step.output, null, 2)
                    : "No output recorded yet."}
                </pre>
              </details>
            ))
          ) : (
            <p className="muted">
              Start the mission to create its execution steps.
            </p>
          )}
        </section>
        <section className="panel">
          <h2>Run details</h2>
          <dl>
            <dt>Mission ID</dt>
            <dd>{mission.id}</dd>
            <dt>Budget cap</dt>
            <dd>${current.budget_usd.toFixed(2)}</dd>
            <dt>Model calls / spend</dt>
            <dd>0 / $0.00 - fixture activities only</dd>
            <dt>Activity latency</dt>
            <dd>
              {run?.steps.reduce(
                (total, step) => total + (step.latency_ms ?? 0),
                0,
              ) ?? 0}{" "}
              ms recorded for successful step attempts
            </dd>
            <dt>Application artifacts</dt>
            <dd>{artifacts.length} saved drafts requiring review</dd>
          </dl>
        </section>
      </div>
      <section className="panel">
        <div className="panel-title">
          <h2>Recorded events</h2>
          <span className="subtle">{events.length} EVENTS</span>
        </div>
        {events.map((event) => (
          <details className="event event-detail" key={event.id}>
            <summary>
              #{event.sequence} {event.type}
              <small>{new Date(event.created_at).toLocaleString()}</small>
            </summary>
            <pre>{JSON.stringify(event.payload, null, 2)}</pre>
          </details>
        ))}
      </section>
    </>
  );
}
