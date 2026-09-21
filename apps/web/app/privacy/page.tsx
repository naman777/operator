import Link from "next/link";

export default function Privacy() {
  return (
    <main
      style={{
        maxWidth: 800,
        margin: "0 auto",
        padding: "48px 24px",
        lineHeight: 1.7,
      }}
    >
      <Link href="/">Back to Operator</Link>
      <h1>Privacy and stored data</h1>
      <p>
        Updated September 21, 2026. Operator is a portfolio application for
        reviewing job fit and preparing application drafts. Use only resume and
        project information you are comfortable storing here. Applications are
        not submitted automatically.
      </p>
      <h2>What is stored</h2>
      <p>
        Your workspace can contain your profile, extracted resume text, evidence
        excerpts and embeddings, imported job pages and screenshots, mission
        history, approval decisions, drafts, and pipeline records. Starting
        fresh archives a profile; it does not delete that profile or its
        evidence.
      </p>
      <p>
        Accounts store an email address and a password hash. Session tokens are
        stored as hashes on the server; your browser stores its current token
        locally. Sign-in browser labels come from the device, so they are not
        verified device identities.
      </p>
      <h2>Where data is processed</h2>
      <p>
        The application runs on Google Compute Engine, with application data in
        Aiven PostgreSQL and workflow history in a separate Temporal database on
        the VM. Importing a job fetches the public URL and may render the page.
        Email and calendar actions are currently local mock records.
      </p>
      <p>
        Optional model enrichment, when enabled by the operator, can send
        relevant profile evidence and job content to the configured model
        provider. It is not required for the deterministic analysis path. Do not
        upload sensitive identifiers or information you do not want processed by
        these services.
      </p>
      <h2>Retention and controls</h2>
      <p>
        Guest access expires after 24 hours; expiry does not automatically erase
        saved data. Account sessions expire after 30 days. Account data,
        archived profiles, and mission records currently have no automatic
        deletion schedule. Backups and workflow history can retain additional
        copies.
      </p>
      <p>
        You can export workspace data from the Candidate Profile screen. Account
        security in Mission Control lets you revoke sessions and change your
        password. A password change signs out every session. Deleting individual
        profile evidence does not erase historical drafts, mission results, or
        backups that may contain it.
      </p>
      <p>
        Self-service account deletion, email verification, and
        forgotten-password recovery are not available yet. Do not rely on this
        service as the only copy of your resume or job history.
      </p>
      <h2>Operational records</h2>
      <p>
        Request logs record request IDs, methods, response codes, and timings.
        Shared admission counters store hashed client identifiers and expire at
        the end of a fixed rate-limit window; expired counters are removed in
        bounded batches as requests arrive. Hashing an IP address is not a
        guarantee of anonymity.
      </p>
    </main>
  );
}
