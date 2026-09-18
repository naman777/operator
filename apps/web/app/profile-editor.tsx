"use client";
import { useEffect, useState } from "react";
import type { components } from "@operator/contracts";
import { request } from "../lib/api";
type State = components["schemas"]["ProfileState"];
export function ProfileEditor({ token }: { token: string }) {
  const [state, setState] = useState<State | null>(null);
  const [name, setName] = useState("");
  const [year, setYear] = useState(2027);
  const [locations, setLocations] = useState("");
  const [authorization, setAuthorization] = useState("");
  const [experience, setExperience] = useState("");
  const [text, setText] = useState("");
  const [documentName, setDocumentName] = useState("resume.txt");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  function populate(value: State) {
    setState(value);
    setName(value.profile.name);
    setYear(value.profile.graduation_year);
    setLocations(value.profile.locations.join(", "));
    setAuthorization((value.profile.work_authorization ?? []).join(", "));
    setExperience(
      value.profile.experience_years == null
        ? ""
        : String(value.profile.experience_years),
    );
  }
  useEffect(() => {
    const controller = new AbortController();
    request<State>("/v1/profile/state", token, { signal: controller.signal })
      .then(populate)
      .catch((cause) => {
        if (!controller.signal.aborted) setError((cause as Error).message);
      });
    return () => controller.abort();
  }, [token]);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!state) return;
    setBusy(true);
    setError("");
    setMessage("");
    const split = (value: string) =>
      value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
    try {
      populate(
        await request<State>("/v1/profile", token, {
          method: "PATCH",
          body: JSON.stringify({
            expected_version: state.version,
            profile: {
              ...state.profile,
              name,
              graduation_year: year,
              locations: split(locations),
              work_authorization: split(authorization),
              experience_years: experience === "" ? null : Number(experience),
            },
          }),
        }),
      );
      setMessage("Profile saved. Future missions will use these corrections.");
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function ingest(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await request("/v1/profile/documents", token, {
        method: "POST",
        body: JSON.stringify({ name: documentName, text }),
      });
      populate(await request<State>("/v1/profile/state", token));
      setText("");
      setMessage(
        "Source text saved with evidence references. Review the excerpts below.",
      );
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {message && (
        <div className="notice" role="status">
          {message}
        </div>
      )}
      <div className="two-col">
        <section className="panel">
          <h2>Candidate profile</h2>
          <p className="muted">
            Starts with demo data. Correct the details for your workspace.
            Evidence excerpts stay linked to their sources.
          </p>
          <form onSubmit={save}>
            <label htmlFor="profile-name">Name</label>
            <input
              id="profile-name"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <label htmlFor="profile-year">Graduation year</label>
            <input
              id="profile-year"
              type="number"
              min={1900}
              max={2200}
              required
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
            />
            <label htmlFor="profile-locations">
              Locations (comma separated)
            </label>
            <input
              id="profile-locations"
              value={locations}
              onChange={(e) => setLocations(e.target.value)}
            />
            <label htmlFor="profile-auth">
              Work authorization (comma separated)
            </label>
            <input
              id="profile-auth"
              value={authorization}
              onChange={(e) => setAuthorization(e.target.value)}
            />
            <label htmlFor="profile-experience">
              Experience in years (blank if unknown)
            </label>
            <input
              id="profile-experience"
              type="number"
              min={0}
              step="0.1"
              value={experience}
              onChange={(e) => setExperience(e.target.value)}
            />
            <button className="primary full" disabled={busy || !state}>
              Save corrections
            </button>
          </form>
        </section>
        <section className="panel">
          <h2>Add resume evidence</h2>
          <p className="muted">
            Paste plain text from your resume or project description. Each line
            is preserved as source evidence. PDF and DOCX uploads and automatic
            education parsing are still pending.
          </p>
          <form onSubmit={ingest}>
            <label htmlFor="document-name">Source name</label>
            <input
              id="document-name"
              required
              maxLength={200}
              value={documentName}
              onChange={(e) => setDocumentName(e.target.value)}
            />
            <label htmlFor="resume-text">Resume or project text</label>
            <textarea
              id="resume-text"
              required
              minLength={10}
              maxLength={100000}
              rows={12}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <button className="primary full" disabled={busy || !state}>
              Add evidence
            </button>
          </form>
        </section>
      </div>
      <section className="panel">
        <h2>Stored evidence</h2>
        <small>Profile version {state?.version ?? "--"}</small>
        {state?.profile.evidence.map((evidence) => (
          <article className="evidence" key={evidence.id}>
            <strong>{evidence.source_location}</strong>
            <p>{evidence.text}</p>
            <small>
              {evidence.document_id} / {evidence.id}
            </small>
            <small>
              Detected skills: {evidence.skills.join(", ") || "None"}
            </small>
          </article>
        ))}
      </section>
    </>
  );
}
