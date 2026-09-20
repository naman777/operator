"use client";
import { useEffect, useState } from "react";
import { RunInspector } from "./run-inspector";
import { ProfileEditor } from "./profile-editor";
import { JobImporter } from "./job-importer";
import { request } from "../lib/api";
import type { components } from "@operator/contracts";
type Mission = components["schemas"]["MissionView"];
type Job = components["schemas"]["JobPosting"];
type Profile = components["schemas"]["CandidateProfile"];
type Application = components["schemas"]["ApplicationView"];
type Approval = components["schemas"]["ApprovalView"];
type EvalRun = components["schemas"]["EvalRunView"];
type Observability = components["schemas"]["ObservabilitySummary"];
type Screen =
  | "Mission Control"
  | "Opportunities"
  | "Candidate Profile"
  | "Application Pipeline"
  | "Approval Inbox"
  | "Evaluation Lab"
  | "Operations"
  | "Project Guide";
const screens: Screen[] = [
  "Mission Control",
  "Opportunities",
  "Candidate Profile",
  "Application Pipeline",
  "Approval Inbox",
  "Evaluation Lab",
  "Operations",
  "Project Guide",
];
const screenIcons = ["▦", "◇", "◎", "▤", "▣", "⌁", "i"];

const STAGE_ORDER = ["saved", "applied", "interview", "offer", "rejected"];
const STAGE_LABELS: Record<string, string> = {
  saved: "Saved",
  applied: "Applied",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
};

const STATUS_RUNNING = new Set([
  "queued",
  "planning",
  "extracting",
  "matching",
  "verifying",
  "generating",
]);

