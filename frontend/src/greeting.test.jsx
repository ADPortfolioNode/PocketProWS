import { describe, expect, it, vi, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// Greeting + avatar test (2026-11-22): the concierge speaks first —
// his greeting (seeded server-side into an empty transcript) renders
// as the first bubble — and his lens avatar sits by the panel title.

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

const GREETING = "Hello — I'm your concierge, working for Test Client. "
  + "We're at step 1 of 6: documents. It all starts with the resume — "
  + "shall we add it under Documents now?";

function mockFetch() {
  const routes = {
    "/api/health": { status: "ok", app: "PocketProWS", free_sources: ["remoteok"] },
    "/api/profiles": { profiles: [{ id: "p1", name: "Test Client" }] },
    "/api/profiles/active": { active_profile_id: "p1", header: HEADER },
    "/api/profiles/p1": PROFILE,
    "/api/profiles/p1/interview": { complete: false, step: 0, total: 11,
                                    next_question: "Who is our client?", why: "Filing." },
    "/api/profiles/p1/documents": { documents: [] },
    "/api/profiles/p1/status": null,
    "/api/profiles/p1/chat": { messages: [{ role: "assistant", text: GREETING }] },
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

describe("concierge greeting + avatar", () => {
  it("greets first in the transcript and wears his lens by the title", async () => {
    vi.stubGlobal("fetch", mockFetch());
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(<App />);
    // Documents is the focused step, so the Concierge panel starts
    // minimized — open it the way a user would.
    await vi.waitFor(() => {
      expect(container.querySelector("#interview button")).toBeTruthy();
    }, { timeout: 3000 });
    const openBtn = [...container.querySelectorAll("#interview button")]
      .find((b) => b.textContent.includes("Open this step"));
    openBtn.click();
    await vi.waitFor(() => {
      const log = container.querySelector(".ppws-chat-log");
      expect(log).toBeTruthy();
      expect(log.textContent).toContain("your concierge, working for Test Client");
      expect(log.textContent).toContain("shall we add it under Documents now?");
    }, { timeout: 3000 });
    const avatar = container.querySelector(".ppws-avatar .ppws-avatar-lens");
    expect(avatar).toBeTruthy();
    root.unmount();
  });
});
