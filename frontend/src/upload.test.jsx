import { describe, expect, it, vi, afterEach } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// Choose-then-upload (2026-11-23): the file picker only STAGES the
// file — nothing is sent until the Upload file button is clicked.

const HEADER = {
  client_name: "Test Client", target_roles: [], location: "",
  remote_preference: "", employment_type: "", current_step: "documents",
};

const STEPS = ["documents", "interview", "preferences", "job_search", "applications", "follow_up"]
  .map((step) => ({ step, done: false }));

const PROFILE = {
  id: "p1", name: "Test Client", header: HEADER,
  client: { name: "Test Client", skills: [], certifications: [], education: [] },
  workflow: { current_step: "documents", steps: STEPS },
};

const DOC = {
  id: "d1", title: "resume.txt", filename: "resume.txt", text_chars: 33,
  digest: { skills: ["python"], certifications: [], education: [], email: "a@b.c" },
};

function mockFetch(calls) {
  let uploaded = false;
  const routes = {
    "/api/health": { status: "ok", app: "PocketProWS", free_sources: ["remoteok"] },
    "/api/profiles": { profiles: [{ id: "p1", name: "Test Client" }] },
    "/api/profiles/active": { active_profile_id: "p1", header: HEADER },
    "/api/profiles/p1": PROFILE,
    "/api/profiles/p1/interview": { complete: false, step: 0, total: 11,
                                    next_question: "Who is our client?", why: "Filing." },
    "/api/profiles/p1/status": null,
    "/api/profiles/p1/chat": { messages: [] },
  };
  return vi.fn(async (url, opts = {}) => {
    const method = opts.method || "GET";
    if (url === "/api/profiles/active" && method === "POST") {
      return { ok: true, status: 200, json: async () => ({ active_profile_id: "p1" }) };
    }
    if (url === "/api/profiles/p1/documents" && method === "POST") {
      calls.push({ url, method, body: opts.body });
      if (calls.failUpload) {
        return { ok: false, status: 500,
                 text: async () => "Internal Server Error",
                 json: async () => { throw new Error("not json"); } };
      }
      uploaded = true;
      const payload = { document: DOC,
        extracted: { skills: ["python"], certifications: [], email: "a@b.c" } };
      return { ok: true, status: 200, text: async () => JSON.stringify(payload),
               json: async () => payload };
    }
    if (url === "/api/profiles/p1/documents") {
      return { ok: true, status: 200,
               json: async () => ({ documents: uploaded ? [DOC] : [] }) };
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

describe("document upload", () => {
  it("stages the chosen file and sends it only on Upload file click", async () => {
    const calls = [];
    vi.stubGlobal("fetch", mockFetch(calls));
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(<App />);
    await vi.waitFor(() => {
      expect(container.querySelector('input[type="file"]')).toBeTruthy();
    }, { timeout: 3000 });
    const uploadBtn = [...container.querySelectorAll("button")]
      .find((b) => b.textContent === "Upload file");
    expect(uploadBtn).toBeTruthy();
    expect(uploadBtn.disabled).toBe(true); // nothing chosen yet
    const input = container.querySelector('input[type="file"]');
    const file = new File(["Anthony Dickerson\nPython"], "resume.txt", { type: "text/plain" });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    input.dispatchEvent(new Event("change", { bubbles: true }));
    await vi.waitFor(() => {
      expect(uploadBtn.disabled).toBe(false);
      expect(container.textContent).toContain("Ready: resume.txt");
    }, { timeout: 3000 });
    expect(calls.length).toBe(0); // choosing sent nothing
    uploadBtn.click();
    await vi.waitFor(() => {
      expect(calls.length).toBe(1);
      expect(calls[0].body).toBeInstanceOf(FormData);
      expect(container.querySelector(".ppws-doc-msg")?.textContent).toContain("Added");
    }, { timeout: 3000 });
    root.unmount();
  });

  it("reports the server's real failure instead of 'unknown error'", async () => {
    const calls = [];
    calls.failUpload = true;
    vi.stubGlobal("fetch", mockFetch(calls));
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(<App />);
    await vi.waitFor(() => {
      expect(container.querySelector('input[type="file"]')).toBeTruthy();
    }, { timeout: 3000 });
    const input = container.querySelector('input[type="file"]');
    const file = new File(["x"], "resume.pdf", { type: "application/pdf" });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    input.dispatchEvent(new Event("change", { bubbles: true }));
    const uploadBtn = [...container.querySelectorAll("button")]
      .find((b) => b.textContent === "Upload file");
    await vi.waitFor(() => { expect(uploadBtn.disabled).toBe(false); }, { timeout: 3000 });
    uploadBtn.click();
    await vi.waitFor(() => {
      const msg = container.querySelector(".ppws-doc-msg")?.textContent || "";
      expect(msg).toContain("Upload failed");
      expect(msg).toContain("500");
      expect(msg).not.toContain("unknown error");
    }, { timeout: 3000 });
    root.unmount();
  });
});