export default function Home() {
  const [token, setToken] = useState("");
  const [screen, setScreen] = useState<Screen>("Mission Control");
  const [missions, setMissions] = useState<Mission[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [applications, setApplications] = useState<Application[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [evalRuns, setEvalRuns] = useState<EvalRun[]>([]);
  const [observability, setObservability] = useState<Observability | null>(
    null,
  );
  const [evalBusy, setEvalBusy] = useState(false);
  const [editingApproval, setEditingApproval] = useState("");
  const [proposalDraft, setProposalDraft] = useState("");
  const [selected, setSelected] = useState<Mission | null>(null);
  const [url, setUrl] = useState("");
  const [goal, setGoal] = useState(
    "Assess fit and prepare an evidence-backed application pack",
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);

  async function api<T>(
    path: string,
    session: string,
    options: RequestInit = {},
  ): Promise<T> {
    const response = await fetch(`/api${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session}`,
        ...options.headers,
      },
    });
    if (!response.ok) {
      if (response.status === 401) {
        localStorage.removeItem("operator-session");
        setToken("");
      }
      throw new Error(
        response.status === 401
          ? "Session expired. Open a new guest workspace."
          : `Request failed (${response.status}). Check that the API is running and try again.`,
      );
    }
    return response.json();
  }
  async function load(session: string) {
    const [m, j, p, apps, apv, evals, operations] = await Promise.all([
      api<Mission[]>("/v1/missions", session),
      api<Job[]>("/v1/demo/jobs", session),
      api<Profile>("/v1/profile", session),
      api<Application[]>("/v1/applications", session),
      api<Approval[]>("/v1/approvals", session),
      api<EvalRun[]>("/v1/evals/runs", session),
      api<Observability>("/v1/observability/summary", session),
    ]);
    setMissions(m);
    setJobs(j);
    setProfile(p);
    setApplications(apps);
    setApprovals(apv);
    setEvalRuns(evals);
    setObservability(operations);
  }
  useEffect(() => {
    const saved = localStorage.getItem("operator-session");
    if (saved) {
      setToken(saved);
      load(saved)
        .catch((e) => setError(e.message))
        .finally(() => setReady(true));
    } else setReady(true);
    // Initial session restoration only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (!token || selected) return;
    const controller = new AbortController();
    const timer = setInterval(() => {
      Promise.all([
        request<Mission[]>("/v1/missions", token, {
          signal: controller.signal,
        }),
        request<Application[]>("/v1/applications", token, {
          signal: controller.signal,
        }),
        request<Approval[]>("/v1/approvals", token, {
          signal: controller.signal,
        }),
      ])
        .then(([m, apps, apv]) => {
          if (!controller.signal.aborted) {
            setMissions(m);
            setApplications(apps);
            setApprovals(apv);
          }
        })
        .catch(() => {});
    }, 3000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [token, selected]);
  async function enter() {
    setBusy(true);
    setError("");
    try {
      const data = await api<components["schemas"]["GuestSession"]>(
        "/v1/guest-sessions",
        "",
        { method: "POST" },
      );
      localStorage.setItem("operator-session", data.token);
      setToken(data.token);
      await load(data.token);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function inspect(mission: Mission) {
    setError("");
    setSelected(mission);
  }
  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const payload = JSON.stringify({ job_url: url, goal, budget_usd: 1 });
      const pending = JSON.parse(
        sessionStorage.getItem("operator-pending-mission") || "null",
      ) as { payload: string; key: string } | null;
      const key =
        pending?.payload === payload ? pending.key : crypto.randomUUID();
      sessionStorage.setItem(
        "operator-pending-mission",
        JSON.stringify({ payload, key }),
      );
      const mission = await api<Mission>("/v1/missions", token, {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: payload,
      });
      sessionStorage.removeItem("operator-pending-mission");
      await load(token);
      await inspect(mission);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function moveStage(appId: string, stage: string) {
    try {
      await api<Application>(`/v1/applications/${appId}`, token, {
        method: "PATCH",
        body: JSON.stringify({ stage }),
      });
      const updated = await api<Application[]>("/v1/applications", token);
      setApplications(updated);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function resolveApproval(
    approvalId: string,
    action: "approve" | "reject",
  ) {
    try {
      await api<Approval>(`/v1/approvals/${approvalId}/${action}`, token, {
        method: "POST",
        body: JSON.stringify({}),
      });
      const updated = await api<Approval[]>("/v1/approvals", token);
      setApprovals(updated);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function saveApprovalProposal(approvalId: string) {
    try {
      const proposed_payload = JSON.parse(proposalDraft) as Record<
        string,
        unknown
      >;
      await api<Approval>(`/v1/approvals/${approvalId}/proposal`, token, {
        method: "PATCH",
        body: JSON.stringify({ proposed_payload }),
      });
      setApprovals(await api<Approval[]>("/v1/approvals", token));
      setEditingApproval("");
    } catch (e) {
      setError(
        e instanceof SyntaxError
          ? "Proposal must be valid JSON."
          : (e as Error).message,
      );
    }
  }
  async function runEvaluation() {
    setEvalBusy(true);
    setError("");
    try {
      const run = await api<EvalRun>("/v1/evals/runs", token, {
        method: "POST",
        body: JSON.stringify({ dataset_version: "opportunity-v3" }),
      });
      setEvalRuns((current) => [run, ...current]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setEvalBusy(false);
    }
  }
  const pendingApprovals = approvals.filter(
    (a) => a.status === "pending",
  ).length;
  return (
    <div className="app">
      <aside>
        <a className="brand" href="/">
          ◈{" "}
          <span>
            operator<span className="brand-dot">.</span>
          </span>
        </a>
        <div className="workspace">
          <span className="avatar">G</span>
          <div>
            Guest workspace<small>Synthetic data · Private session</small>
          </div>
        </div>
        <p className="nav-label">WORKSPACE</p>
        <nav>
          {screens.map((s, i) => (
            <button
              key={s}
              className={screen === s ? "active" : ""}
              onClick={() => {
                setScreen(s);
                setSelected(null);
              }}
            >
              <span className="nav-icon">{screenIcons[i] || "i"}</span>
              {s}
              {s === "Approval Inbox" && pendingApprovals > 0 && (
                <span className="nav-badge">{pendingApprovals}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="aside-bottom">
          <span className="dot" /> Workflow preview
          <small>v0.1 · Local development</small>
        </div>
      </aside>
      <main>
        <header>
          <span>
            Workspace <span className="slash">/</span>{" "}
            {selected ? "Run Inspector" : screen}
          </span>
          <span className="tag">GUEST DEMO</span>
        </header>
        <div className="content">
          <div className="heading">
            <div>
              <p className="eyebrow">YOUR NEXT OPPORTUNITY, WITH EVIDENCE</p>
              <h1>{selected ? "Run Inspector" : screen}</h1>
              <p className="muted">
                {selected
                  ? "Every recorded event, in one place."
                  : screen === "Application Pipeline"
                    ? "Track every role from saved to offer."
                    : screen === "Approval Inbox"
                      ? "Review and approve pending agent actions."
                      : screen === "Project Guide"
                        ? "Architecture, safety boundaries, and the fastest path through the demo."
                        : "Turn a promising role into a clear, informed next step."}
              </p>
            </div>
            <span className="pill">
              <span className="dot" /> Sample execution
            </span>
          </div>
          {error && (
            <div role="alert" className="error">
              {error}
            </div>
          )}
          {!ready ? (
            <div className="panel empty">Restoring workspace…</div>
          ) : !token ? (
            <div className="welcome panel">
              <span className="hero-icon">◈</span>
              <h2>
                A little more clarity.
                <br />A better next move.
              </h2>
              <p>
                Explore a synthetic candidate and three sample roles. Save a
                mission and inspect its audit trail, without connecting any
                private accounts.
              </p>
              <div className="demo-steps" aria-label="Guided demo steps">
                <div>
                  <span>1</span>
                  <strong>Open a private guest workspace</strong>
                  <small>No signup or external account is required.</small>
                </div>
                <div>
                  <span>2</span>
                  <strong>Run a seeded opportunity mission</strong>
                  <small>
                    Watch durable research, matching, and verification.
                  </small>
                </div>
                <div>
                  <span>3</span>
                  <strong>Inspect evidence and approvals</strong>
                  <small>Every claim stays linked to a stored source.</small>
                </div>
              </div>
              <button className="primary" disabled={busy} onClick={enter}>
                {busy ? "Opening…" : "Start guided demo →"}
              </button>
            </div>
          ) : selected ? (
            <RunInspector
              key={selected.id}
              mission={selected}
              token={token}
              onBack={() => {
                setSelected(null);
                load(token).catch((e) => setError(e.message));
              }}
            />
          ) : screen === "Mission Control" ? (
            <>
              <div className="stats">
                <div>
                  <small>SAVED MISSIONS</small>
                  <strong>{missions.length.toString().padStart(2, "0")}</strong>
                  <span>Persisted in your workspace</span>
                </div>
                <div>
                  <small>SAMPLE OPPORTUNITIES</small>
                  <strong>03</strong>
                  <span>Ready to explore</span>
                </div>
                <div>
                  <small>EXECUTION STATUS</small>
                  <strong className="stat-text">Temporal</strong>
                  <span>Durable sample workflow</span>
                </div>
              </div>
              <div className="two-col">
                <section className="panel">
                  <div className="panel-title">
                    <h2>Start with an opportunity</h2>
                    <span className="subtle">01 / CREATE A DRAFT</span>
                  </div>
                  <p className="muted">
                    Choose a sample, or save a public job URL for a future run.
                  </p>
                  <form onSubmit={create}>
                    <label htmlFor="job">Job URL</label>
                    <input
                      id="job"
                      type="url"
                      required
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                      placeholder="https://company.com/careers/role"
                    />
                    <div className="samples">
                      {jobs.map((j) => (
                        <button
                          type="button"
                          key={j.id}
                          onClick={() => setUrl(j.url)}
                        >
                          {j.company} ↗
                        </button>
                      ))}
                    </div>
                    <label htmlFor="goal">Mission goal</label>
                    <textarea
                      id="goal"
                      required
                      minLength={10}
                      maxLength={2000}
                      value={goal}
                      onChange={(e) => setGoal(e.target.value)}
                    />
                    <div className="form-footer">
                      <small>$1.00 budget cap · No spend in draft mode</small>
                      <button className="primary" disabled={busy}>
                        {busy ? "Saving…" : "Save mission →"}
                      </button>
                    </div>
                  </form>
                </section>
                <section className="panel accent">
                  <p className="eyebrow">BUILT AROUND PROOF</p>
                  <h2>
                    Know why.
                    <br />
                    Then decide.
                  </h2>
                  <p>
                    Operator is being built to connect every recommendation to
                    its source, and keep you in control of the next action.
                  </p>
                  <div className="principle">
                    01 <span>Evidence before conclusions</span>
                  </div>
                  <div className="principle">
                    02 <span>Transparent execution</span>
                  </div>
                  <div className="principle">
                    03 <span>Approval before action</span>
                  </div>
                </section>
              </div>
              <section className="panel">
                <div className="panel-title">
                  <h2>Your missions</h2>
                  <span className="subtle">{missions.length} TOTAL</span>
                </div>
                {missions.length ? (
                  missions.map((m) => (
                    <button
                      className="mission-row"
                      key={m.id}
                      onClick={() => inspect(m)}
                    >
                      <span className="mission-icon">
                        {STATUS_RUNNING.has(m.status) ? (
                          <span className="pulse-dot" />
                        ) : (
                          "◇"
                        )}
                      </span>
                      <span>
                        <strong>{m.goal}</strong>
                        <small>{m.job_url}</small>
                      </span>
                      <span className={`tag status-${m.status}`}>
                        {m.status}
                      </span>
                      <span>◇</span>
                    </button>
                  ))
                ) : (
                  <div className="empty">
                    <span>◇</span>
                    <h3>Your first mission starts here</h3>
                    <p>
                      Save a role above to create a persistent mission and its
                      first event.
                    </p>
                  </div>
                )}
              </section>
            </>
          ) : screen === "Opportunities" ? (
            <>
              <JobImporter
                token={token}
                onSelect={(value) => {
                  setUrl(value);
                  setScreen("Mission Control");
                }}
              />
              <div className="notice">
                These are synthetic fixtures, not real vacancies. Completed
                analyses create a saved pipeline entry.
              </div>
              <div className="job-grid">
                {jobs.map((j) => (
                  <section className="panel" key={j.id}>
                    <span className="avatar">{j.company[0]}</span>
                    <p className="eyebrow">{j.company}</p>
                    <h2>{j.title}</h2>
                    <p className="muted">{j.location}</p>
                    <div className="samples">
                      {j.requirements.map((r) => (
                        <span className="tag" key={r.id}>
                          {r.text}
                        </span>
                      ))}
                    </div>
                    <blockquote>{j.sources[0]?.excerpt}</blockquote>
                    <small>Source: {j.sources[0]?.title}</small>
                    <button
                      className="primary full"
                      onClick={() => {
                        setUrl(j.url);
                        setScreen("Mission Control");
                      }}
                    >
                      Use this sample →
                    </button>
                  </section>
                ))}
              </div>
            </>
          ) : screen === "Candidate Profile" ? (
            <ProfileEditor token={token} />
          ) : screen === "Application Pipeline" ? (
            <>
              <div className="stats">
                <div>
                  <small>TOTAL APPLICATIONS</small>
                  <strong>
                    {applications.length.toString().padStart(2, "0")}
                  </strong>
                  <span>Across all stages</span>
                </div>
                <div>
                  <small>ACTIVE STAGE</small>
                  <strong className="stat-text">
                    {applications.filter(
                      (a) => a.stage === "applied" || a.stage === "interview",
                    ).length > 0
                      ? "In Progress"
                      : "Saved"}
                  </strong>
                  <span>Most advanced stage</span>
                </div>
                <div>
                  <small>OFFERS</small>
                  <strong>
                    {applications
                      .filter((a) => a.stage === "offer")
                      .length.toString()
                      .padStart(2, "0")}
                  </strong>
                  <span>Received</span>
                </div>
              </div>
              {applications.length === 0 ? (
                <div className="panel empty">
                  <span>▤</span>
                  <h3>No applications yet</h3>
                  <p>
                    Complete a mission to automatically add an application to
                    the pipeline. Start and run a mission from Mission Control
                    to see it appear here.
                  </p>
                  <button
                    className="primary"
                    onClick={() => setScreen("Mission Control")}
                  >
                    Go to Mission Control →
                  </button>
                </div>
              ) : (
                <div className="pipeline-grid">
                  {applications.map((app) => (
                    <section className="panel pipeline-card" key={app.id}>
                      <div className="panel-title">
                        <div>
                          <span className="avatar">
                            {(app.company ?? "?")[0]}
                          </span>
                        </div>
                        <span className={`tag pipeline-stage-${app.stage}`}>
                          {STAGE_LABELS[app.stage] ?? app.stage}
                        </span>
                      </div>
                      <p className="eyebrow" style={{ marginTop: 14 }}>
                        {app.company ?? "Unknown company"}
                      </p>
                      <h2 style={{ fontSize: 15 }}>
                        {app.title ?? "Unknown role"}
                      </h2>
                      {app.fit_score !== null &&
                        app.fit_score !== undefined && (
                          <p className="muted" style={{ fontSize: 12 }}>
                            Fit score:{" "}
                            <strong style={{ color: "var(--green)" }}>
                              {app.fit_score}
                            </strong>{" "}
                            / 100
                          </p>
                        )}
                      <p className="muted break" style={{ fontSize: 11 }}>
                        {app.job_url}
                      </p>
                      <div className="stage-controls">
                        {STAGE_ORDER.filter((s) => s !== app.stage).map((s) => (
                          <button
                            key={s}
                            className="stage-btn"
                            onClick={() => moveStage(app.id, s)}
                          >
                            → {STAGE_LABELS[s]}
                          </button>
                        ))}
                      </div>
                    </section>
                  ))}
                </div>
              )}
            </>
          ) : screen === "Approval Inbox" ? (
            <>
              {approvals.length === 0 ? (
                <section className="panel empty">
                  <span>▣</span>
                  <h2>No pending approvals</h2>
                  <p>
                    Approval gates will be triggered by agent actions that
                    require human confirmation before proceeding. Run a mission
                    with an approval step to see requests here.
                  </p>
                  <span className="tag">WORKSPACE SCOPED</span>
                </section>
              ) : (
                <div className="approval-list">
                  {approvals.map((approval) => (
                    <section className="panel" key={approval.id}>
                      <div className="panel-title">
                        <div>
                          <span className="tag">{approval.action_type}</span>{" "}
                          <span className="tag">
                            {approval.risk_level} risk
                          </span>{" "}
                          <strong style={{ fontSize: 13, marginLeft: 10 }}>
                            Mission {approval.mission_id.slice(0, 8)}…
                          </strong>
                        </div>
                        <span className={`tag status-${approval.status}`}>
                          {approval.status}
                        </span>
                      </div>
                      <p
                        className="muted"
                        style={{ fontSize: 12, marginTop: 12 }}
                      >
                        Created {new Date(approval.created_at).toLocaleString()}
                      </p>
                      {editingApproval === approval.id ? (
                        <div style={{ marginTop: 14 }}>
                          <textarea
                            value={proposalDraft}
                            onChange={(event) =>
                              setProposalDraft(event.target.value)
                            }
                            rows={10}
                            aria-label="Editable approval proposal JSON"
                          />
                        </div>
                      ) : (
                        <details style={{ marginTop: 14 }}>
                          <summary>Proposed payload</summary>
                          <pre>
                            {JSON.stringify(approval.proposed_payload, null, 2)}
                          </pre>
                        </details>
                      )}
                      {approval.status === "pending" && (
                        <div className="approval-actions">
                          {approval.action_type === "email_draft" ||
                          approval.action_type === "calendar_event" ? (
                            editingApproval === approval.id ? (
                              <>
                                <button
                                  className="secondary"
                                  onClick={() =>
                                    saveApprovalProposal(approval.id)
                                  }
                                >
                                  Save proposal
                                </button>
                                <button
                                  className="secondary"
                                  onClick={() => setEditingApproval("")}
                                >
                                  Cancel edit
                                </button>
                              </>
                            ) : (
                              <button
                                className="secondary"
                                onClick={() => {
                                  setEditingApproval(approval.id);
                                  setProposalDraft(
                                    JSON.stringify(
                                      approval.proposed_payload,
                                      null,
                                      2,
                                    ),
                                  );
                                }}
                              >
                                Edit proposal
                              </button>
                            )
                          ) : null}
                          <button
                            className="primary"
                            onClick={() =>
                              resolveApproval(approval.id, "approve")
                            }
                          >
                            Approve
                          </button>
                          <button
                            className="secondary"
                            onClick={() =>
                              resolveApproval(approval.id, "reject")
                            }
                          >
                            Reject
                          </button>
                        </div>
                      )}
                    </section>
                  ))}
                </div>
              )}
            </>
          ) : screen === "Operations" ? (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">DURABLE WORKFLOW TELEMETRY</p>
                  <h1>Operations</h1>
                  <p className="muted">
                    Workspace-scoped outcomes, costs, step reliability, and
                    eight-week mission cohorts from persisted records.
                  </p>
                </div>
                <button
                  className="secondary"
                  onClick={() => load(token).catch((e) => setError(e.message))}
                >
                  Refresh metrics
                </button>
              </div>
              {!observability ? (
                <section className="panel empty">Loading metrics…</section>
              ) : (
                <>
                  <section className="panel">
                    <div className="stats eval-stats">
                      <div>
                        <small>MISSIONS</small>
                        <strong>{observability.mission_count}</strong>
                        <span>{observability.active_count} active</span>
                      </div>
                      <div>
                        <small>SUCCESS RATE</small>
                        <strong>
                          {observability.success_rate == null
                            ? "—"
                            : `${(observability.success_rate * 100).toFixed(0)}%`}
                        </strong>
                        <span>
                          {observability.completed_count} completed /{" "}
                          {observability.failed_count} failed
                        </span>
                      </div>
                      <div>
                        <small>MODEL COST</small>
                        <strong>
                          ${observability.total_model_cost_usd.toFixed(4)}
                        </strong>
                        <span>recorded provider usage</span>
                      </div>
                      <div>
                        <small>COST / SUCCESS</small>
                        <strong>
                          {observability.cost_per_completed_mission_usd == null
                            ? "—"
                            : `$${observability.cost_per_completed_mission_usd.toFixed(4)}`}
                        </strong>
                        <span>per completed mission</span>
                      </div>
                    </div>
                  </section>
                  <div className="two-col" style={{ marginTop: 20 }}>
                    <section className="panel">
                      <h2>Workflow steps</h2>
                      <div className="eval-cases">
                        {observability.step_metrics.length === 0 ? (
                          <p className="muted">
                            No workflow steps recorded yet.
                          </p>
                        ) : (
                          observability.step_metrics.map((item) => (
                            <p key={item.name} className="muted">
                              <strong>{item.name}</strong> · {item.completed}/
                              {item.attempted} completed · success{" "}
                              {item.success_rate == null
                                ? "—"
                                : `${(item.success_rate * 100).toFixed(0)}%`}
                              {item.p95_latency_ms == null
                                ? ""
                                : ` · P50 ${item.p50_latency_ms?.toFixed(0)} ms / P95 ${item.p95_latency_ms.toFixed(0)} ms`}
                            </p>
                          ))
                        )}
                      </div>
                    </section>
                    <section className="panel">
                      <h2>Tools and connectors</h2>
                      <div className="eval-cases">
                        {observability.tool_metrics.length === 0 ? (
                          <p className="muted">No tool calls recorded yet.</p>
                        ) : (
                          observability.tool_metrics.map((item) => (
                            <p key={item.name} className="muted">
                              <strong>{item.name}</strong> · {item.succeeded}/
                              {item.attempted} succeeded ·{" "}
                              {(item.success_rate * 100).toFixed(0)}%
                            </p>
                          ))
                        )}
                      </div>
                    </section>
                  </div>
                  <section className="panel">
                    <h2>Eight-week mission trend</h2>
                    <div className="eval-cases">
                      {observability.weekly_trend.map((item) => (
                        <p key={item.week_start} className="muted">
                          <strong>{item.week_start}</strong> · {item.created}{" "}
                          created · {item.completed} completed · {item.failed}{" "}
                          failed · {item.cancelled} cancelled
                        </p>
                      ))}
                    </div>
                  </section>
                </>
              )}
            </>
          ) : screen === "Project Guide" ? (
            <>
              <section className="panel guide-hero">
                <div>
                  <p className="eyebrow">RECRUITER DEMO PATH</p>
                  <h2>See the complete decision trail in three steps.</h2>
                  <p className="muted">
                    The demo uses synthetic candidate data and local mock
                    actions. It does not submit applications, send email, or
                    modify an external calendar.
                  </p>
                </div>
                <button
                  className="primary"
                  onClick={() => setScreen("Mission Control")}
                >
                  Start a mission →
                </button>
              </section>
              <div className="guide-grid">
                <section className="panel">
                  <p className="eyebrow">01 / INPUT</p>
                  <h2>Choose a role</h2>
                  <p className="muted">
                    Select a seeded role or import a supported public HTTPS job
                    page. Its saved snapshot becomes immutable source evidence
                    for the mission.
                  </p>
                  <button
                    className="secondary"
                    onClick={() => setScreen("Opportunities")}
                  >
                    Open opportunities
                  </button>
                </section>
                <section className="panel">
                  <p className="eyebrow">02 / EXECUTION</p>
                  <h2>Inspect the workflow</h2>
                  <p className="muted">
                    Temporal checkpoints planning, extraction, company research,
                    matching, verification, and artifact generation. Refreshes
                    and retries reconstruct stored state.
                  </p>
                </section>
                <section className="panel">
                  <p className="eyebrow">03 / DECISION</p>
                  <h2>Review before action</h2>
                  <p className="muted">
                    Fit scores are reproducible, drafts retain citations, and
                    connector proposals wait for explicit approval. Current
                    connectors remain local mocks.
                  </p>
                  <button
                    className="secondary"
                    onClick={() => setScreen("Approval Inbox")}
                  >
                    Open approvals
                  </button>
                </section>
              </div>
              <section className="panel architecture-panel">
                <div className="panel-title">
                  <h2>System architecture</h2>
                  <span className="tag">LOCAL MVP</span>
                </div>
                <div
                  className="architecture-flow"
                  aria-label="System architecture flow"
                >
                  <div>
                    <strong>Next.js</strong>
                    <small>Workspace UI and SSE client</small>
                  </div>
                  <span>→</span>
                  <div>
                    <strong>FastAPI</strong>
                    <small>Authorization, contracts, persistence</small>
                  </div>
                  <span>→</span>
                  <div>
                    <strong>Temporal</strong>
                    <small>Durable workflow and approvals</small>
                  </div>
                  <span>→</span>
                  <div>
                    <strong>Postgres</strong>
                    <small>Audit state and pgvector evidence</small>
                  </div>
                </div>
              </section>
              <div className="guide-grid two">
                <section className="panel">
                  <h2>Implemented safeguards</h2>
                  <ul className="check-list">
                    <li>Workspace authorization and idempotent writes</li>
                    <li>Private-network blocking and bounded extraction</li>
                    <li>
                      Exact source citations and deterministic verification
                    </li>
                    <li>Model time, token, and mission-budget limits</li>
                    <li>Human approval before connector actions</li>
                  </ul>
                </section>
                <section className="panel">
                  <h2>Current limitations</h2>
                  <ul className="check-list limitations">
                    <li>Guest sessions are local and expire after 24 hours</li>
                    <li>Email and calendar integrations are mock connectors</li>
                    <li>Full PostgreSQL and Docker verification is pending</li>
                    <li>No public deployment, production monitoring, or SLA</li>
                    <li>
                      Live model validation needs an operator-supplied key
                    </li>
                  </ul>
                </section>
              </div>
            </>
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">QUALITY REGRESSION</p>
                  <h1>Evaluation Lab</h1>
                  <p className="muted">
                    Versioned cases measure matching accuracy, score drift,
                    evidence coverage, and unsupported positive matches.
                  </p>
                </div>
                <button
                  className="primary"
                  onClick={runEvaluation}
                  disabled={evalBusy}
                >
                  {evalBusy ? "Running…" : "Run opportunity-v3"}
                </button>
              </div>
              {evalRuns.length === 0 ? (
                <section className="panel empty">
                  <h2>No measured runs yet</h2>
                  <p>
                    Run the forty-case suite to record reproducible matching,
                    eligibility, safety, provenance, and latency metrics.
                  </p>
                  <span className="tag">DATASET opportunity-v3</span>
                </section>
              ) : (
                <div className="eval-runs">
                  {evalRuns.map((run, index) => (
                    <section className="panel" key={run.id}>
                      <div className="panel-title">
                        <div>
                          <span className="tag">{run.dataset_version}</span>{" "}
                          <strong style={{ marginLeft: 10 }}>
                            {index === 0 ? "Latest run" : "Previous run"}
                          </strong>
                        </div>
                        <span className="muted">
                          {new Date(run.created_at).toLocaleString()}
                        </span>
                      </div>
                      <div className="stats eval-stats">
                        <div>
                          <small>CASE PASS RATE</small>
                          <strong>
                            {run.metrics.pass_rate == null
                              ? "Legacy"
                              : `${(run.metrics.pass_rate * 100).toFixed(0)}%`}
                          </strong>
                        </div>
                        <div>
                          <small>REQUIREMENT ACCURACY</small>
                          <strong>
                            {(run.metrics.requirement_accuracy * 100).toFixed(
                              0,
                            )}
                            %
                          </strong>
                        </div>
                        <div>
                          <small>ELIGIBILITY ACCURACY</small>
                          <strong>
                            {run.metrics.eligibility_accuracy == null
                              ? "Legacy"
                              : `${(run.metrics.eligibility_accuracy * 100).toFixed(0)}%`}
                          </strong>
                        </div>
                        <div>
                          <small>SCORE MAE</small>
                          <strong>{run.metrics.score_mae.toFixed(1)}</strong>
                        </div>
                        <div>
                          <small>CITATION COVERAGE</small>
                          <strong>
                            {(run.metrics.citation_coverage * 100).toFixed(0)}%
                          </strong>
                        </div>
                        <div>
                          <small>P50 / P95 LATENCY</small>
                          <strong>
                            {run.metrics.p50_latency_ms == null ||
                            run.metrics.p95_latency_ms == null
                              ? `${run.metrics.mean_latency_ms.toFixed(2)} ms mean`
                              : `${run.metrics.p50_latency_ms.toFixed(2)} / ${run.metrics.p95_latency_ms.toFixed(2)} ms`}
                          </strong>
                        </div>
                      </div>
                      <details style={{ marginTop: 16 }}>
                        <summary>{run.metrics.case_count} case results</summary>
                        <div className="eval-cases">
                          {run.case_results.map((item) => (
                            <p key={item.case_id} className="muted">
                              <span
                                className={`tag ${item.passed ? "status-completed" : "status-failed"}`}
                              >
                                {item.passed ? "PASS" : "FAIL"}
                              </span>{" "}
                              [{item.category}] {item.job_title}: score{" "}
                              {item.actual_score} / expected{" "}
                              {item.expected_score}
                              {item.expected_eligibility &&
                                `; eligibility ${item.actual_eligibility} / expected ${item.expected_eligibility}`}
                            </p>
                          ))}
                        </div>
                      </details>
                    </section>
                  ))}
                </div>
              )}
            </>
          )}
          <footer>
            OPERATOR{" "}
            <span>Evidence-backed decisions. Human-controlled actions.</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
