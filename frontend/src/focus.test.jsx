import { describe, expect, it, vi, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// Step-focus tests (2026-11-21): resume first — a fresh profile's
// current step is Documents, so the Documents panel dominates the page
// and the other workflow panels render minimized until opened.

const HEADER = {
  client_name: "Test Client",
  target_roles: [],
  location: "",
  remote_preference: "",
  employment_type: "",
  current_step: "documents",
};

const STEPS = ["documents", "interview", "preferences", "job_search", "applications", "follow_up"]
  .map((step) => ({ step, done: step === "documents" ? false : false }));

const PROFILE = {
  id: "p1",
  name: "Test Client",
  header: HEADER,
  workflow: { current_step: "documents", steps: STEPS },
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

function mockFetch() {
  const routes = {
    "/api/health": { status: "ok", app: "PocketProWS", free_sources: ["remoteok"] },
    "/api/profiles": { profiles: [{ id: "p1", name: "Test Client" }] },
    "/api/profiles/active": { active_profile_id: "p1", header: HEADER },
    "/api/profiles/p1": PROFILE,
    "/api/profiles/p1/interview": { complete: false, step: 0, total: 11, next_question: "Who is our client?" },
    "/api/profiles/p1/documents": { documents: [] },
    "/api/profiles/p1/status": STATUS,
  };
  return vi.fn(async (url) => {
    const data = routes[url];
    if (!data) return { ok: false, status: 404, json: async () => ({ detail: "not found" }) };
    return { ok: true, status: 200, json: async () => data };
  });
}

async function renderApp() {
  vi.stubGlobal("fetch", mockFetch());
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  root.render(<App />);
  await vi.waitFor(() => {
    expect(container.querySelectorAll(".ppws-steps .ppws-step").length).toBe(6);
  }, { timeout: 3000 });
  return { container, root };
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

describe("step focus", () => {
  it("the current step (documents) dominates; other panels are minimized", async () => {
    const { container, root } = await renderApp();
    // Documents is expanded: the resume upload is right there.
    const docs = container.querySelector("#documents");
    expect(docs).toBeTruthy();
    expect(docs.classList.contains("ppws-panel-min")).toBe(false);
    expect(docs.querySelector('input[type="file"]')).toBeTruthy();
    expect(docs.textContent).toContain("resume first");
    // Interview, search and agents are minimized bars.
    for (const id of ["#interview", "#search", "#agents"]) {
      const panel = container.querySelector(id);
      expect(panel, id).toBeTruthy();
      expect(panel.classList.contains("ppws-panel-min"), id).toBe(true);
    }
    // No interview answer box while the interview is minimized.
    expect(container.querySelector('input[aria-label="interview answer"]')).toBeNull();
    // The guidance cards compact once a client is active.
    expect(container.querySelector(".ppws-howto")?.classList.contains("is-compact")).toBe(true);
    root.unmount();
  });

  it("opening a minimized panel expands it and minimizes the previous one", async () => {
    const { container, root } = await renderApp();
    const openBtn = [...container.querySelectorAll("#interview button")]
      .find((b) => b.textContent.includes("Open this step"));
    expect(openBtn).toBeTruthy();
    openBtn.click();
    await vi.waitFor(() => {
      expect(container.querySelector('input[aria-label="interview answer"]')).toBeTruthy();
    }, { timeout: 3000 });
    // Documents is now the minimized one.
    expect(container.querySelector("#documents").classList.contains("ppws-panel-min")).toBe(true);
    root.unmount();
  });
});
