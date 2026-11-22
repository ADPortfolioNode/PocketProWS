import { describe, expect, it, vi, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// Document viewer test (2026-11-22): clicking a document's title
// views it — the extracted text and digest appear, with a link to
// the original file; clicking again closes the viewer.

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

const DOC = {
  id: "d1", title: "resume.txt", filename: "resume.txt", text_chars: 33,
  digest: { skills: ["python"], certifications: [], education: [], email: "a@b.c" },
};

function mockFetch() {
  const routes = {
    "/api/health": { status: "ok", app: "PocketProWS", free_sources: ["remoteok"] },
    "/api/profiles": { profiles: [{ id: "p1", name: "Test Client" }] },
    "/api/profiles/active": { active_profile_id: "p1", header: HEADER },
    "/api/profiles/p1": PROFILE,
    "/api/profiles/p1/interview": { complete: false, step: 0, total: 11,
                                    next_question: "Who is our client?", why: "Filing." },
    "/api/profiles/p1/documents": { documents: [DOC] },
    "/api/profiles/p1/documents/d1/view": {
      document: DOC, text: "Anthony Dickerson\nPython developer.",
      truncated: false, text_chars: 33,
    },
    "/api/profiles/p1/status": null,
    "/api/profiles/p1/chat": { messages: [] },
  };
  return vi.fn(async (url, opts = {}) => {
    const method = opts.method || "GET";
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

describe("document viewer", () => {
  it("clicking a document views it; clicking again closes it", async () => {
    vi.stubGlobal("fetch", mockFetch());
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(<App />);
    await vi.waitFor(() => {
      expect(container.querySelector(".ppws-doc-title-btn")).toBeTruthy();
    }, { timeout: 3000 });
    container.querySelector(".ppws-doc-title-btn").click();
    await vi.waitFor(() => {
      const view = container.querySelector(".ppws-doc-view");
      expect(view).toBeTruthy();
      expect(view.textContent).toContain("Python developer.");
      expect(view.textContent).toContain("skills: python");
      const link = view.querySelector("a");
      expect(link.getAttribute("href")).toBe("/api/profiles/p1/documents/d1/file");
    }, { timeout: 3000 });
    container.querySelector(".ppws-doc-title-btn").click();
    await vi.waitFor(() => {
      expect(container.querySelector(".ppws-doc-view")).toBeFalsy();
    }, { timeout: 3000 });
    root.unmount();
  });
});
