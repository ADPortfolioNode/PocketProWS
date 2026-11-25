import { describe, expect, it, vi, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// Pack UX (2026-11-24): the letter's check status is a badge at a
// glance; deterministic lint problems are shown even when the LM
// check is unavailable; and a letter can be regenerated in place
// (a second POST rebuilds the pack) without closing the panel.

const HEADER = {
  client_name: "Test Client", target_roles: [], location: "",
  remote_preference: "", employment_type: "", current_step: "documents",
};
const STEPS = ["documents", "interview", "preferences", "job_search", "applications", "follow_up"]
  .map((step) => ({ step, done: false }));
const PROFILE = { id: "p1", name: "Test Client", header: HEADER,
                  workflow: { current_step: "documents", steps: STEPS } };
const JOB = { id: "job1", title: "Python Developer", company: "Acme", location: "Remote",
              url: "https://example.com/job1", application_status: "saved" };
const STATUS = {
  client_name: "Test Client", integrity: { passed: true, problems: [] },
  pipeline: { total: 1, counts: { saved: 1, applied: 0, interviewing: 0, offer: 0, hired: 0, rejected: 0 } },
  follow_ups_due: [],
  resources: { document_count: 1, healthy_count: 1, interview_notes_in_rag: 0, documents: [] },
  last_runs: [], saved_jobs: [JOB],
};

const PACK_BAD = {
  job_id: "job1", title: "Python Developer", company: "Acme", url: JOB.url,
  fit: { wanted: ["python"], matched: ["python"], missing: [], coverage: 1,
         summary: "Strong match." },
  cover_letter: "Dear Acme hiring team,\n\nwarm and friendly.",
  answers: [], provider: "template", generated_at: "2026-11-24T00:00:00Z",
  letter_check: { checked: false, reason: "HTTP 429",
                  lint_issues: ["the tone setting is printed as a standalone line in the letter"] },
  note: "Preparation only.",
};
const PACK_GOOD = {
  ...PACK_BAD,
  cover_letter: "Dear Acme hiring team,\n\nI am applying for the Python Developer position at Acme.",
  letter_check: { checked: true, provider: "gemini", verdict: "pass", issues: [], revised: false, lint_issues: [] },
};

function mockFetch(state) {
  const routes = {
    "/api/health": { status: "ok", app: "PocketProWS", free_sources: ["remoteok"] },
    "/api/profiles": { profiles: [{ id: "p1", name: "Test Client" }] },
    "/api/profiles/active": { active_profile_id: "p1", header: HEADER },
    "/api/profiles/p1": PROFILE,
    "/api/profiles/p1/interview": { complete: false, step: 0, total: 11, next_question: "Who is our client?" },
    "/api/profiles/p1/documents": { documents: [] },
    "/api/profiles/p1/status": STATUS,
    "/api/profiles/p1/chat": { messages: [] },
  };
  return vi.fn(async (url, opts = {}) => {
    const method = opts.method || "GET";
    if (url === "/api/profiles/p1/saved-jobs/job1/apply-pack" && method === "POST") {
      state.posts += 1;
      return { ok: true, status: 200, json: async () => ({ apply_pack: state.posts === 1 ? PACK_BAD : PACK_GOOD }) };
    }
    if (url === "/api/profiles/active" && method === "POST") {
      return { ok: true, status: 200, json: async () => ({ active_profile_id: "p1" }) };
    }
    const data = routes[url];
    if (!data) return { ok: false, status: 404, json: async () => ({ detail: "not found" }) };
    return { ok: true, status: 200, json: async () => data };
  });
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

describe("pack letter UX", () => {
  it("shows lint problems and the unchecked badge, then regenerates in place", async () => {
    const state = { posts: 0 };
    vi.stubGlobal("fetch", mockFetch(state));
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(<App />);
    await vi.waitFor(() => {
      expect(container.querySelectorAll(".ppws-rail-step").length).toBe(6);
    }, { timeout: 3000 });
    [...container.querySelectorAll("#agents button")]
      .find((b) => b.textContent.includes("Open this step")).click();
    await vi.waitFor(() => {
      expect([...container.querySelectorAll("button")].some((b) => b.textContent === "Apply pack")).toBe(true);
    }, { timeout: 3000 });
    [...container.querySelectorAll("button")].find((b) => b.textContent === "Apply pack").click();
    await vi.waitFor(() => {
      const pack = container.querySelector(".ppws-pack");
      expect(pack).toBeTruthy();
      expect(pack.querySelector(".ppws-check-badge.is-off")).toBeTruthy();
      expect(pack.textContent).toContain("Basic checks found problems in this letter:");
      expect(pack.textContent).toContain("tone setting is printed");
    }, { timeout: 3000 });
    [...container.querySelectorAll("button")].find((b) => b.textContent === "Regenerate letter").click();
    await vi.waitFor(() => {
      const pack = container.querySelector(".ppws-pack");
      expect(state.posts).toBe(2);
      expect(pack.querySelector(".ppws-check-badge.is-pass")).toBeTruthy();
      expect(pack.textContent).not.toContain("Basic checks found problems");
      expect(pack.textContent).toContain("I am applying for the Python Developer position at Acme.");
    }, { timeout: 3000 });
    root.unmount();
  });
});
