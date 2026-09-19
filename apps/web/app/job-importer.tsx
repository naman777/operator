"use client";
import { useEffect, useState } from "react";
import type { components } from "@operator/contracts";
import { request } from "../lib/api";
type Receipt = components["schemas"]["ImportReceipt"];
export function JobImporter({
  token,
  onSelect,
}: {
  token: string;
  onSelect: (url: string) => void;
}) {
  const [url, setUrl] = useState("");
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [importedUrl, setImportedUrl] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [screenshotUrl, setScreenshotUrl] = useState("");
  useEffect(
    () => () => {
      if (screenshotUrl) URL.revokeObjectURL(screenshotUrl);
    },
    [screenshotUrl],
  );
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    setReceipt(null);
    setScreenshotUrl("");
    try {
      const imported = await request<Receipt>(
        "/v1/opportunities/import",
        token,
        {
          method: "POST",
          body: JSON.stringify({ url }),
        },
      );
      setReceipt(imported);
      if (imported.screenshot_available) {
        const response = await fetch(
          `/api/v1/opportunities/imports/${imported.import_id}/screenshot`,
          { headers: { Authorization: `Bearer ${token}` } },
        );
        if (response.ok)
          setScreenshotUrl(URL.createObjectURL(await response.blob()));
      }
      setImportedUrl(url);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel" style={{ marginBottom: 24 }}>
      <h2>Import a public job</h2>
      <p className="muted">
        Supports HTTPS detail pages containing one structured JobPosting. Static
        HTML is preferred; JavaScript pages use a guarded browser fallback. The
        final source snapshot is saved in your workspace.
      </p>
      <form onSubmit={submit}>
        <label htmlFor="import-url">Job page URL</label>
        <input
          id="import-url"
          type="url"
          required
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <button className="primary full" disabled={busy}>
          {busy ? "Importing..." : "Import job"}
        </button>
      </form>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {receipt && (
        <div className="evidence">
          <h3>
            {receipt.posting.title} / {receipt.posting.company}
          </h3>
          <p>{receipt.posting.location || "Location not specified"}</p>
          <small>
            {receipt.posting.requirements.length} explicit requirements
            extracted. Eligibility remains unverified.
          </small>
          <blockquote>{receipt.posting.sources[0]?.excerpt}</blockquote>
          {screenshotUrl && (
            <img
              src={screenshotUrl}
              alt="Rendered job page captured during import"
              style={{ width: "100%", borderRadius: 8, marginBottom: 16 }}
            />
          )}
          <button className="primary" onClick={() => onSelect(importedUrl)}>
            Create mission for this job
          </button>
        </div>
      )}
    </section>
  );
}
