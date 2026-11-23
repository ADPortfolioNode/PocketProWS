import { describe, expect, it, vi, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// Edit profile (2026-11-22): the hero's Active profile card gains an
// Edit profile form for the client's own facts (contact, roles,
// preferences, cover-letter settings). Saving PATCHes the profile;
// skills/certs/education stay document-derived and are not fields.

const HEADER = {
  client_name: "Test Client",
  target_roles: ["Python Developer"],
  location: "Queens, NY",
  remote_preference: "Remote",
  employment_type: "Full-time",
  current_step: "documents",
};

const STEPS = ["documents", "interview", "preferences", "job_search", "applications", "follow_up"]
  .map((step) => ({ step, done: false }));

const CLIENT = {
  name: "Test Client", current_role: "Freelance AI Consultant",
  target_roles: ["Python Developer"], skills: ["python"],
  work_history: [], certifications: [], education: [],
  location: "Queens, NY", remote_preference: "Remote",
  employment_type: "Full-time", salary_min: "", salary_max: "",
  salary_text: "", cover_letter_tone: "", cover_letter_highlights: "",
  email: "deoism@gmail.com", phone: "718-914-0413", linkedin: "", github: "",
};

const PROFILE = {
  id: "p1", name: "Test Client", header: HEADER, client: CLIENT,
  workflow: { current_step: "documents", steps: STEPS },
};

function mockFetch(calls) {
  const routes = {
    "/api/health": { status: "ok", app: "PocketProWS", free_sources: ["remoteok"] },
    "/api/profiles": { profiles: [{ id: "p1", name: "Test Client" }] },
    "/api/profiles/active": { active_profile_id: "p1", header: HEADER },
    "/api/profiles/p1": PROFILE,
    "/api/profiles/p1/interview": { complete: false, step: 0, total: 11,
                                    next_question: "Who is our client?", why: "Filing." },
    "/api/profiles/p1/documents": { documents: [] },
    "/api/profiles/p1/status": null,
    "/api/profiles/p1/chat": { messages: [] },
  };
  return vi.fn(async (url, opts = {}) => {
    const method = opts.method || "GET";
    calls.push({ url, method, body: opts.body ? JSON.parse(opts.body) : null });
    if (url === "/api/profiles/active" && method === "POST") {
      return { ok: true, status: 200, json: async () => ({ active_profile_id: "p1" }) };
    }
    if (url === "/api/profiles/p1" && method === "PATCH") {
      return { ok: true, status: 200, json: async () => PROFILE };
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

describe("edit profile", () => {
  it("opens prefilled, saves a corrected phone by PATCH, and closes", async () => {
    const calls = [];
    vi.stubGlobal("fetch", mockFetch(calls));
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(<App />);
    await vi.waitFor(() => {
      expect([...container.querySelectorAll("button")]
        .some((b) => b.textContent === "Edit profile")).toBe(true);
    }, { timeout: 3000 });
    [...container.querySelectorAll("button")]
      .find((b) => b.textContent === "Edit profile").click();
    await vi.waitFor(() => {
      expect(container.querySelector(".ppws-edit-form")).toBeTruthy();
    }, { timeout: 3000 });
    // Prefilled from the record — including the wrong phone on file.
    const labels = [...container.querySelectorAll(".ppws-edit-field")];
    const phoneInput = labels.find((l) => l.textContent.startsWith("Phone")).querySelector("input");
    expect(phoneInput.value).toBe("718-914-0413");
    // Skills are NOT an editable field — they come from documents.
    expect(labels.some((l) => l.textContent.startsWith("Skills"))).toBe(false);
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    setter.call(phoneInput, "718-914-0313");
    phoneInput.dispatchEvent(new Event("input", { bubbles: true }));
    [...container.querySelectorAll("button")]
      .find((b) => b.textContent === "Save profile").click();
    await vi.waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH" && c.url === "/api/profiles/p1");
      expect(patch).toBeTruthy();
      expect(patch.body.client.phone).toBe("718-914-0313");
      expect(patch.body.client.target_roles).toEqual(["Python Developer"]);
      expect(patch.body.name).toBe("Test Client");
    }, { timeout: 3000 });
    await vi.waitFor(() => {
      expect(container.querySelector(".ppws-edit-form")).toBeFalsy();
    }, { timeout: 3000 });
    root.unmount();
  });
});
