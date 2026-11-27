import { describe, expect, it, vi, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// Page submission (2026-11-26): one selection per job and one
// submission per page. Selecting two jobs prepares both packs with
// ONE batch request, the review shows both submissions, and one
// authorize click submits the page with ONE batch request.

const HEADER = {
  client_name: "Test Client", target_roles: [], location: "",
  remote_preference: "", employment_type: "", current_step: "documents",
};
const STEPS = ["documents", "interview", "preferences", "job_search", "applications", "follow_up"]
  .map((step) => ({ step, done: false }));
const PROFILE = { id: "p1", name: "Test Client", header: HEADER,
                  workflow: { current_step: "documents", steps: STEPS },
                  client: { name: "Test Client" } };

function pack(jobId, title, company) {
  return {
    job_id: jobId, title, company, url: `https://example.com/${jobId}`,
    fit: { wanted: ["python"], matched: ["python"], missing: [], coverage: 1,
           summary: "Strong match." },
    cover_letter: `Dear ${company} hiring team,\n\nI am applying for the ${title} position at ${company}.`,
    answers: [], provider: "gemini", generated_at: "2026-11-26T00:00:00Z",
    letter_check: { checked: true, provider: "gemini", verdict: "pass", issues: [], lint_issues: [] },
    note: "Preparation only.",
  };
}
const PACKS = {
  job1: pack("job1", "Python Developer", "Acme"),
  job2: pack("job2", "AI Engineer", "Beta"),
};
const JOBS = [
  { id: "job1", title: "Python Developer", company: "Acme", location: "Remote",
    url: "https://example.com/job1", application_status: "saved" },
  { id: "job2", title: "AI Engineer", company: "Beta", location: "Remote",
    url: "https://example.com/job2", application_status: "saved" },
];
const STATUS = {
  client_name: "Test Client",
  integrity: { passed: true, problems: [] },
  pipeline: { total: 2, counts: { saved: 2, applied: 0, interviewing: 0, offer: 0, hired: 0, rejected: 0 } },
  follow_ups_due: [],
  resources: { document_count: 1, healthy_count: 1, interview_notes_in_rag: 0, documents: [] },
  last_runs: [],
  saved_jobs: JOBS,
};

function mockFetch(calls) {
  const routes = {
    "/api/health": { status: "ok", app: "PocketProWS", free_sources: ["remoteok"] },
    "/api/profiles": { profiles: [{ id: "p1", name: "Test Client" }] },
    "/api/profiles/active": { active_profile_id: "p1", header: HEADER },
    "/api/profiles/p1": PROFILE,
    "/api/profiles/p1/interview": { complete: false, step: 0, total: 12, next_question: "Who is our client?" },
    "/api/profiles/p1/documents": { documents: [{ id: "d1", filename: "resume.txt" }] },
    "/api/profiles/p1/status": STATUS,
    "/api/profiles/p1/chat": { messages: [] },
    "/api/mail/status": { configured: true, from: "sender@example.com", missing: [] },
  };
  return vi.fn(async (url, opts = {}) => {
    const method = opts.method || "GET";
    calls.push({ url, method, body: opts.body ? JSON.parse(opts.body) : null });
    if (url === "/api/profiles/p1/saved-jobs/apply-packs/batch" && method === "POST") {
      return { ok: true, status: 200, json: async () => ({
        packs: PACKS,
        results: [
          { job_id: "job1", status: "prepared", application_email: "jobs@acme.com", ready: true, checks: [] },
          { job_id: "job2", status: "prepared", application_email: "hiring@beta.com", ready: true, checks: [] },
        ],
        batch: { requested: 2, prepared: 2, skipped: 0 },
      }) };
    }
    if (url === "/api/profiles/p1/saved-jobs/submissions/batch" && method === "POST") {
      return { ok: true, status: 200, json: async () => ({
        submitted: 2, failed: 0,
        results: [
          { job_id: "job1", status: "sent", job_status: "applied" },
          { job_id: "job2", status: "sent", job_status: "applied" },
        ],
      }) };
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

describe("page submission", () => {
  it("selects jobs, prepares once, reviews once, submits once", async () => {
    const calls = [];
    vi.stubGlobal("fetch", mockFetch(calls));
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
      expect(container.querySelectorAll(".ppws-job-select input").length).toBe(2);
    }, { timeout: 3000 });

    const boxes = container.querySelectorAll(".ppws-job-select input");
    boxes[0].click();
    boxes[1].click();
    await vi.waitFor(() => {
      expect([...container.querySelectorAll("button")]
        .some((b) => b.textContent === "Prepare selected submissions (2)")).toBe(true);
    }, { timeout: 3000 });

    [...container.querySelectorAll("button")]
      .find((b) => b.textContent === "Prepare selected submissions (2)").click();
    await vi.waitFor(() => {
      expect(container.querySelector(".ppws-batch-review")).toBeTruthy();
      expect(container.querySelector(".ppws-batch-review").textContent)
        .toContain("Review this page submission");
    }, { timeout: 3000 });

    const preparePosts = calls.filter((c) => c.url.endsWith("/apply-packs/batch") && c.method === "POST");
    expect(preparePosts.length).toBe(1);
    expect(preparePosts[0].body.job_ids).toEqual(["job1", "job2"]);
    const recipients = [...container.querySelectorAll('.ppws-batch-review input[type="email"]')]
      .map((input) => input.value);
    expect(recipients).toEqual(["jobs@acme.com", "hiring@beta.com"]);

    [...container.querySelectorAll("button")]
      .find((b) => b.textContent === "Authorize and submit selected page").click();
    await vi.waitFor(() => {
      expect(container.querySelector(".ppws-batch-msg").textContent)
        .toContain("Submitted the page — 2 applications emailed");
    }, { timeout: 3000 });

    const submitPosts = calls.filter((c) => c.url.endsWith("/submissions/batch") && c.method === "POST");
    expect(submitPosts.length).toBe(1);
    expect(submitPosts[0].body.confirm).toBe(true);
    expect(submitPosts[0].body.submissions.map((s) => s.job_id)).toEqual(["job1", "job2"]);
    expect(submitPosts[0].body.submissions.map((s) => s.to)).toEqual(["jobs@acme.com", "hiring@beta.com"]);
    root.unmount();
  });
});
