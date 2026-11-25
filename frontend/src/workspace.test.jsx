import { describe, expect, it, vi, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// Workspace redesign (2026-11-24): the workflow owns the screen —
// compact hero + step rail + concierge dock once a client is active,
// "How it works" cards only onboard a brand-new user.

const HEADER = {
  client_name: "Test Client",
  target_roles: ["AI Engineer"],
  location: "New York",
  remote_preference: "remote preferred",
  employment_type: "Full-time",
  current_step: "interview",
};

const STEPS = ["documents", "interview", "preferences", "job_search", "applications", "follow_up"]
  .map((step) => ({ step, done: step === "documents" }));

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

function mockFetch(withProfile) {
  const routes = {
    "/api/health": { status: "ok", app: "PocketProWS", free_sources: ["remoteok"] },
    "/api/profiles": { profiles: withProfile ? [{ id: "p1", name: "Test Client" }] : [] },
    "/api/profiles/active": withProfile
      ? { active_profile_id: "p1", header: HEADER }
      : { active_profile_id: null, header: null },
    "/api/profiles/p1": PROFILE,
    "/api/profiles/p1/interview": { complete: false, step: 1, total: 12, next_question: "What is your current role?" },
    "/api/profiles/p1/documents": { documents: [] },
    "/api/profiles/p1/status": STATUS,
  };
  return vi.fn(async (url) => {
    const data = routes[url];
    if (!data) return { ok: false, status: 404, json: async () => ({ detail: "not found" }) };
    return { ok: true, status: 200, json: async () => data };
  });
}

async function renderApp(withProfile) {
  vi.stubGlobal("fetch", mockFetch(withProfile));
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  root.render(<App />);
  await vi.waitFor(() => {
    expect(container.textContent).toContain("Backend:");
  }, { timeout: 3000 });
  if (withProfile) {
    await vi.waitFor(() => {
      expect(container.querySelectorAll(".ppws-rail-step").length).toBe(6);
    }, { timeout: 3000 });
  } else {
    await vi.waitFor(() => {
      expect(container.textContent).toContain("How it works");
    }, { timeout: 3000 });
  }
  return { container, root };
}

afterEach(() => {
  document.body.innerHTML = "";
  window.history.replaceState(null, "", window.location.pathname || "/");
  vi.unstubAllGlobals();
});

describe("workspace redesign", () => {
  it("rail marks done and current steps, and the dock holds the concierge", async () => {
    const { container, root } = await renderApp(true);
    const steps = [...container.querySelectorAll(".ppws-rail-step")];
    expect(steps.map((s) => s.querySelector(".ppws-rail-name").textContent.trim())).toEqual([
      "Documents", "Interview", "Preferences", "Job search", "Applications", "Follow-up",
    ]);
    expect(steps[0].className).toContain("is-done");
    expect(steps[1].className).toContain("is-current");
    expect(container.querySelector(".ppws-concierge-dock #interview")).toBeTruthy();
    expect(container.querySelector(".ppws-concierge-dock .ppws-concierge-head")).toBeTruthy();
    root.unmount();
  });

  it("clicking a rail step focuses its panel", async () => {
    const { container, root } = await renderApp(true);
    // Job search starts minimized (current step is interview).
    expect(container.querySelector('#search input[aria-label="job query"]')).toBeNull();
    const link = [...container.querySelectorAll(".ppws-rail-link")]
      .find((a) => a.querySelector(".ppws-rail-name")?.textContent.trim() === "Job search");
    link.click();
    await vi.waitFor(() => {
      expect(container.querySelector('#search input[aria-label="job query"]')).toBeTruthy();
    }, { timeout: 3000 });
    root.unmount();
  });

  it("hero compacts and how-it-works hides once a client is active", async () => {
    const { container: active, root: rootA } = await renderApp(true);
    expect(active.querySelector(".ppws-hero").className).toContain("is-compact");
    expect(active.textContent).not.toContain("How it works");
    rootA.unmount();

    const { container: fresh, root: rootB } = await renderApp(false);
    expect(fresh.querySelector(".ppws-hero").className).not.toContain("is-compact");
    expect(fresh.querySelector(".ppws-howto")).toBeTruthy();
    expect(fresh.querySelector(".ppws-step-rail")).toBeNull();
    rootB.unmount();
  });

  it("workflow card keeps progress without duplicating the step list", async () => {
    const { container, root } = await renderApp(true);
    expect(container.querySelector("#workflow .ppws-progress-count").textContent).toContain("1 of 6 steps done");
    expect(container.querySelector("#workflow .ppws-steps")).toBeNull();
    expect(container.querySelector("#workflow .ppws-workflow-next").textContent).toContain("Interview");
    root.unmount();
  });
});
