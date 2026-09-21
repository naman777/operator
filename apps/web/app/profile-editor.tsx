"use client";
import { useEffect, useRef, useState } from "react";
import type { components } from "@operator/contracts";
import { request } from "../lib/api";
type State = components["schemas"]["ProfileState"];
type Archive = components["schemas"]["ProfileArchiveView"];

type UploadStatus = "idle" | "uploading" | "done" | "error";

export function ProfileEditor({
  token,
  onUpdated,
}: {
  token: string;
  onUpdated?: () => void;
}) {
  const [state, setState] = useState<State | null>(null);
  const [archives, setArchives] = useState<Archive[]>([]);
  const [name, setName] = useState("");
  const [year, setYear] = useState<number | "">("");
  const [locations, setLocations] = useState("");
  const [skills, setSkills] = useState("");
  const [authorization, setAuthorization] = useState("");
  const [experience, setExperience] = useState("");
  const [availableFrom, setAvailableFrom] = useState("");
  const [availableUntil, setAvailableUntil] = useState("");
  const [employmentTypes, setEmploymentTypes] = useState("");
  const [text, setText] = useState("");
  const [documentName, setDocumentName] = useState("resume.txt");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);

  // File upload state
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>("idle");
  const [uploadMessage, setUploadMessage] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function populate(value: State) {
    setState(value);
    setName(value.profile.name);
    setYear(value.profile.graduation_year ?? "");
    setLocations(value.profile.locations.join(", "));
    setSkills(value.profile.skills.join(", "));
    setAuthorization((value.profile.work_authorization ?? []).join(", "));
    setExperience(
      value.profile.experience_years == null
        ? ""
        : String(value.profile.experience_years),
    );
    setAvailableFrom(value.profile.available_from ?? "");
    setAvailableUntil(value.profile.available_until ?? "");
    setEmploymentTypes(
      (value.profile.employment_type_preference ?? []).join(", "),
    );
  }
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      request<State>("/v1/profile/state", token, { signal: controller.signal }),
      request<Archive[]>("/v1/profile/archives", token, {
        signal: controller.signal,
      }),
    ])
      .then(([profile, savedArchives]) => {
        populate(profile);
        setArchives(savedArchives);
      })
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
              graduation_year: year === "" ? null : year,
              locations: split(locations),
              skills: split(skills),
              work_authorization: split(authorization),
              experience_years: experience === "" ? null : Number(experience),
              available_from: availableFrom || null,
              available_until: availableUntil || null,
              employment_type_preference: split(employmentTypes),
            },
          }),
        }),
      );
      setMessage("Profile saved. Future missions will use these corrections.");
      onUpdated?.();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmProfile() {
    if (!state) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const confirmed = await request<State>(
        `/v1/profile/confirm?expected_version=${state.version}`,
        token,
        { method: "POST" },
      );
      populate(confirmed);
      setMessage(
        "Profile confirmed for future missions. New edits or evidence will require another review.",
      );
      onUpdated?.();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function startFresh() {
    if (!state) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const clean = await request<State>(
        `/v1/profile/start-fresh?expected_version=${state.version}`,
        token,
        { method: "POST" },
      );
      populate(clean);
      setArchives(await request<Archive[]>("/v1/profile/archives", token));
      setMessage(
        "Your previous profile was archived. Add your own evidence to the clean profile.",
      );
      onUpdated?.();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function restoreArchive(id: string) {
    if (!state) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const restored = await request<State>(
        `/v1/profile/archives/${id}/restore?expected_version=${state.version}`,
        token,
        { method: "POST" },
      );
      populate(restored);
      setArchives(await request<Archive[]>("/v1/profile/archives", token));
      setMessage(
        "Archived profile restored. The profile it replaced was archived too.",
      );
      onUpdated?.();
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
      onUpdated?.();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function uploadFile(file: File) {
    if (uploadStatus === "uploading") return;
    const allowed = [".pdf", ".docx"];
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!allowed.includes(ext)) {
      setUploadStatus("error");
      setUploadMessage(
        `Unsupported file type "${ext}". Please upload a PDF or DOCX file.`,
      );
      return;
    }
    setUploadStatus("uploading");
    setUploadMessage(`Uploading ${file.name}\u2026`);
    const form = new FormData();
    form.append("file", file, file.name);
    try {
      const response = await fetch(`/api/v1/profile/documents/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
        cache: "no-store",
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(
          typeof body?.detail === "string"
            ? body.detail
            : `Upload failed (${response.status}).`,
        );
      }
      const receipt = await response.json();
      const newState = await request<State>("/v1/profile/state", token);
      populate(newState);
      onUpdated?.();
      setUploadStatus("done");
      setUploadMessage(
        `${file.name} uploaded \u2014 ${receipt.evidence_count} evidence chunk${receipt.evidence_count === 1 ? "" : "s"} extracted.`,
      );
    } catch (cause) {
      setUploadStatus("error");
      setUploadMessage((cause as Error).message);
    }
  }

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) uploadFile(file);
    e.target.value = "";
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) uploadFile(file);
  }

  function onDragOver(e: React.DragEvent) {
    e.preventDefault();
    setIsDragging(true);
  }

  function onDragLeave() {
    setIsDragging(false);
  }

  const uploadZoneClass = [
    "upload-zone",
    isDragging ? "upload-zone--dragging" : "",
    uploadStatus === "done" ? "upload-zone--done" : "",
    uploadStatus === "error" ? "upload-zone--error" : "",
  ]
    .filter(Boolean)
    .join(" ");

  function fieldSource(field: string) {
    const source = state?.profile.field_sources?.[field];
    if (!source && state?.profile.synthetic) return "Guided demo fixture";
    if (source === "heuristic-v1")
      return "Suggested from resume; review before confirming";
    if (source === "user-correction") return "Entered or corrected by you";
    if (source === "synthetic") return "Guided demo fixture";
    return "Not supplied or not yet classified";
  }

  async function exportWorkspace() {
    setExporting(true);
    setError("");
    try {
      const response = await fetch("/api/v1/workspace/export", {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      });
      if (!response.ok)
        throw new Error("Workspace export failed. Please try again.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "operator-workspace-export.json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setExporting(false);
    }
  }

  function fieldCitations(field: string) {
    const ids = state?.profile.field_evidence_ids?.[field] ?? [];
    if (!ids.length) return null;
    return (
      <small>
        Source excerpts:{" "}
        {ids.map((id, index) => {
          const evidence = state?.profile.evidence.find(
            (item) => item.id === id,
          );
          return evidence ? (
            <span key={id}>
              {index > 0 ? "; " : ""}
              <a href={`#evidence-${id}`}>{evidence.source_location}</a>
            </span>
          ) : null;
        })}
      </small>
    );
  }

  return (
    <>
      <section className="panel">
        <h2>Your workspace data</h2>
        <p className="muted">
          Download your saved profile, resume text, imported jobs, missions,
          drafts, approvals, and application history as JSON. This file may
          contain sensitive personal information; store it securely.
        </p>
        <button
          className="secondary"
          disabled={exporting}
          onClick={exportWorkspace}
        >
          {exporting ? "Preparing export..." : "Download workspace data"}
        </button>
      </section>
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
      {state?.profile.synthetic && (
        <section className="panel">
          <h2>Start with your own profile</h2>
          <p className="muted">
            This workspace contains synthetic candidate data. Starting fresh
            archives the current profile and keeps existing missions and drafts.
          </p>
          <button className="secondary" disabled={busy} onClick={startFresh}>
            Archive demo profile and start fresh
          </button>
        </section>
      )}
      {archives.length > 0 && (
        <section className="panel">
          <h2>Archived profiles</h2>
          <p className="muted">
            Restoring a profile archives your current one first.
          </p>
          {archives.map((archive) => (
            <div key={archive.id} className="mission-row">
              <span>
                {archive.was_demo ? "Guided demo" : "Real-data profile"} -{" "}
                {new Date(archive.created_at).toLocaleString()}
              </span>
              <button
                className="secondary"
                disabled={busy}
                onClick={() => restoreArchive(archive.id)}
              >
                Restore
              </button>
            </div>
          ))}
        </section>
      )}
      <div className="two-col">
        <section className="panel">
          <h2>Candidate profile</h2>
          <p className="muted">
            {state?.profile.synthetic
              ? "This guided demo uses a synthetic candidate. Evidence excerpts stay linked to their sources."
              : "Add your own resume evidence, then review and save your details. Missing fields stay unknown."}
          </p>
          <form onSubmit={save}>
            <label htmlFor="profile-name">Name</label>
            <input
              id="profile-name"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <small>{fieldSource("name")}</small>
            <label htmlFor="profile-year">Graduation year</label>
            <input
              id="profile-year"
              type="number"
              min={1900}
              max={2200}
              value={year}
              onChange={(e) =>
                setYear(e.target.value === "" ? "" : Number(e.target.value))
              }
            />
            <small>{fieldSource("graduation_year")}</small>
            {fieldCitations("graduation_year")}
            <label htmlFor="profile-locations">
              Locations (comma separated)
            </label>
            <input
              id="profile-locations"
              value={locations}
              onChange={(e) => setLocations(e.target.value)}
            />
            <small>{fieldSource("locations")}</small>
            <label htmlFor="profile-skills">Skills (comma separated)</label>
            <input
              id="profile-skills"
              value={skills}
              onChange={(e) => setSkills(e.target.value)}
            />
            <small>{fieldSource("skills")}</small>
            {fieldCitations("skills")}
            <label htmlFor="profile-auth">
              Work authorization (comma separated)
            </label>
            <input
              id="profile-auth"
              value={authorization}
              onChange={(e) => setAuthorization(e.target.value)}
            />
            <small>{fieldSource("work_authorization")}</small>
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
            <small>{fieldSource("experience_years")}</small>
            {fieldCitations("experience_years")}
            <label htmlFor="profile-available-from">Available from</label>
            <input
              id="profile-available-from"
              type="date"
              value={availableFrom}
              onChange={(e) => setAvailableFrom(e.target.value)}
            />
            <small>{fieldSource("available_from")}</small>
            <label htmlFor="profile-available-until">Available until</label>
            <input
              id="profile-available-until"
              type="date"
              value={availableUntil}
              onChange={(e) => setAvailableUntil(e.target.value)}
            />
            <small>{fieldSource("available_until")}</small>
            <label htmlFor="profile-employment-types">
              Employment types (comma separated)
            </label>
            <input
              id="profile-employment-types"
              value={employmentTypes}
              onChange={(e) => setEmploymentTypes(e.target.value)}
              placeholder="Full-time, internship"
            />
            <small>{fieldSource("employment_type_preference")}</small>
            <button className="primary full" disabled={busy || !state}>
              Save corrections
            </button>
          </form>
        </section>
        <section className="panel">
          <h2>Add resume evidence</h2>

          {/* File upload zone */}
          <div
            id="resume-upload-zone"
            className={uploadZoneClass}
            onDrop={onDrop}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onClick={() => fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            aria-label="Upload PDF or DOCX resume"
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ")
                fileInputRef.current?.click();
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx"
              style={{ display: "none" }}
              onChange={onFileChange}
              id="resume-file-input"
            />
            {uploadStatus === "uploading" ? (
              <span className="upload-zone__spinner" aria-live="polite">
                {uploadMessage}
              </span>
            ) : uploadStatus === "done" ? (
              <span className="upload-zone__success" aria-live="polite">
                {uploadMessage}
              </span>
            ) : uploadStatus === "error" ? (
              <span className="upload-zone__error-msg" aria-live="polite">
                {uploadMessage}
              </span>
            ) : (
              <>
                <span className="upload-zone__icon">&#128196;</span>
                <span className="upload-zone__label">
                  Drop your PDF or DOCX here
                </span>
                <span className="upload-zone__sub">
                  or click to browse &middot; max 5&thinsp;MB
                </span>
              </>
            )}
          </div>

          <p className="muted" style={{ marginTop: "1rem" }}>
            Or paste plain text from your resume or project description below.
            Each line is preserved as a source evidence excerpt.
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
          <article
            className="evidence"
            key={evidence.id}
            id={`evidence-${evidence.id}`}
          >
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
      {state && !state.profile.synthetic && (
        <section className="panel">
          <h2>Review and confirm profile</h2>
          <p className="muted">
            Check each field and the source excerpts above. Resume-derived
            values are suggestions until you confirm this profile version.
          </p>
          <p>
            {state.reviewed_version === state.version
              ? "This profile version is confirmed."
              : "This profile version still needs your confirmation before a real-data mission."}
          </p>
          <button
            className="primary"
            disabled={
              busy ||
              state.reviewed_version === state.version ||
              !state.profile.name.trim() ||
              !state.profile.evidence.length
            }
            onClick={confirmProfile}
          >
            Confirm this profile
          </button>
        </section>
      )}
    </>
  );
}
