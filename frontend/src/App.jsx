import { useEffect, useState } from "react";

// PocketProWS — Recruiter Workstation, single-page dashboard.
//
// PROFILE model (Anthony, 2026-11-07): the PROFILE is the unit of
// separation. One profile holds exactly ONE client (the job seeker — the
// client seeks work; the employer hires), never two people in one profile.
// Each profile gets its own personal resources: work history, documents,
// interview answers, job search preferences, saved jobs, workflow, RAG.
// Profiles are kept strictly separate.
//
// HEADER: dynamically populated from the ACTIVE profile — GET
// /api/profiles/active — showing the active profile's client name, target
// roles, location/remote preference and workflow step. It is re-fetched
// every time the active profile is switched, created, edited, or an
// interview answer is saved, so it is never hard-coded and never stale.
// No client name is hard-coded anywhere in this file.
const WORKFLOW_LABELS = {
  interview: "Interview", documents: "Documents", preferences: "Preferences",
  job_search: "Job search", applications: "Applications", follow_up: "Follow-up",
};

export default function App() {
  const [ready, setReady] = useState(false);
  const [health, setHealth] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [activeId, setActiveId] = useState("");
  const [header, setHeader] = useState(null);
  const [active, setActive] = useState(null);
  const [newName, setNewName] = useState("");
  const [query, setQuery] = useState("AI Engineer");
  const [location, setLocation] = useState("Remote");
  const [results, setResults] = useState(null);
  const [chatQ, setChatQ] = useState("");
  const [chatA, setChatA] = useState(null);
  const [interview, setInterview] = useState(null);
  const [interviewA, setInterviewA] = useState("");
  const [docs, setDocs] = useState([]);
  const [docMsg, setDocMsg] = useState("");
  const [status, setStatus] = useState(null);
  const [agentMsg, setAgentMsg] = useState("");

  const loadStatus = async (id) => {
    if (!id) { setStatus(null); return; }
    const s = await fetch(`/api/profiles/${id}/status`).then((x) => x.json()).catch(() => null);
    setStatus(s && !s.detail ? s : null);
  };

  const loadProfiles = async () => {
    const r = await fetch("/api/profiles").then((x) => x.json()).catch(() => ({ profiles: [] }));
    setProfiles(r.profiles || []);
    return r.profiles || [];
  };

  // The header comes from the active profile endpoint — one source of truth.
  const loadHeader = async () => {
    const r = await fetch("/api/profiles/active").then((x) => x.json()).catch(() => null);
    if (!r) return null;
    setHeader(r.header);
    if (r.active_profile_id) setActiveId(r.active_profile_id);
    return r;
  };

  const loadActive = async (id) => {
    if (!id) { setActive(null); setInterview(null); setDocs([]); setHeader(null); return; }
    // Header first (fresh from the store), then every profile-scoped panel.
    await loadHeader();
    const p = await fetch(`/api/profiles/${id}`).then((x) => x.json()).catch(() => null);
    if (!p || p.detail) { setActive(null); setInterview(null); setDocs([]); return; }
    setActive(p);
    if (p?.header) setHeader(p.header);
    const iv = await fetch(`/api/profiles/${id}/interview`).then((x) => x.json()).catch(() => null);
    setInterview(iv);
    const d = await fetch(`/api/profiles/${id}/documents`).then((x) => x.json()).catch(() => ({ documents: [] }));
    setDocs(d.documents || []);
    loadStatus(id);
  };

  useEffect(() => {
    fetch("/api/health").then((r) => r.json()).then(setHealth).catch(() => null).finally(() => setReady(true));
    loadProfiles();
    loadHeader();
  }, []);

  useEffect(() => { if (activeId) loadActive(activeId); }, [activeId]);

  if (!ready) return <main><h1>PocketProWS</h1><p>Starting up…</p></main>;

  const switchProfile = async (id) => {
    if (!id) {
      await fetch("/api/profiles/active", { method: "DELETE" });
      setActiveId(""); setActive(null); setHeader(null); return;
    }
    // Tell the server which profile is active, then re-render everything
    // (header + all panels) from that profile's own data.
    await fetch("/api/profiles/active", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profile_id: id }) });
    setActiveId(id);
  };

  const createProfile = async () => {
    // An empty name is allowed: the interview's first question is the
    // client's name, so a nameless profile gets named on Q1.
    const r = await fetch("/api/profiles", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: newName }) });
    const p = await r.json();
    if (!p.id) return; // server rejected it (e.g. empty name) — stay put
    setNewName("");
    await loadProfiles();
    await switchProfile(p.id);
  };

  const deleteProfile = async () => {
    if (!activeId || !window.confirm(`Delete the profile for ${header?.client_name || "this client"} and all of their documents, interview answers and saved jobs?`)) return;
    await fetch(`/api/profiles/${activeId}`, { method: "DELETE" });
    await fetch("/api/profiles/active", { method: "DELETE" });
    setActiveId("");
    setHeader(null);
    await loadProfiles();
    await loadHeader();
  };

  const answerInterview = async () => {
    if (!interviewA.trim()) return;
    const r = await fetch(`/api/profiles/${activeId}/interview/answer`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answer: interviewA }) });
    const res = await r.json();
    if (res.error || res.detail) {
      setChatA({ answer: `⚠ ${res.error || res.detail}` });
    } else {
      setChatA({ answer: res.complete ? `All done — thank you! ${res.saved} ${res.summary || ""}` : `${res.saved} Next: ${res.next_question}` });
    }
    setInterviewA("");
    loadActive(activeId);
  };

  const ask = async () => {
    if (!chatQ.trim()) return;
    const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: chatQ, profile_id: activeId }) });
    setChatA(await r.json());
    setChatQ("");
  };

  const search = async () => {
    const r = await fetch(`/api/jobs/search?q=${encodeURIComponent(query)}&location=${encodeURIComponent(location)}&profile_id=${encodeURIComponent(activeId)}`);
    setResults(await r.json());
    if (activeId) loadActive(activeId);
  };

  const uploadDoc = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch(`/api/profiles/${activeId}/documents`, { method: "POST", body: fd });
    const res = await r.json();
    if (res.document) {
      const d = res.extracted || {};
      setDocMsg(`Added “${file.name}” — digested into ${header?.client_name || "this client"}'s resource. Found: skills ${d.skills?.join(", ") || "none"}, certifications ${d.certifications?.length || 0}, email ${d.email || "—"}.`);
    } else {
      setDocMsg(`Upload failed: ${res.detail || "unknown error"}`);
    }
    e.target.value = "";
    loadActive(activeId);
  };

  const editDoc = async (doc) => {
    const title = window.prompt("Document title:", doc.title);
    if (title === null) return;
    await fetch(`/api/profiles/${activeId}/documents/${doc.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) });
    loadActive(activeId);
  };

  const deleteDoc = async (doc) => {
    if (!window.confirm(`Delete “${doc.title}”? It will also be removed from this profile's RAG store.`)) return;
    await fetch(`/api/profiles/${activeId}/documents/${doc.id}`, { method: "DELETE" });
    loadActive(activeId);
  };

  const markStep = async (step) => {
    await fetch(`/api/profiles/${activeId}/workflow`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ step }) });
    loadActive(activeId);
  };

  // Workflow agents: run them on demand, then show what they reported.
  // The agents do the operable work (search, follow-ups, resource checks);
  // applying to an employer stays external — the app only records it.
  const runAgents = async () => {
    setAgentMsg("Agents running…");
    const r = await fetch(`/api/profiles/${activeId}/agents/run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
    const res = await r.json();
    setAgentMsg((res.reports || []).map((x) => x.summary).join(" "));
    loadActive(activeId);
  };

  const setJobStatus = async (job, next) => {
    await fetch(`/api/profiles/${activeId}/saved-jobs/${job.id}/status`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: next }) });
    loadActive(activeId);
  };

  const NEXT_STATUS = { saved: "applied", applied: "interviewing", interviewing: "offer", offer: "hired" };
  const NEXT_LABEL = { saved: "Mark applied", applied: "Mark interviewing", interviewing: "Mark offer", offer: "Mark hired" };

  const who = header?.client_name || (activeId ? "(name not set yet — answer the first interview question)" : "nobody yet");

  return (
    <main>
      <header id="top"><h1>PocketProWS — Recruiter Workstation</h1>
        <p>{health ? `Backend: ${health.status} · free sources: ${health.free_sources?.join(", ")}` : "Backend not reachable — search and chat will report honestly."}</p>
        <p><strong>Client: {who}</strong> — the client seeks work; the employer hires.</p>
        {header && (
          <p>
            {header.target_roles?.length ? `Target roles: ${header.target_roles.join(", ")}` : "Target roles: not set yet"}
            {header.location ? ` · Location: ${header.location}` : ""}
            {header.remote_preference ? ` (${header.remote_preference})` : ""}
            {header.employment_type ? ` · ${header.employment_type}` : ""}
            {header.current_step ? ` · Workflow: ${WORKFLOW_LABELS[header.current_step] || header.current_step}` : ""}
          </p>
        )}
      </header>

      <section>
        <h2>Who is our client?</h2>
        <p>One profile per client — each profile has its own work history, documents, interview, workflow and saved jobs. Pick a profile, or add a new one. Switching profiles re-loads the header and every panel from that profile's own data.</p>
        <select aria-label="active profile" value={activeId} onChange={(e) => switchProfile(e.target.value)}>
          <option value="">— choose a profile —</option>
          {profiles.map((p) => <option key={p.id} value={p.id}>{p.client?.name || p.id}</option>)}
        </select>
        <input aria-label="new profile client name" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="New client's name…" />
        <button onClick={createProfile}>Add profile</button>
        {activeId && <button onClick={deleteProfile}>Delete this profile</button>}
      </section>

      {active && active.workflow && (
        <section>
          <h2>Workflow — {header?.client_name || active.id}</h2>
          <p>Current step: <strong>{WORKFLOW_LABELS[active.workflow.current_step] || active.workflow.current_step}</strong></p>
          <ol>{active.workflow.steps.map((s) => (
            <li key={s.step}>{s.done ? "✓" : "○"} {WORKFLOW_LABELS[s.step]}
              {!s.done && (s.step === "applications" || s.step === "follow_up") && <button onClick={() => markStep(s.step)}>Mark done</button>}
            </li>))}</ol>
        </section>
      )}

      {activeId && status && (
        <section>
          <h2>Agents — workflow status for {status.client_name || activeId}</h2>
          <p>The agents run on demand and report here — the same status the concierge reports when you ask “what’s the status?” Applying to an employer stays outside the app; the agents record what happened, they never submit an application.</p>
          <button onClick={runAgents}>Run agents (search · application · follow-up · resources)</button>
          {agentMsg && <p>{agentMsg}</p>}
          {status.integrity && (status.integrity.passed
            ? <p>✓ Workflow integrity check: passed.</p>
            : <p>⚠ Workflow integrity check FAILED: {status.integrity.problems.join("; ")}</p>)}
          <p><strong>Pipeline:</strong> {status.pipeline.total} saved job(s) — {Object.entries(status.pipeline.counts).map(([k, v]) => `${v} ${k}`).join(", ")}.</p>
          {status.follow_ups_due.length > 0 ? (
            <div><p><strong>Follow-ups due ({status.follow_ups_due.length}):</strong></p>
              <ul>{status.follow_ups_due.map((f) => (
                <li key={f.job_id}>{f.title} — employer {f.company} ({f.status}, last change {f.last_status_at ? f.last_status_at.slice(0, 10) : "unknown"})
                  {f.draft && <p>Draft: {f.draft}</p>}
                </li>))}</ul></div>
          ) : <p>No follow-ups due right now.</p>}
          <p><strong>Resources:</strong> {status.resources.document_count} document(s), {status.resources.healthy_count} healthy in RAG, {status.resources.interview_notes_in_rag} interview note(s) in RAG.
            {status.resources.documents.filter((d) => d.status !== "ok").map((d) => ` ${d.title}: ${d.problems.join("; ")}.`)}
          </p>
          {status.last_runs.length > 0 && (
            <div><p><strong>Last agent runs:</strong></p>
              <ul>{status.last_runs.map((r, i) => <li key={i}>{r.agent} — {r.ran_at ? r.ran_at.slice(0, 16).replace("T", " ") : ""}: {r.summary}</li>)}</ul>
            </div>
          )}
          {status.saved_jobs.length > 0 && (
            <div><p><strong>Saved jobs — application status:</strong></p>
              <ul>{status.saved_jobs.map((j) => (
                <li key={j.id}>{j.title} — employer {j.company} · {j.application_status || "saved"}
                  {NEXT_STATUS[j.application_status || "saved"] && <button onClick={() => setJobStatus(j, NEXT_STATUS[j.application_status || "saved"])}>{NEXT_LABEL[j.application_status || "saved"]}</button>}
                  {(j.application_status || "saved") !== "rejected" && (j.application_status || "saved") !== "hired" && <button onClick={() => setJobStatus(j, "rejected")}>Mark rejected</button>}
                </li>))}</ul></div>
          )}
        </section>
      )}

      <section>
        <h2>Concierge recruiter</h2>
        <p>Hi! I'm your friendly recruiter concierge. On first load I ask who our client is — the client seeks work, the employer hires — then one question at a time. Each answer is saved into that profile's resource, and I tell you what I saved.</p>
        {activeId && interview && !interview.complete && (
          <div>
            <p><strong>Question {interview.step + 1} of {interview.total}:</strong> {interview.next_question}</p>
            <input aria-label="interview answer" value={interviewA} onChange={(e) => setInterviewA(e.target.value)} placeholder="Your answer…" />
            <button onClick={answerInterview}>Save answer</button>
          </div>
        )}
        {activeId && interview?.complete && <p>✓ Interview complete. {interview.summary}</p>}
        {!activeId && <p>Add or choose a profile above to start the interview.</p>}
        <input aria-label="concierge question" value={chatQ} onChange={(e) => setChatQ(e.target.value)} placeholder="Ask about a role, skill or location…" />
        <button onClick={ask}>Ask</button>
        {chatA && <p style={{ whiteSpace: "pre-line" }}>{chatA.answer}</p>}
      </section>

      {activeId && (
        <section>
          <h2>Profile documents — Add / Edit / Delete</h2>
          <p>You own these files. Add a resume, work history or certificate and I digest it into this profile's resource — skills, certifications, education — and into their RAG store. Edit renames a document; delete removes it from the resource and RAG too.</p>
          <label>Add a document: <input type="file" onChange={uploadDoc} /></label>
          {docMsg && <p>{docMsg}</p>}
          <ul>{docs.map((d) => (
            <li key={d.id}>{d.title} ({d.text_chars} chars digested)
              {d.digest?.skills?.length ? ` — skills: ${d.digest.skills.join(", ")}` : ""}
              <button onClick={() => editDoc(d)}>Edit</button>
              <button onClick={() => deleteDoc(d)}>Delete</button>
            </li>))}</ul>
          {!docs.length && <p>No documents yet for this profile.</p>}
        </section>
      )}

      <section>
        <h2>Job search {activeId ? `— for client ${header?.client_name || activeId}` : "(choose a profile first)"}</h2>
        <input aria-label="job query" value={query} onChange={(e) => setQuery(e.target.value)} />
        <input aria-label="location" value={location} onChange={(e) => setLocation(e.target.value)} />
        <button onClick={search}>Search jobs</button>
        {results && <p>{results.total} jobs found across {results.results.length} sources.</p>}
        {results && results.results.map((s) => (
          <div key={s.source}><h3>{s.source} — {s.status}{s.count ? ` (${s.count})` : ""}</h3>
            {s.message && <p>{s.message}</p>}
            <ul>{s.jobs.map((j) => <li key={j.id}><a href={j.url}>{j.title}</a> — employer {j.company} ({j.location})</li>)}</ul>
          </div>
        ))}
      </section>

      <section>
        <h2>Resources</h2>
        <p>Free sources (verified 2026-11-07): Adzuna, Jooble, USAJOBS (free keys) + Remotive, RemoteOK, Arbeitnow (no key). Indeed, Dice and Monster are gated — no public search API. Research doc: <code>your_files/pocketprows-job-board-apis-2026-11-07.md</code>.</p>
      </section>
    </main>
  );
}
