import { describe, expect, it, vi, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// Submit application (2026-11-24): each job lead with a built pack
// gets a Submit button. It opens the submission panel — the readiness
// checklist, the recipient prefilled from the posting when it carries
// one — and only "Authorize and submit" posts, with confirm: true.

const HEADER = {
  client_name: "Test Client", target_roles: [], location: "",
  remote_preference: "", employment_type: "", current_step: "documents",
};
const STEPS = ["documents", "interview", "preferences", "job_search", "applications", "follow_up"]
  .map((step) => ({ step, done: false }));
const PROFILE = { id: "p1", name: "Test Client", header: HEADER,
                  workflow: { current_step: "documents", steps: STEPS },
                  client: { name: "Test Client" } };
const PACK = {
  job_id: "job1", title: "Python Developer", company: "Acme", url: "https://example.com/job1",
  fit: { wanted: ["python"], matched: ["python"], missing: [], coverage: 1,
         summary: "Strong match." },
  cover_letter: "Dear Acme hiring team,\n\nI am applying for the Python Developer position at Acme.",
  answers: [], provider: "template", generated_at: "2026-11-24T00:00:00Z",
  note: "Preparation only.",
};
const JOB = { id: "job1", title: "Python Developer", company: "Acme", location: "Remote",
              url: "https://example.com/job1", application_status: "saved",
              apply_pack: PACK };
const READINESS = {
  job_id: "job1", submitted: null, application_email: "apply@acme.com", ready: true,
  checks: [
    { key: "pack", label: "Apply pack built — cover letter and answers from the profile", ok: true, detail: "" },
    { key: "contact", label: "Client contact on the letter", ok: true, detail: "" },
    { key: "document", label: "A document to attach (the resume)", ok: true, detail: "" },
    { key: "recipient", label: "Application email for this job", ok: true, detail: "apply@acme.com" },
  ],
};

function makeStatus(job) {
  return {
    client_name: "Test Client",
    integrity: { passed: true, problems: [] },
    pipeline: { total: 1, counts: { saved: 1, applied: 0, interviewing: 0, offer: 0, hired: 0, rejected: 0 } },
    follow_ups_due: [],
    resources: { document_count: 1, healthy_count: 1, interview_notes_in_rag: 0, documents: [] },
    last_runs: [],
    saved_jobs: [job],
  };
}

function mockFetch(calls, job) {
  const routes = {
    "/api/health": { status: "ok", app: "PocketProWS", free_sources: ["remoteok"] },
    "/api/profiles": { profiles: [{ id: "p1", name: "Test Client" }] },
    "/api/profiles/active": { active_profile_id: "p1", header: HEADER },
    "/api/profiles/p1": PROFILE,
    "/api/profiles/p1/interview": { complete: false, step: 0, total: 11, next_question: "Who is our client?" },
    "/api/profiles/p1/documents": { documents: [{ id: "d1", filename: "resume.txt" }] },
    "/api/profiles/p1/status": makeStatus(job),
    "/api/profiles/p1/chat": { messages: [] },
    "/api/mail/status": { configured: true, from: "sender@example.com", missing: [] },
    "/api/profiles/p1/saved-jobs/job1/submission": READINESS,
  };
  return vi.fn(async (url, opts = {}) => {
    const method = opts.method || "GET";
    calls.push({ url, method, body: opts.body ? JSON.parse(opts.body) : null });
    if (url === "/api/profiles/p1/saved-jobs/job1/email-application" && method === "POST") {
      return { ok: true, status: 200, json: async () => ({
        emailed: { to: "apply@acme.com", subject: "Application for Python Developer — Test Client",
                   from: "sender@example.com", attachment: "resume.txt", at: "2026-11-24T00:00:00Z" },
        job_status: "applied" }) };
    }
    if (url === "/api/profiles/active" && method === "POST") {
      return { ok: true, status: 200, json: async () => ({ active_profile_id: "p1" }) };
    }
    const data = routes[url];
    if (!data) return { ok: false, status: 404, json: async () => ({ detail: "not found" }) };
    return { ok: true, status: 200, json: async () => data };
  });
}

async function openAgents(container) {
  await vi.waitFor(() => {
    expect(container.querySelectorAll(".ppws-rail-step").length).toBe(6);
  }, { timeout: 3000 });
  [...container.querySelectorAll("#agents button")]
    .find((b) => b.textContent.includes("Open this step")).click();
  await vi.waitFor(() => {
    expect(container.querySelector(".ppws-saved-jobs")).toBeTruthy();
  }, { timeout: 3000 });
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

describe("submit application", () => {
  it("button appears with a pack; authorize-and-submit sends with confirm", async () => {
    const calls = [];
    vi.stubGlobal("fetch", mockFetch(calls, JOB));
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(<App />);
    await openAgents(container);
    const btn = [...container.querySelectorAll("button")]
      .find((b) => b.textContent === "Submit application");
    expect(btn).toBeTruthy();
    btn.click();
    await vi.waitFor(() => {
      expect(container.querySelector(".ppws-submit-checks")).toBeTruthy();
      expect(container.querySelector(".ppws-submit-checks").textContent)
        .toContain("apply@acme.com");
    }, { timeout: 3000 });
    const toInput = container.querySelector('.ppws-email input[type="email"]');
    expect(toInput.value).toBe("apply@acme.com");
    const posts = () => calls.filter((c) => c.url.endsWith("/email-application") && c.method === "POST");
    expect(posts().length).toBe(0);
    [...container.querySelectorAll("button")].find((b) => b.textContent === "Review submission").click();
    await vi.waitFor(() => {
      expect(container.querySelector(".ppws-email").textContent)
        .toContain("Submit your application to");
    }, { timeout: 3000 });
    expect(posts().length).toBe(0);
    [...container.querySelectorAll("button")].find((b) => b.textContent === "Authorize and submit").click();
    await vi.waitFor(() => {
      expect(posts().length).toBe(1);
      expect(posts()[0].body.confirm).toBe(true);
      expect(posts()[0].body.to).toBe("apply@acme.com");
      expect(container.querySelector(".ppws-email").textContent)
        .toContain("Submitted — emailed to apply@acme.com");
    }, { timeout: 3000 });
    root.unmount();
  });

  it("no pack, no button; submitted job shows the submitted line", async () => {
    const calls = [];
    const bare = { ...JOB, apply_pack: undefined };
    vi.stubGlobal("fetch", mockFetch(calls, bare));
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(<App />);
    await openAgents(container);
    expect([...container.querySelectorAll("button")]
      .some((b) => b.textContent === "Submit application")).toBe(false);
    root.unmount();

    const calls2 = [];
    const done = { ...JOB, apply_pack: { ...PACK, emailed: { to: "apply@acme.com", at: "2026-11-24T00:00:00Z" } } };
    vi.stubGlobal("fetch", mockFetch(calls2, done));
    const container2 = document.createElement("div");
    document.body.appendChild(container2);
    const root2 = createRoot(container2);
    root2.render(<App />);
    await openAgents(container2);
    await vi.waitFor(() => {
      expect(container2.querySelector(".ppws-submitted")).toBeTruthy();
      expect(container2.querySelector(".ppws-submitted").textContent)
        .toContain("apply@acme.com");
    }, { timeout: 3000 });
    expect([...container2.querySelectorAll("button")]
      .some((b) => b.textContent === "Submit application")).toBe(false);
    root2.unmount();
  });
});
