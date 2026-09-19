"use client";
import { useEffect, useRef, useState } from "react";
import type { components } from "@operator/contracts";
import { request } from "../lib/api";
type State = components["schemas"]["ProfileState"];

type UploadStatus = "idle" | "uploading" | "done" | "error";

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

  // File upload state
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>("idle");
  const [uploadMessage, setUploadMessage] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
