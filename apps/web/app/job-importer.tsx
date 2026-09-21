"use client";
import { useEffect, useState } from "react";
import type { components } from "@operator/contracts";
import { request } from "../lib/api";

type Receipt = components["schemas"]["ImportReceipt"];
type Importance = "required" | "preferred";

export function JobImporter({
  token,
  demoMode,
  onSelect,
}: {
  token: string;
  demoMode: boolean;
  onSelect: (url: string) => void;
}) {
  const [url, setUrl] = useState("");
  const [imports, setImports] = useState<Receipt[]>([]);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [importance, setImportance] = useState<Record<string, Importance>>({});
  const [acceptEligibility, setAcceptEligibility] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [screenshotUrl, setScreenshotUrl] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    request<Receipt[]>("/v1/opportunities/imports", token, {
      signal: controller.signal,
    })
      .then((rows) => {
        setImports(rows);
        if (rows[0]) selectImport(rows[0]);
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setError((cause as Error).message);
      });
    return () => controller.abort();
  }, [token]);

  useEffect(
    () => () => {
      if (screenshotUrl) URL.revokeObjectURL(screenshotUrl);
    },
    [screenshotUrl],
  );

  function selectImport(item: Receipt) {
    setReceipt(item);
    setSelectedIds(
      item.posting.requirements.map((requirement) => requirement.id),
    );
    setImportance(
      Object.fromEntries(
        item.posting.requirements.map((requirement) => [
          requirement.id,
          requirement.importance,
        ]),
      ),
    );
    setAcceptEligibility(Boolean(item.posting.eligibility_requirements));
    setScreenshotUrl("");
    if (item.screenshot_available) {
      fetch(`/api/v1/opportunities/imports/${item.import_id}/screenshot`, {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then(async (response) => {
          if (response.ok)
            setScreenshotUrl(URL.createObjectURL(await response.blob()));
        })
        .catch(() => {});
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setMessage("");
    setBusy(true);
    try {
      const imported = await request<Receipt>(
        "/v1/opportunities/import",
        token,
        {
          method: "POST",
          body: JSON.stringify({ url }),
        },
      );
      setImports((current) => [imported, ...current]);
      selectImport(imported);
      setMessage(
        "Snapshot saved. Review the extracted requirements before creating a real-data mission.",
      );
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmReview() {
    if (!receipt) return;
    setError("");
    setMessage("");
    setBusy(true);
    try {
      const reviewed = await request<Receipt>(
        `/v1/opportunities/imports/${receipt.import_id}/review`,
        token,
        {
          method: "PATCH",
          body: JSON.stringify({
            expected_version: receipt.version,
            requirements: receipt.posting.requirements
              .filter((requirement) => selectedIds.includes(requirement.id))
              .map((requirement) => ({
                id: requirement.id,
                importance: importance[requirement.id],
              })),
            accept_eligibility: acceptEligibility,
          }),
        },
      );
      setImports((current) =>
        current.map((item) =>
          item.import_id === reviewed.import_id ? reviewed : item,
        ),
      );
      selectImport(reviewed);
      setMessage(
        "Reviewed job requirements saved. This version is ready for a mission.",
      );
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const reviewed = receipt?.reviewed_version === receipt?.version;
  const expired = Boolean(
    receipt?.posting.valid_through &&
    receipt.posting.valid_through < new Date().toISOString().slice(0, 10),
  );
  const latestForUrl =
    receipt &&
    imports.find((item) => item.original_url === receipt.original_url)
      ?.import_id === receipt.import_id;
  const sameUrlImports = receipt
    ? imports.filter((item) => item.original_url === receipt.original_url)
    : [];
  const selectedIndex = sameUrlImports.findIndex(
    (item) => item.import_id === receipt?.import_id,
  );
  const previousImport =
    selectedIndex >= 0 ? sameUrlImports[selectedIndex + 1] : undefined;

  return (
    <section className="panel" style={{ marginBottom: 24 }}>
      <h2>Import a public job</h2>
      <p className="muted">
        Supports HTTPS detail pages containing one structured JobPosting and
        current public Ashby postings. Static HTML is preferred; other
        JavaScript pages use a guarded browser fallback. The source snapshot and
        retrieval time are saved in your workspace.
      </p>
      <form onSubmit={submit}>
        <label htmlFor="import-url">Job page URL</label>
        <input
          id="import-url"
          type="url"
          required
          value={url}
          onChange={(event) => setUrl(event.target.value)}
        />
        <button className="primary full" disabled={busy}>
          {busy ? "Importing..." : "Import job"}
        </button>
      </form>
      {imports.length > 0 && (
        <div className="samples">
          {imports.map((item) => (
            <button
              type="button"
              key={item.import_id}
              className={receipt?.import_id === item.import_id ? "active" : ""}
              onClick={() => selectImport(item)}
            >
              {item.posting.company}: {item.posting.title}
              {item.reviewed_version === item.version
                ? " - reviewed"
                : " - needs review"}
            </button>
          ))}
        </div>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="notice">
          {message}
        </p>
      )}
      {receipt && (
        <div className="evidence">
          <h3>
            {receipt.posting.title} / {receipt.posting.company}
          </h3>
          <p>{receipt.posting.location || "Location not specified"}</p>
          <small>Source: {receipt.original_url}</small>
          {previousImport && (
            <p
              className={
                previousImport.snapshot_sha256 === receipt.snapshot_sha256
                  ? "muted"
                  : "notice"
              }
            >
              {previousImport.snapshot_sha256 === receipt.snapshot_sha256
                ? "This page snapshot matches the previous import."
                : "The saved source snapshot differs from the previous import. Recheck the requirements and constraints before confirming."}
            </p>
          )}
          <p className="muted">
            {receipt.posting.date_posted
              ? `Posted ${receipt.posting.date_posted}. `
              : "Posting date was not supplied. "}
            {receipt.posting.valid_through
              ? `Valid through ${receipt.posting.valid_through}.`
              : "Expiry date was not supplied; check the live page before applying."}
          </p>
          {expired && (
            <p role="alert" className="error">
              This posting has expired. Import a current job before starting a
              real-data mission.
            </p>
          )}
          <p className="muted">
            Check every requirement against the source excerpt. Remove
            unsupported items and mark preferred items correctly. This review
            does not change the saved page snapshot.
          </p>
          <blockquote>{receipt.posting.sources[0]?.excerpt}</blockquote>
          {receipt.posting.sources[0]?.retrieved_at && (
            <small>
              Retrieved{" "}
              {new Date(
                receipt.posting.sources[0].retrieved_at,
              ).toLocaleString()}
            </small>
          )}
          {screenshotUrl && (
            <img
              src={screenshotUrl}
              alt="Rendered job page captured during import"
              style={{ width: "100%", borderRadius: 8, marginBottom: 16 }}
            />
          )}
          {receipt.posting.requirements.map((requirement) => (
            <div className="evidence" key={requirement.id}>
              <label htmlFor={`keep-${requirement.id}`}>
                <input
                  id={`keep-${requirement.id}`}
                  type="checkbox"
                  checked={selectedIds.includes(requirement.id)}
                  onChange={(event) =>
                    setSelectedIds((current) =>
                      event.target.checked
                        ? [...current, requirement.id]
                        : current.filter((id) => id !== requirement.id),
                    )
                  }
                />
                Keep: {requirement.text}
              </label>
              <small>
                {requirement.category} / source {requirement.source_id}
              </small>
              <label htmlFor={`importance-${requirement.id}`}>Priority</label>
              <select
                id={`importance-${requirement.id}`}
                value={importance[requirement.id] ?? requirement.importance}
                disabled={!selectedIds.includes(requirement.id)}
                onChange={(event) =>
                  setImportance((current) => ({
                    ...current,
                    [requirement.id]: event.target.value as Importance,
                  }))
                }
              >
                <option value="required">Required</option>
                <option value="preferred">Preferred</option>
              </select>
            </div>
          ))}
          {receipt.posting.eligibility_requirements && (
            <div className="evidence">
              <strong>Extracted hard constraints</strong>
              <p className="muted">
                Review these against the source. If they are unsupported,
                exclude them and assess eligibility manually.
              </p>
              <ul>
                {Object.entries(receipt.posting.eligibility_requirements)
                  .filter(
                    ([key, value]) =>
                      ![
                        "schema_version",
                        "source_ids",
                        "requirements_complete",
                      ].includes(key) &&
                      value !== null &&
                      !(Array.isArray(value) && value.length === 0),
                  )
                  .map(([key, value]) => (
                    <li key={key}>
                      {key.replaceAll("_", " ")}:{" "}
                      {Array.isArray(value) ? value.join(", ") : String(value)}
                    </li>
                  ))}
              </ul>
              <label htmlFor="keep-eligibility">
                <input
                  id="keep-eligibility"
                  type="checkbox"
                  checked={acceptEligibility}
                  onChange={(event) =>
                    setAcceptEligibility(event.target.checked)
                  }
                />
                Keep these extracted hard constraints
              </label>
            </div>
          )}
          <button className="secondary" disabled={busy} onClick={confirmReview}>
            {reviewed ? "Save another review" : "Confirm reviewed requirements"}
          </button>
          {!demoMode && !latestForUrl && (
            <p className="muted">
              A newer snapshot exists for this URL. Review that import before
              starting a mission.
            </p>
          )}
          <button
            className="primary"
            disabled={!demoMode && (!reviewed || !latestForUrl || expired)}
            onClick={() => onSelect(receipt.original_url)}
          >
            Create mission for this job
          </button>
        </div>
      )}
    </section>
  );
}
