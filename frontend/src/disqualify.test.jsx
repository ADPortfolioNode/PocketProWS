import { describe, expect, it, vi, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// Disqualifier filter test (2026-11-22): search results report the
// omitted jobs with reasons, expandable — never silently dropped.

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
  query: "dev", location: "", total: 1, profile_id: "p1",
  results: [{ source: "fakeboard", status: "ok", message: "", count: 1,
              jobs: [{ id: "keep1", title: "Python Dev", company: "Acme", location: "Remote", url: "https://x/1" }] }],
  omitted: [{ id: "drop1", title: "Data Scientist", company: "Beta",
              reasons: ["Requires a doctorate degree — highest on file is associate"] }],
  omitted_count: 1,
};

function mockFetch() {
  const routes = {
    "/api/health": { status: "ok", app: "PocketProWS", free_sources: ["remoteok"] },
    "/api/profiles": { profiles: [{ id: "p1", name: "Test Client" }] },
    "/api/profiles/active": { active_profile_id: "p1", header: HEADER },
    "/api/profiles/p1": PROFILE,
    "/api/profiles/p1/interview": { complete: false, step: 0, total: 11, next_question: "Who is our client?" },
    "/api/profiles/p1/documents": { documents: [] },
    "/api/profiles/p1/status": null,
    "/api/profiles/p1/chat": { messages: [] },
  };
  return vi.fn(async (url, opts = {}) => {
    const method = opts.method || "GET";
    if (url.startsWith("/api/jobs/search")) {
      return { ok: true, status: 200, json: async () => SEARCH_RES };
    }
    if (url === "/api/profiles/active" && method === "POST") {
      return { ok: true, status: 200, json: async () => ({ active_profile_id: "p1" }) };
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

describe("disqualifier filter display", () => {
  it("reports omitted jobs with reasons, expandable", async () => {
    vi.stubGlobal("fetch", mockFetch());
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(<App />);
    await vi.waitFor(() => {
      expect(container.querySelectorAll(".ppws-steps .ppws-step").length).toBe(6);
    }, { timeout: 3000 });
    const openBtn = [...container.querySelectorAll("#search button")]
      .find((b) => b.textContent.includes("Open this step"));
    openBtn.click();
    await vi.waitFor(() => {
      expect([...container.querySelectorAll("#search button")].some((b) => b.textContent === "Search jobs")).toBe(true);
    }, { timeout: 3000 });
    [...container.querySelectorAll("#search button")].find((b) => b.textContent === "Search jobs").click();
    await vi.waitFor(() => {
      const block = container.querySelector(".ppws-omitted");
      expect(block).toBeTruthy();
      expect(block.textContent).toContain("1 job omitted");
      expect(block.textContent).toContain("would disqualify this client");
    }, { timeout: 3000 });
    [...container.querySelectorAll(".ppws-omitted button")].find((b) => b.textContent.includes("Show what was omitted")).click();
    await vi.waitFor(() => {
      expect(container.querySelector(".ppws-omitted").textContent).toContain("Data Scientist");
      expect(container.querySelector(".ppws-omitted").textContent).toContain("doctorate degree");
    }, { timeout: 3000 });
    root.unmount();
  });
});
