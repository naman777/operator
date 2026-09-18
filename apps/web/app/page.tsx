"use client";
import { useEffect, useState } from "react";
import type { components } from "@operator/contracts";
type Mission = components["schemas"]["MissionView"];
type Job = components["schemas"]["JobPosting"];
type Profile = components["schemas"]["CandidateProfile"];
type Event = components["schemas"]["EventView"];
type Screen =
  | "Mission Control"
  | "Opportunities"
  | "Candidate Profile"
  | "Approval Inbox"
  | "Evaluation Lab";
const screens: Screen[] = [
  "Mission Control",
  "Opportunities",
  "Candidate Profile",
  "Approval Inbox",
  "Evaluation Lab",
];
const steps = [
  "Plan mission",
  "Extract job",
  "Research company",
  "Match evidence",
  "Verify claims",
  "Approval",
  "Generate pack",
  "Update pipeline",
];

export default function Home() {
  const [token, setToken] = useState("");
  const [screen, setScreen] = useState<Screen>("Mission Control");
  const [missions, setMissions] = useState<Mission[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [selected, setSelected] = useState<Mission | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
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
    const [m, j, p] = await Promise.all([
      api<Mission[]>("/v1/missions", session),
      api<Job[]>("/v1/demo/jobs", session),
      api<Profile>("/v1/profile", session),
    ]);
    setMissions(m);
    setJobs(j);
    setProfile(p);
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
    setEvents([]);
    try {
      setEvents(await api<Event[]>(`/v1/missions/${mission.id}/events`, token));
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const payload = JSON.stringify({ job_url: url, goal, budget_usd: 1 });
      // Keep the key across ambiguous network failures, but never reuse it for a changed payload.
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
              <span className="nav-icon">{["▦", "◇", "◎", "▣", "⌁"][i]}</span>
              {s}
            </button>
          ))}
        </nav>
        <div className="aside-bottom">
          <span className="dot" /> Foundation build
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
                  : "Turn a promising role into a clear, informed next step."}
              </p>
            </div>
            <span className="pill">
              <span className="dot" /> Draft mode
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
              <button className="primary" disabled={busy} onClick={enter}>
                {busy ? "Opening…" : "Open guest workspace →"}
              </button>
            </div>
          ) : selected ? (
            <>
              <button className="back" onClick={() => setSelected(null)}>
                ← Back to missions
              </button>
              <div className="panel">
                <div className="panel-title">
                  <h2>{selected.goal}</h2>
                  <span className="tag">{selected.status}</span>
                </div>
                <p className="muted break">{selected.job_url}</p>
                <div className="notice">
                  Draft saved successfully. Temporal execution is not connected
                  in this build; no research or model calls have run.
                </div>
                <div className="workflow">
                  {steps.map((s, i) => (
                    <div className="step" key={s}>
                      <span>{String(i + 1).padStart(2, "0")}</span>
                      <strong>{s}</strong>
                      <small>Not started</small>
                    </div>
                  ))}
                </div>
              </div>
              <div className="two-col">
                <section className="panel">
                  <h2>Recorded events</h2>
                  {events.map((event) => (
                    <div className="event" key={event.id}>
                      <span className="dot" />
                      <div>
                        <strong>{event.type}</strong>
                        <small>
                          Sequence {event.sequence} ·{" "}
                          {new Date(event.created_at).toLocaleString()}
                        </small>
                        <pre>{JSON.stringify(event.payload, null, 2)}</pre>
                      </div>
                    </div>
                  ))}
                </section>
                <section className="panel">
                  <h2>Run details</h2>
                  <dl>
                    <dt>Mission ID</dt>
                    <dd>{selected.id}</dd>
                    <dt>Maximum budget</dt>
                    <dd>${selected.budget_usd.toFixed(2)}</dd>
                    <dt>Model usage</dt>
                    <dd>No calls recorded</dd>
                    <dt>Evidence & artifacts</dt>
                    <dd>Available after execution is implemented</dd>
                  </dl>
                </section>
              </div>
            </>
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
                  <strong className="stat-text">Coming next</strong>
                  <span>Temporal worker integration</span>
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
                      <span className="mission-icon">◇</span>
                      <span>
                        <strong>{m.goal}</strong>
                        <small>{m.job_url}</small>
                      </span>
                      <span className="tag">{m.status}</span>
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
              <div className="notice">
                These are synthetic fixtures, not real vacancies. Application
                pipeline updates are planned for the workflow milestone.
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
            <section className="panel">
              <span className="tag">SYNTHETIC PROFILE</span>
              <h2>{profile?.name}</h2>
              <p className="muted">
                Class of {profile?.graduation_year} ·{" "}
                {profile?.locations.join(" / ")}
              </p>
              <h3>Candidate evidence</h3>
              {profile?.evidence.map((e) => (
                <div className="evidence" key={e.id}>
                  <strong>{e.source_location}</strong>
                  <p>{e.text}</p>
                  <small>
                    {e.document_id} · {e.id}
                  </small>
                </div>
              ))}
            </section>
          ) : (
            <section className="panel empty">
              <span>{screen === "Approval Inbox" ? "▣" : "⌁"}</span>
              <h2>
                {screen === "Approval Inbox"
                  ? "No actions awaiting approval"
                  : "Evaluation results will live here"}
              </h2>
              <p>
                {screen === "Approval Inbox"
                  ? "Approval gates will be connected with the execution worker. This build cannot take external actions."
                  : "No evaluations have run yet. Quality, cost, and latency metrics will be shown only after measurement."}
              </p>
              <span className="tag">PLANNED MILESTONE</span>
            </section>
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
