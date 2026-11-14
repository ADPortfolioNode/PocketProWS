import { describe, expect, it, vi, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// Rendered-DOM navigation tests: every workflow card and every in-page
// link must lead somewhere real. Regression cover for the dead "How it
// works" cards (they rendered as articles with hover effects but no
// link, so clicking them did nothing).

const HEADER = {
  client_name: "Test Client",
  target_roles: ["AI Engineer"],
  location: "New York",
  remote_preference: "remote preferred",
  employment_type: "Full-time",
  current_step: "interview",
};

const STEPS = ["interview", "documents", "preferences", "job_search", "applications", "follow_up"]
  .map((step) => ({ step, done: false }));

const PROFILE = {
  id: "p1",
  name: "Test Client",
  header: HEADER,
  workflow: { current_step: "interview", steps: STEPS },
};

const STATUS = {
  client_name: "Test Client",
  integrity: { passed: true, problems: [] },
  pipeline: { total: 0, counts: { saved: 0, applied: 0, interviewing: 0, offer: 0, hired: 0, rejected: 0 } },
  follow_ups_due: [],
  resources: { document_count: 0, healthy_count: 0, interview_notes_in_rag: 0, documents: [] },
  last_runs: [],
  saved_jobs: [],
};

function mockFetch(withProfile, health) {
  const routes = {
    "/api/health": health || { status: "ok", app: "PocketProWS", free_sources: ["remoteok"] },
    "/api/profiles": { profiles: withProfile ? [{ id: "p1", name: "Test Client" }] : [] },
    "/api/profiles/active": withProfile
      ? { active_profile_id: "p1", header: HEADER }
      : { active_profile_id: null, header: null },
    "/api/profiles/p1": PROFILE,
    "/api/profiles/p1/interview": { complete: false, step: 0, total: 11, next_question: "What is the client's full name?" },
    "/api/profiles/p1/documents": { documents: [] },
    "/api/profiles/p1/status": STATUS,
  };
  return vi.fn(async (url) => {
    const data = routes[url];
    if (!data) return { ok: false, status: 404, json: async () => ({ detail: "not found" }) };
    return { ok: true, status: 200, json: async () => data };
  });
}

async function renderApp(withProfile, health) {
  vi.stubGlobal("fetch", mockFetch(withProfile, health));
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  root.render(<App />);
  // Poll until the app has finished its first load (health pill text).
  await vi.waitFor(() => {
    expect(container.textContent).toContain("How it works");
  }, { timeout: 3000 });
  if (withProfile) {
    // Wait until the profile-scoped panels have loaded too (workflow
    // steps render only once the active profile has been fetched).
    await vi.waitFor(() => {
      expect(container.querySelectorAll(".ppws-steps .ppws-step").length).toBe(6);
    }, { timeout: 3000 });
  }
  return { container, root };
}

function stepCard(container, label) {
  return [...container.querySelectorAll(".ppws-step-card")]
    .find((c) => c.querySelector(".ppws-step-title")?.textContent.trim() === label);
}

afterEach(() => {
  document.body.innerHTML = "";
  window.history.replaceState(null, "", window.location.pathname || "/");
  vi.unstubAllGlobals();
});

const LABELS = {
  interview: "Interview", documents: "Documents", preferences: "Preferences",
  job_search: "Job search", applications: "Applications", follow_up: "Follow-up",
};

describe("workflow card navigation", () => {
  it("every card is a working link to a panel that exists (no profile yet)", async () => {
    const { container, root } = await renderApp(false);
    const expected = {
      interview: "#interview", preferences: "#interview", job_search: "#search",
      documents: "#client", applications: "#client", follow_up: "#client",
    };
    for (const [step, hash] of Object.entries(expected)) {
      const card = stepCard(container, LABELS[step]);
      expect(card, `card for ${step}`).toBeTruthy();
      const link = card.querySelector("a[href]");
      expect(link, `card ${step} must contain a link`).toBeTruthy();
      expect(link.getAttribute("href")).toBe(hash);
      expect(document.querySelector(hash), `target ${hash} for ${step} must exist`).toBeTruthy();
      link.click();
      // jsdom performs fragment navigation asynchronously — wait for it.
      await vi.waitFor(() => expect(window.location.hash).toBe(hash), { timeout: 2000 });
    }
    root.unmount();
  });

  it("cards lead to their own workflow panels once a client is active", async () => {
    const { container, root } = await renderApp(true);
    const expected = {
      interview: "#interview", preferences: "#interview", job_search: "#search",
      documents: "#documents", applications: "#agents", follow_up: "#agents",
    };
    for (const [step, hash] of Object.entries(expected)) {
      const card = stepCard(container, LABELS[step]);
      const link = card?.querySelector("a[href]");
      expect(link, `card ${step} must contain a link`).toBeTruthy();
      expect(link.getAttribute("href")).toBe(hash);
      expect(document.querySelector(hash), `target ${hash} for ${step} must exist`).toBeTruthy();
      link.click();
      await vi.waitFor(() => expect(window.location.hash).toBe(hash), { timeout: 2000 });
    }
    root.unmount();
  });

  it("workflow panel step rows link to the same panels", async () => {
    const { container, root } = await renderApp(true);
    const rows = [...container.querySelectorAll(".ppws-steps .ppws-step-name a[href]")];
    expect(rows.length).toBe(6);
    for (const a of rows) {
      expect(document.querySelector(a.getAttribute("href"))).toBeTruthy();
    }
    root.unmount();
  });

  it("pill names a wrong backend instead of parroting its status", async () => {
    // A foreign app holding the backend port answers health in its own
    // shape (status "healthy", no app identity, no free_sources). The
    // pill must call that out, not repeat "healthy" back at the user.
    const { container, root } = await renderApp(false, { status: "healthy" });
    const pill = container.querySelector(".ppws-status-pill");
    expect(pill.textContent).toContain("wrong app");
    expect(pill.textContent).not.toContain("Backend: ok");
    root.unmount();
  });

  it("pill says Backend: ok for the real PocketProWS backend", async () => {
    const { container, root } = await renderApp(false);
    const pill = container.querySelector(".ppws-status-pill");
    expect(pill.textContent).toContain("Backend: ok");
    root.unmount();
  });

  it("no dead in-page links anywhere on the page (with a client active)", async () => {
    const { container, root } = await renderApp(true);
    const anchors = [...container.querySelectorAll('a[href^="#"]')]
      .filter((a) => a.getAttribute("href").length > 1);
    expect(anchors.length).toBeGreaterThan(0);
    for (const a of anchors) {
      expect(document.querySelector(a.getAttribute("href")),
        `dead link ${a.getAttribute("href")}`).toBeTruthy();
    }
    root.unmount();
  });
});
