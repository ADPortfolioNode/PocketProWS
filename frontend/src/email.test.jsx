import { describe, expect, it, vi, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// Email the apply pack (2026-11-23): the pack gains an email step —
// compose, REVIEW (exact recipient/subject/attachment), and only the
// review screen's "Approve and send" posts, with confirm: true.
// Unconfigured mail shows an honest not-configured line instead.

const HEADER = {
  client_name: "Test Client", target_roles: [], location: "",
  remote_preference: "", employment_type: "", current_step: "documents",
};
const STEPS = ["documents", "interview", "preferences", "job_search", "applications", "follow_up"]
  .map((step) => ({ step, done: false }));
const PROFILE = { id: "p1", name: "Test Client", header: HEADER,
                  workflow: { current_step: "documents", steps: STEPS },
                  client: { name: "Test Client" } };
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
  fit: { wanted: ["python"], matched: ["python"], missing: [], coverage: 1,
         summary: "Strong match." },
  cover_letter: "Dear Acme hiring team,\n\nI am applying for the Python Developer position at Acme.",
  answers: [], provider: "template", generated_at: "2026-11-23T00:00:00Z",
  note: "Preparation only — review everything, then open the posting and submit it yourself.",
};

function mockFetch(calls, mailStatus) {
  const routes = {
    "/api/health": { status: "ok", app: "PocketProWS", free_sources: ["remoteok"] },
    "/api/profiles": { profiles: [{ id: "p1", name: "Test Client" }] },
    "/api/profiles/active": { active_profile_id: "p1", header: HEADER },
    "/api/profiles/p1": PROFILE,
    "/api/profiles/p1/interview": { complete: false, step: 0, total: 11, next_question: "Who is our client?" },
    "/api/profiles/p1/documents": { documents: [{ id: "d1", filename: "resume.txt" }] },
    "/api/profiles/p1/status": STATUS,
    "/api/profiles/p1/chat": { messages: [] },
    "/api/mail/status": mailStatus,
  };
  return vi.fn(async (url, opts = {}) => {
    const method = opts.method || "GET";
    calls.push({ url, method, body: opts.body ? JSON.parse(opts.body) : null });
    if (url === "/api/profiles/p1/saved-jobs/job1/apply-pack" && method === "POST") {
      return { ok: true, status: 200, json: async () => ({ apply_pack: PACK }) };
    }
    if (url === "/api/profiles/p1/saved-jobs/job1/email-application" && method === "POST") {
      return { ok: true, status: 200, json: async () => ({
        emailed: { to: "hiring@acme.com", subject: "Application for Python Developer — Test Client",
                   from: "sender@example.com", attachment: "resume.txt", at: "2026-11-23T16:00:00Z" },
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

async function openPack(container) {
  await vi.waitFor(() => {
    expect(container.querySelectorAll(".ppws-steps .ppws-step").length).toBe(6);
  }, { timeout: 3000 });
  [...container.querySelectorAll("#agents button")]
    .find((b) => b.textContent.includes("Open this step")).click();
  await vi.waitFor(() => {
    expect([...container.querySelectorAll("button")].some((b) => b.textContent === "Apply pack")).toBe(true);
  }, { timeout: 3000 });
  [...container.querySelectorAll("button")].find((b) => b.textContent === "Apply pack").click();
  await vi.waitFor(() => {
    expect(container.querySelector(".ppws-email")).toBeTruthy();
  }, { timeout: 3000 });
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

describe("email the apply pack", () => {
  it("sends only from the review screen, with explicit approval", async () => {
    const calls = [];
    vi.stubGlobal("fetch", mockFetch(calls, { configured: true, from: "sender@example.com", missing: [] }));
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(<App />);
    await openPack(container);
    const emailPosts = () => calls.filter((c) => c.url.endsWith("/email-application") && c.method === "POST");
    expect(emailPosts().length).toBe(0);
    const toInput = container.querySelector('.ppws-email input[type="email"]');
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    setter.call(toInput, "hiring@acme.com");
    toInput.dispatchEvent(new Event("input", { bubbles: true }));
    [...container.querySelectorAll("button")].find((b) => b.textContent === "Review send").click();
    await vi.waitFor(() => {
      expect(container.querySelector(".ppws-email").textContent).toContain("Send to");
      expect(container.querySelector(".ppws-email").textContent).toContain("resume.txt");
    }, { timeout: 3000 });
    // Reviewing is not sending.
    expect(emailPosts().length).toBe(0);
    [...container.querySelectorAll("button")].find((b) => b.textContent === "Approve and send").click();
    await vi.waitFor(() => {
      expect(emailPosts().length).toBe(1);
      expect(emailPosts()[0].body.confirm).toBe(true);
      expect(emailPosts()[0].body.to).toBe("hiring@acme.com");
      expect(emailPosts()[0].body.document_id).toBe("d1");
      expect(container.querySelector(".ppws-email").textContent)
        .toContain("Emailed to hiring@acme.com");
    }, { timeout: 3000 });
    root.unmount();
  });

  it("shows an honest not-configured line when mail is off", async () => {
    const calls = [];
    vi.stubGlobal("fetch", mockFetch(calls, { configured: false, from: "",
      missing: ["POCKETPROWS_SMTP_HOST", "POCKETPROWS_SMTP_USER", "POCKETPROWS_SMTP_PASSWORD"] }));
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(<App />);
    await openPack(container);
    await vi.waitFor(() => {
      expect(container.querySelector(".ppws-email").textContent).toContain("not configured yet");
      expect(container.querySelector(".ppws-email").textContent).toContain("POCKETPROWS_SMTP_HOST");
    }, { timeout: 3000 });
    expect([...container.querySelectorAll("button")].some((b) => b.textContent === "Review send")).toBe(false);
    root.unmount();
  });
});
