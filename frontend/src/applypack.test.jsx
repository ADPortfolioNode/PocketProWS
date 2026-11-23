import { describe, expect, it, vi, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// Apply pack test (2026-11-22): from the saved-jobs list, one click
// builds the pack (fit + cover letter + answers) and shows it inline.

const HEADER = {
  client_name: "Test Client",
  target_roles: [],
  location: "",
  remote_preference: "",
  employment_type: "",
  current_step: "documents",
};

const STEPS = ["documents", "interview", "preferences", "job_search", "applications", "follow_up"]
  .map((step) => ({ step, done: false }));

const PROFILE = {
  id: "p1",
  name: "Test Client",
  header: HEADER,
  workflow: { current_step: "documents", steps: STEPS },
};

const JOB = { id: "job1", title: "Python Developer", company: "Acme", location: "Remote",
              url: "https://example.com/job1", application_status: "saved" };

const STATUS = {
  client_name: "Test Client",
  integrity: { passed: true, problems: [] },
  pipeline: { total: 1, counts: { saved: 1, applied: 0, interviewing: 0, offer: 0, hired: 0, rejected: 0 } },
  follow_ups_due: [],
  resources: { document_count: 1, healthy_count: 1, interview_notes_in_rag: 0, documents: [] },
  last_runs: [],
  saved_jobs: [JOB],
};

const PACK = {
  job_id: "job1", title: "Python Developer", company: "Acme", url: JOB.url,
  fit: { wanted: ["python", "docker"], matched: ["python"], missing: ["docker"],
         coverage: 0.5, summary: "Partial match: 1 of 2 named skills are on the resume; 1 to address." },
  cover_letter: "Dear Acme hiring team,\n\nI am applying for the Python Developer position at Acme.",
  answers: [{ question: "Why are you interested in this role?", answer: "Because it fits." }],
  provider: "template", generated_at: "2026-11-22T00:00:00Z",
  letter_check: { checked: true, provider: "gemini", verdict: "pass", issues: [], revised: false },
  note: "Preparation only — review everything, then open the posting and submit it yourself.",
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
    "/api/profiles/p1/chat": { messages: [] },
  };
  return vi.fn(async (url, opts = {}) => {
    const method = opts.method || "GET";
    if (url === "/api/profiles/p1/saved-jobs/job1/apply-pack" && method === "POST") {
      return { ok: true, status: 200, json: async () => ({ apply_pack: PACK }) };
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

describe("apply pack", () => {
  it("builds and shows the pack from a saved job", async () => {
    vi.stubGlobal("fetch", mockFetch());
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(<App />);
    await vi.waitFor(() => {
      expect(container.querySelectorAll(".ppws-steps .ppws-step").length).toBe(6);
    }, { timeout: 3000 });
    const openBtn = [...container.querySelectorAll("#agents button")]
      .find((b) => b.textContent.includes("Open this step"));
    openBtn.click();
    await vi.waitFor(() => {
      expect([...container.querySelectorAll("button")].some((b) => b.textContent === "Apply pack")).toBe(true);
    }, { timeout: 3000 });
    [...container.querySelectorAll("button")].find((b) => b.textContent === "Apply pack").click();
    await vi.waitFor(() => {
      const pack = container.querySelector(".ppws-pack");
      expect(pack).toBeTruthy();
      expect(pack.textContent).toContain("Partial match");
      expect(pack.textContent).toContain("I am applying for the Python Developer position at Acme.");
      expect(pack.textContent).toContain("Why are you interested in this role?");
      expect(pack.textContent).toContain("submit it yourself");
      expect(pack.textContent).toContain("LM check (gemini): passed");
    }, { timeout: 3000 });
    root.unmount();
  });
});
