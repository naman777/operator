"use client";
import { useEffect, useState } from "react";
import type { components } from "@operator/contracts";
import { request } from "../lib/api";
type Device = components["schemas"]["AccountDeviceView"];

export function AccountSecurity({
  token,
  onSignOut,
}: {
  token: string;
  onSignOut: () => void;
}) {
  const [devices, setDevices] = useState<Device[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    request<Device[]>("/v1/accounts/sessions", token, {
      signal: controller.signal,
    })
      .then(setDevices)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [token]);
  async function act(
    path: string,
    method: string,
    signOut = false,
    body?: object,
  ) {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(
          typeof payload?.detail === "string"
            ? payload.detail
            : "Unable to update account security.",
        );
      }
      if (signOut) {
        onSignOut();
        return;
      }
      setDevices(await request<Device[]>("/v1/accounts/sessions", token));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel account-form">
      <h2>Account security</h2>
      <p className="muted">
        Active sign-ins expire after 30 days. Browser labels are reported by the
        device and may not uniquely identify it.
      </p>
      {error && <p role="alert">{error}</p>}
      <ul>
        {devices.map((device) => (
          <li key={device.id}>
            <p>
              {device.current ? "This session" : "Other session"}:{" "}
              {device.user_agent || "Unknown browser"}
            </p>
            <p className="muted">
              Signed in {new Date(device.created_at).toLocaleString()} ? Expires{" "}
              {new Date(device.expires_at).toLocaleString()}
            </p>
            <button
              className="secondary"
              disabled={busy}
              onClick={() =>
                act(
                  `/v1/accounts/sessions/${device.id}`,
                  "DELETE",
                  device.current,
                )
              }
            >
              Sign out{device.current ? " here" : " session"}
            </button>
          </li>
        ))}
      </ul>
      <button
        className="secondary"
        disabled={busy}
        onClick={() => act("/v1/accounts/sessions/revoke-others", "POST")}
      >
        Sign out all other sessions
      </button>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          act("/v1/accounts/password", "POST", true, {
            current_password: currentPassword,
            new_password: newPassword,
          });
        }}
      >
        <label>
          Current password
          <input
            type="password"
            autoComplete="current-password"
            required
            minLength={12}
            maxLength={128}
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
          />
        </label>
        <label>
          New password
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            maxLength={128}
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
        </label>
        <button className="secondary" disabled={busy}>
          Change password and sign out everywhere
        </button>
      </form>
    </section>
  );
}
