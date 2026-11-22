import { describe, expect, it, vi, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// Concierge chat tests (2026-11-22): the chat is a real conversation —
// a transcript of bubbles fed by the server's stored history, starter
// chips when empty, job cards under an answer, and a Clear chat.

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

const STATUS = {
  client_name: "Test Client",
  integrity: { passed: true, problems: [] },
  pipeline: { total: 0, counts: { saved: 0, applied: 0, interviewing: 0, offer: 0, hired: 0, rejected: 0 } },
  follow_ups_due: [],
  resources: { document_count: 0, healthy_count: 0, interview_notes_in_rag: 0, documents: [] },
  last_runs: [],
  saved_jobs: [],
};

function mockFetch() {
  let history = [];
  const routes = {
    "/api/health": { status: "ok", app: "PocketProWS", free_sources: ["remoteok"] },
    "/api/profiles": { profiles: [{ id: "p1", name: "Test Client" }] },
    "/api/profiles/active": { active_profile_id: "p1", header: HEADER },
    "/api/profiles/p1": PROFILE,
    "/api/profiles/p1/interview": { complete: false, step: 0, total: 11, next_question: "Who is our client?" },
    "/api/profiles/p1/documents": { documents: [] },
    "/api/profiles/p1/status": STATUS,
  };
  return vi.fn(async (url, opts = {}) => {
    const method = opts.method || "GET";
    if (url === "/api/profiles/p1/chat" && method === "GET") {
      return { ok: true, status: 200, json: async () => ({ messages: history }) };
    }
    if (url === "/api/profiles/p1/chat" && method === "DELETE") {
      history = [];
      return { ok: true, status: 200, json: async () => ({ messages: [] }) };
    }
    if (url === "/api/chat" && method === "POST") {
      const body = JSON.parse(opts.body);
      history = [...history,
        { role: "user", text: body.message },
        { role: "assistant", text: `Answer to: ${body.message}` }];
      return { ok: true, status: 200, json: async () => ({ answer: `Answer to: ${body.message}`, jobs: [], history }) };
    }
    if (url === "/api/profiles/active" && method === "POST") {
      return { ok: true, status: 200, json: async () => ({ active_profile_id: "p1" }) };
    }
    const data = routes[url];
    if (!data) return { ok: false, status: 404, json: async () => ({ detail: "not found" }) };
    return { ok: true, status: 200, json: async () => data };
  });
}

async function renderApp() {
  vi.stubGlobal("fetch", mockFetch());
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  root.render(<App />);
  await vi.waitFor(() => {
    expect(container.querySelectorAll(".ppws-steps .ppws-step").length).toBe(6);
  }, { timeout: 3000 });
  // The interview panel (which holds the chat) starts minimized.
  const openBtn = [...container.querySelectorAll("#interview button")]
    .find((b) => b.textContent.includes("Open this step"));
  openBtn.click();
  await vi.waitFor(() => {
    expect(container.querySelector('input[aria-label="concierge question"]')).toBeTruthy();
  }, { timeout: 3000 });
  return { container, root };
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

describe("concierge chat", () => {
  it("shows starter chips, then a real transcript after asking", async () => {
    const { container, root } = await renderApp();
    const chips = [...container.querySelectorAll(".ppws-chip")];
    expect(chips.length).toBe(3);
    chips.find((c) => c.textContent.includes("How are we doing?")).click();
    await vi.waitFor(() => {
      expect(container.querySelector(".ppws-msg-user")?.textContent).toContain("How are we doing?");
      expect(container.querySelector(".ppws-msg-bot")?.textContent).toContain("Answer to: How are we doing?");
    }, { timeout: 3000 });
    // Chips are gone once the conversation has started.
    expect(container.querySelectorAll(".ppws-chip").length).toBe(0);
    root.unmount();
  });

  it("sends a typed question with Enter-form submit and can clear the chat", async () => {
    const { container, root } = await renderApp();
    const input = container.querySelector('input[aria-label="concierge question"]');
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    setter.call(input, "Remote Python jobs");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    const form = input.closest("form");
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await vi.waitFor(() => {
      expect(container.querySelector(".ppws-msg-user")?.textContent).toContain("Remote Python jobs");
      expect(container.querySelector(".ppws-msg-bot")?.textContent).toContain("Answer to: Remote Python jobs");
    }, { timeout: 3000 });
    const clear = [...container.querySelectorAll("button")].find((b) => b.textContent === "Clear chat");
    expect(clear).toBeTruthy();
    clear.click();
    await vi.waitFor(() => {
      expect(container.querySelectorAll(".ppws-msg").length).toBe(0);
      expect(container.querySelectorAll(".ppws-chip").length).toBe(3);
    }, { timeout: 3000 });
    root.unmount();
  });
});
