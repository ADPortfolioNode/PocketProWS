import { describe, expect, it, vi, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// Concierge verbosity test (2026-11-22): the "Explain my workflow"
// chip returns the walkthrough into the transcript, and the interview
// panel shows why each question is asked.

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

const GUIDE = "Here's the workflow for Test Client, step by step:\n1. [→ you are here] Documents — the resume goes in first.";

function mockFetch() {
  const routes = {
    "/api/health": { status: "ok", app: "PocketProWS", free_sources: ["remoteok"] },
    "/api/profiles": { profiles: [{ id: "p1", name: "Test Client" }] },
    "/api/profiles/active": { active_profile_id: "p1", header: HEADER },
    "/api/profiles/p1": PROFILE,
    "/api/profiles/p1/interview": { complete: false, step: 0, total: 11,
                                    next_question: "Who is our client?",
                                    why: "Everything is filed under the client's name." },
    "/api/profiles/p1/documents": { documents: [] },
    "/api/profiles/p1/status": null,
    "/api/profiles/p1/chat": { messages: [] },
  };
  return vi.fn(async (url, opts = {}) => {
    const method = opts.method || "GET";
    if (url === "/api/chat" && method === "POST") {
      return { ok: true, status: 200, json: async () => ({ answer: GUIDE, jobs: [], mode: "guide",
               history: [{ role: "user", text: "Explain my workflow" }, { role: "assistant", text: GUIDE }] }) };
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

describe("concierge guide + why lines", () => {
  it("chip walkthrough lands in the transcript; interview shows its why", async () => {
    vi.stubGlobal("fetch", mockFetch());
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(<App />);
    await vi.waitFor(() => {
      expect(container.querySelectorAll(".ppws-steps .ppws-step").length).toBe(6);
    }, { timeout: 3000 });
    const openBtn = [...container.querySelectorAll("#interview button")]
      .find((b) => b.textContent.includes("Open this step"));
    openBtn.click();
    await vi.waitFor(() => {
      const why = container.querySelector(".ppws-why");
      expect(why).toBeTruthy();
      expect(why.textContent).toContain("filed under the client's name");
    }, { timeout: 3000 });
    const chip = [...container.querySelectorAll(".ppws-chip")].find((b) => b.textContent === "Explain my workflow");
    expect(chip).toBeTruthy();
    chip.click();
    await vi.waitFor(() => {
      const log = container.querySelector(".ppws-chat-log");
      expect(log.textContent).toContain("you are here");
      expect(log.textContent).toContain("the resume goes in first");
    }, { timeout: 3000 });
    root.unmount();
  });
});
