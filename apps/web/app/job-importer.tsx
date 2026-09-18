"use client";
import { useState } from "react";
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
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    setReceipt(null);
    try {
      setReceipt(
        await request<Receipt>("/v1/opportunities/import", token, {
          method: "POST",
          body: JSON.stringify({ url }),
        }),
      );
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
        Supports HTTPS detail pages containing a single structured JobPosting.
        The fetched source is saved in your workspace. JavaScript-only pages and
        unsupported formats may require a later extractor.
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
          <button className="primary" onClick={() => onSelect(importedUrl)}>
            Create mission for this job
          </button>
        </div>
      )}
    </section>
  );
}
