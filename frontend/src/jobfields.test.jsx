import { describe, expect, it, vi, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// Missing-fields flags on search results (2026-11-25): each post
// shows what it does not carry, and the filled application email
// when the posting printed one.

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

const SEARCH_RES = {
  query: "dev", location: "", total: 2, profile_id: "p1",
  results: [{ source: "fakeboard", status: "ok", message: "", count: 2,
    jobs: [
      { id: "thin1", title: "Python Dev", company: "Acme", location: "Remote", url: "https://x/1",
        missing_fields: ["application email", "salary"] },
      { id: "full1", title: "AI Engineer", company: "Beta", location: "New York, NY", url: "https://x/2",
        application_email: "jobs@beta.com", missing_fields: [] },
    ] }],
  omitted: [],
  omitted_count: 0,
};

function mockFetch() {
  const routes = {
    "/api/health": { status: "ok", app: "PocketProWS", free_sources: ["remoteok"] },
    "/api/profiles": { profiles: [{ id: "p1", name: "Test Client" }] },
    "/api/profiles/active": { active_profile_id: "p1", header: HEADER },
    "/api/profiles/p1": PROFILE,
    "/api/profiles/p1/interview": { complete: false, step: 0, total: 12, next_question: "Who is our client?" },
    "/api/profiles/p1/documents": { documents: [] },
    "/api/profiles/p1/status": null,
    "/api/profiles/p1/chat": { messages: [] },
  };
  return vi.fn(async (url, opts = {}) => {
    if (url.startsWith("/api/jobs/search")) {
      return { ok: true, status: 200, json: async () => SEARCH_RES };
    }
    const data = routes[url];
    if (data === null || data === undefined) return { ok: false, status: 404, json: async () => ({ detail: "not found" }) };
    return { ok: true, status: 200, json: async () => data };
  });
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

describe("missing fields on search results", () => {
  it("flags what a thin post lacks and shows the filled email on a full one", async () => {
    vi.stubGlobal("fetch", mockFetch());
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(<App />);
    await vi.waitFor(() => {
      expect(container.querySelectorAll(".ppws-rail-step").length).toBe(6);
    }, { timeout: 3000 });
    const openBtn = [...container.querySelectorAll("#search button")]
      .find((b) => b.textContent.includes("Open this step"));
    openBtn.click();
    await vi.waitFor(() => {
      expect([...container.querySelectorAll("#search button")].some((b) => b.textContent === "Search jobs")).toBe(true);
    }, { timeout: 3000 });
    [...container.querySelectorAll("#search button")].find((b) => b.textContent === "Search jobs").click();
    await vi.waitFor(() => {
      const items = [...container.querySelectorAll(".ppws-job-list li")];
      expect(items.length).toBe(2);
      expect(items[0].querySelector(".ppws-job-missing").textContent).toContain("Missing: application email, salary");
      expect(items[0].querySelector(".ppws-job-email")).toBeNull();
      expect(items[1].querySelector(".ppws-job-missing")).toBeNull();
      expect(items[1].querySelector(".ppws-job-email").textContent).toContain("Apply by email: jobs@beta.com");
    }, { timeout: 3000 });
    root.unmount();
  });
});
