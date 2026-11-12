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

// Presentational only: photography + one-line guidance for the "How it
// works" workflow cards. No behavior reads these.
const HERO_IMAGE = "https://images.unsplash.com/photo-1497366216548-37526070297c?auto=format&fit=crop&w=2000&q=70";
const CONCIERGE_IMAGE = "https://images.unsplash.com/photo-1519389950473-47ba0277781c?auto=format&fit=crop&w=1200&q=70";
const STEP_IMAGES = {
  interview: "https://images.unsplash.com/photo-1521791136064-7986c2920216?auto=format&fit=crop&w=900&q=70",
  documents: "https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?auto=format&fit=crop&w=900&q=70",
  preferences: "https://images.unsplash.com/photo-1573164713988-8665fc963095?auto=format&fit=crop&w=900&q=70",
  job_search: "https://images.unsplash.com/photo-1486312338219-ce68d2c6f44d?auto=format&fit=crop&w=900&q=70",
  applications: "https://images.unsplash.com/photo-1434030216411-0b793f4b4173?auto=format&fit=crop&w=900&q=70",
  follow_up: "https://images.unsplash.com/photo-1423666639041-f56000c27a9a?auto=format&fit=crop&w=900&q=70",
};
const STEP_ALT = {
  interview: "A recruiter shaking hands with a client at the start of a conversation",
  documents: "A desk with a laptop, notebook and planning documents",
  preferences: "A professional working at a computer, setting her preferences",
  job_search: "Hands typing on a laptop, searching for roles",
  applications: "Writing application notes in a notebook beside a laptop",
  follow_up: "A phone call follow-up with notes on the desk",
};
const STEP_GUIDE = {
  interview: "Answer the concierge's questions one at a time — every answer is saved into the client's profile and shapes the search.",
  documents: "Add a resume, work history or certificates. Each file is digested into the skills and credentials the search can use.",
  preferences: "The interview fills in target roles, location and remote preference, so searches stay focused on the right openings.",
  job_search: "Search across the connected job sources and review the matches, grouped by where they came from.",
  applications: "Track each saved job as it moves from saved to applied, interviewing, offer and hired.",
  follow_up: "Run the agents to surface follow-ups that are due, use the drafts they prepare, and mark steps done as the work gets done.",
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
    <div className="ppws-app">
      <nav className="navbar sticky-top ppws-navbar">
        <div className="container d-flex align-items-center gap-2 flex-wrap py-1">
          <a className="navbar-brand ppws-brand" href="#top">PocketProWS <span className="ppws-brand-sub">— Recruiter Workstation</span></a>
          <div className="d-flex align-items-center gap-2 ms-auto flex-wrap">
            <span className={`badge ppws-status-pill ${health ? "is-up" : "is-down"}`} title={health ? `Backend: ${health.status} · free sources: ${health.free_sources?.join(", ")}` : "Backend not reachable — search and chat will report honestly."}>
              <span aria-hidden="true">●</span> {health ? `Backend: ${health.status}` : "Backend not reachable"}
              <span className="d-none d-xl-inline">{health ? ` · free sources: ${health.free_sources?.join(", ")}` : " — search and chat will report honestly."}</span>
            </span>
            <span className="badge ppws-client-chip">Client: {who}</span>
          </div>
        </div>
      </nav>

      <header className="ppws-hero" id="top" style={{ backgroundImage: `url(${HERO_IMAGE})` }}>
        <div className="ppws-hero-overlay">
          <div className="container">
            <div className="row align-items-center g-4">
              <div className="col-12 col-lg-7">
                <p className="ppws-eyebrow">Recruiter Workstation</p>
                <h1 className="ppws-hero-title">One client. One plan. Every step, guided.</h1>
                <p className="ppws-hero-sub">PocketProWS keeps each client&rsquo;s interview, documents, job search and follow-ups in one focused workspace — one profile per client, with the workflow laid out step by step.</p>
                <div className="d-flex flex-wrap gap-2">
                  <a className="btn ppws-btn-accent btn-lg" href="#client">Choose your client</a>
                  <a className="btn btn-outline-light btn-lg" href="#search">Search jobs</a>
                </div>
              </div>
              <div className="col-12 col-lg-5">
                <div className="ppws-glass-card">
                  <p className="ppws-glass-label">Active profile</p>
                  <p className="ppws-glass-client"><strong>Client: {who}</strong> — the client seeks work; the employer hires.</p>
                  {header && (
                    <p className="ppws-glass-summary">
                      {header.target_roles?.length ? `Target roles: ${header.target_roles.join(", ")}` : "Target roles: not set yet"}
                      {header.location ? ` · Location: ${header.location}` : ""}
                      {header.remote_preference ? ` (${header.remote_preference})` : ""}
                      {header.employment_type ? ` · ${header.employment_type}` : ""}
                      {header.current_step ? ` · Workflow: ${WORKFLOW_LABELS[header.current_step] || header.current_step}` : ""}
                    </p>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </header>

      <section className="ppws-section" aria-label="How it works">
        <div className="container">
          <div className="ppws-section-head">
            <p className="ppws-eyebrow ppws-eyebrow-dark">Workflow guidance</p>
            <h2 className="ppws-section-title">How it works — six guided steps</h2>
            <p className="ppws-section-sub">Every client moves through the same six steps. Here is what happens at each one.</p>
          </div>
          <div className="row g-4">
            {Object.keys(WORKFLOW_LABELS).map((step, i) => (
              <div className="col-12 col-sm-6 col-lg-4" key={step}>
                <article className="card ppws-step-card h-100">
                  <div className="ppws-step-media">
                    <img src={STEP_IMAGES[step]} alt={STEP_ALT[step]} loading="lazy" />
                    <span className="ppws-step-badge">Step {i + 1}</span>
                  </div>
                  <div className="card-body">
                    <h3 className="ppws-step-title">{WORKFLOW_LABELS[step]}</h3>
                    <p className="ppws-step-guide">{STEP_GUIDE[step]}</p>
                  </div>
                </article>
              </div>
            ))}
          </div>
        </div>
      </section>

      <main className="container ppws-main">
        <div className="row g-4">
          <div className="col-12 col-lg-5">
            <section className="card ppws-card h-100" id="client">
              <div className="card-body">
                <h2 className="ppws-card-title">Who is our client?</h2>
                <p>One profile per client — each profile has its own work history, documents, interview, workflow and saved jobs. Pick a profile, or add a new one. Switching profiles re-loads the header and every panel from that profile&rsquo;s own data.</p>
                <div className="row g-2">
                  <div className="col-12">
                    <select className="form-select" aria-label="active profile" value={activeId} onChange={(e) => switchProfile(e.target.value)}>
                      <option value="">— choose a profile —</option>
                      {profiles.map((p) => <option key={p.id} value={p.id}>{p.client?.name || p.id}</option>)}
                    </select>
                  </div>
                  <div className="col-12">
                    <input className="form-control" aria-label="new profile client name" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="New client's name…" />
                  </div>
                  <div className="col-12 d-flex flex-wrap gap-2">
                    <button className="btn ppws-btn-accent" onClick={createProfile}>Add profile</button>
                    {activeId && <button className="btn btn-outline-danger" onClick={deleteProfile}>Delete this profile</button>}
                  </div>
                </div>
              </div>
            </section>
          </div>

          {active && active.workflow && (
            <div className="col-12 col-lg-7">
              <section className="card ppws-card h-100">
                <div className="card-body">
                  <h2 className="ppws-card-title">Workflow — {header?.client_name || active.id}</h2>
                  <div className="d-flex flex-wrap justify-content-between align-items-baseline gap-2">
                    <p className="mb-1">Current step: <strong>{WORKFLOW_LABELS[active.workflow.current_step] || active.workflow.current_step}</strong></p>
                    <span className="ppws-progress-count">{active.workflow.steps.filter((s) => s.done).length} of {active.workflow.steps.length} steps done</span>
                  </div>
                  <div className="progress ppws-progress" role="progressbar" aria-label="Workflow progress" aria-valuenow={active.workflow.steps.filter((s) => s.done).length} aria-valuemin={0} aria-valuemax={active.workflow.steps.length}>
                    <div className="ppws-progress-bar" style={{ width: `${active.workflow.steps.length ? Math.round((active.workflow.steps.filter((s) => s.done).length / active.workflow.steps.length) * 100) : 0}%` }} />
                  </div>
                  <ol className="ppws-steps">{active.workflow.steps.map((s) => (
                    <li key={s.step} className={`ppws-step${s.done ? " is-done" : ""}${s.step === active.workflow.current_step ? " is-current" : ""}`}>
                      <span className="ppws-step-dot" aria-hidden="true">{s.done ? "✓" : "○"}</span>
                      <span className="ppws-step-name">{WORKFLOW_LABELS[s.step]}</span>
                      {s.step === active.workflow.current_step && <span className="badge ppws-current-badge">Current</span>}
                      {!s.done && (s.step === "applications" || s.step === "follow_up") && <button className="btn btn-sm ppws-btn-accent ms-auto" onClick={() => markStep(s.step)}>Mark done</button>}
                    </li>))}</ol>
                </div>
              </section>
            </div>
          )}

          {activeId && status && (
            <div className="col-12">
              <section className="card ppws-card">
                <div className="card-body">
                  <h2 className="ppws-card-title">Agents — workflow status for {status.client_name || activeId}</h2>
                  <p>The agents run on demand and report here — the same status the concierge reports when you ask “what’s the status?” Applying to an employer stays outside the app; the agents record what happened, they never submit an application.</p>
                  <button className="btn ppws-btn-accent" onClick={runAgents}>Run agents (search · application · follow-up · resources)</button>
                  {agentMsg && <p className="ppws-agent-msg">{agentMsg}</p>}
                  {status.integrity && (status.integrity.passed
                    ? <p className="alert alert-success ppws-alert" role="status">✓ Workflow integrity check: passed.</p>
                    : <p className="alert alert-danger ppws-alert" role="alert">⚠ Workflow integrity check FAILED: {status.integrity.problems.join("; ")}</p>)}
                  <p><strong>Pipeline:</strong> {status.pipeline.total} saved job(s) — {Object.entries(status.pipeline.counts).map(([k, v]) => `${v} ${k}`).join(", ")}.</p>
                  {status.follow_ups_due.length > 0 ? (
                    <div><p><strong>Follow-ups due ({status.follow_ups_due.length}):</strong></p>
                      <ul className="ppws-list">{status.follow_ups_due.map((f) => (
                        <li key={f.job_id}>{f.title} — employer {f.company} ({f.status}, last change {f.last_status_at ? f.last_status_at.slice(0, 10) : "unknown"})
                          {f.draft && <p className="ppws-draft">Draft: {f.draft}</p>}
                        </li>))}</ul></div>
                  ) : <p>No follow-ups due right now.</p>}
                  <p><strong>Resources:</strong> {status.resources.document_count} document(s), {status.resources.healthy_count} healthy in RAG, {status.resources.interview_notes_in_rag} interview note(s) in RAG.
                    {status.resources.documents.filter((d) => d.status !== "ok").map((d) => ` ${d.title}: ${d.problems.join("; ")}.`)}
                  </p>
                  {status.last_runs.length > 0 && (
                    <div><p><strong>Last agent runs:</strong></p>
                      <ul className="ppws-list">{status.last_runs.map((r, i) => <li key={i}>{r.agent} — {r.ran_at ? r.ran_at.slice(0, 16).replace("T", " ") : ""}: {r.summary}</li>)}</ul>
                    </div>
                  )}
                  {status.saved_jobs.length > 0 && (
                    <div><p><strong>Saved jobs — application status:</strong></p>
                      <ul className="ppws-list ppws-saved-jobs">{status.saved_jobs.map((j) => (
                        <li key={j.id}><span className="ppws-saved-job-text">{j.title} — employer {j.company} · {j.application_status || "saved"}</span>
                          {NEXT_STATUS[j.application_status || "saved"] && <button className="btn btn-sm btn-outline-primary" onClick={() => setJobStatus(j, NEXT_STATUS[j.application_status || "saved"])}>{NEXT_LABEL[j.application_status || "saved"]}</button>}
                          {(j.application_status || "saved") !== "rejected" && (j.application_status || "saved") !== "hired" && <button className="btn btn-sm btn-outline-danger" onClick={() => setJobStatus(j, "rejected")}>Mark rejected</button>}
                        </li>))}</ul></div>
                  )}
                </div>
              </section>
            </div>
          )}

          <div className="col-12 col-lg-7">
            <section className="card ppws-card h-100">
              <div className="card-body">
                <div className="row g-3">
                  <div className="col-12 col-md-8">
                    <h2 className="ppws-card-title">Concierge recruiter</h2>
                    <p>Hi! I&rsquo;m your friendly recruiter concierge. On first load I ask who our client is — the client seeks work, the employer hires — then one question at a time. Each answer is saved into that profile&rsquo;s resource, and I tell you what I saved.</p>
                    {activeId && interview && !interview.complete && (
                      <div className="ppws-interview">
                        <p><strong>Question {interview.step + 1} of {interview.total}:</strong> {interview.next_question}</p>
                        <div className="d-flex flex-column flex-sm-row gap-2">
                          <input className="form-control" aria-label="interview answer" value={interviewA} onChange={(e) => setInterviewA(e.target.value)} placeholder="Your answer…" />
                          <button className="btn ppws-btn-accent" onClick={answerInterview}>Save answer</button>
                        </div>
                      </div>
                    )}
                    {activeId && interview?.complete && <p className="alert alert-success ppws-alert" role="status">✓ Interview complete. {interview.summary}</p>}
                    {!activeId && <p>Add or choose a profile above to start the interview.</p>}
                    <div className="d-flex flex-column flex-sm-row gap-2">
                      <input className="form-control" aria-label="concierge question" value={chatQ} onChange={(e) => setChatQ(e.target.value)} placeholder="Ask about a role, skill or location…" />
                      <button className="btn ppws-btn-outline" onClick={ask}>Ask</button>
                    </div>
                    {chatA && <p className="ppws-chat-answer" style={{ whiteSpace: "pre-line" }}>{chatA.answer}</p>}
                  </div>
                  <div className="col-md-4 d-none d-md-block">
                    <img className="ppws-side-img" src={CONCIERGE_IMAGE} alt="A recruiting team collaborating around a table with laptops" loading="lazy" />
                  </div>
                </div>
              </div>
            </section>
          </div>

          {activeId && (
            <div className="col-12 col-lg-5">
              <section className="card ppws-card h-100">
                <div className="card-body">
                  <h2 className="ppws-card-title">Profile documents — Add / Edit / Delete</h2>
                  <p>You own these files. Add a resume, work history or certificate and I digest it into this profile&rsquo;s resource — skills, certifications, education — and into their RAG store. Edit renames a document; delete removes it from the resource and RAG too.</p>
                  <label className="form-label ppws-file-label">Add a document: <input className="form-control" type="file" onChange={uploadDoc} /></label>
                  {docMsg && <p className="ppws-doc-msg">{docMsg}</p>}
                  <ul className="ppws-list ppws-doc-list">{docs.map((d) => (
                    <li key={d.id}><span className="ppws-doc-text">{d.title} ({d.text_chars} chars digested)
                      {d.digest?.skills?.length ? ` — skills: ${d.digest.skills.join(", ")}` : ""}</span>
                      <span className="ppws-doc-actions">
                        <button className="btn btn-sm btn-outline-primary" onClick={() => editDoc(d)}>Edit</button>
                        <button className="btn btn-sm btn-outline-danger" onClick={() => deleteDoc(d)}>Delete</button>
                      </span>
                    </li>))}</ul>
                  {!docs.length && <p>No documents yet for this profile.</p>}
                </div>
              </section>
            </div>
          )}

          <div className="col-12">
            <section className="card ppws-card" id="search">
              <div className="card-body">
                <h2 className="ppws-card-title">Job search {activeId ? `— for client ${header?.client_name || activeId}` : "(choose a profile first)"}</h2>
                <div className="row g-2">
                  <div className="col-12 col-md-5">
                    <input className="form-control" aria-label="job query" value={query} onChange={(e) => setQuery(e.target.value)} />
                  </div>
                  <div className="col-12 col-md-4">
                    <input className="form-control" aria-label="location" value={location} onChange={(e) => setLocation(e.target.value)} />
                  </div>
                  <div className="col-12 col-md-3 d-grid">
                    <button className="btn ppws-btn-accent" onClick={search}>Search jobs</button>
                  </div>
                </div>
                {results && <p className="ppws-results-total">{results.total} jobs found across {results.results.length} sources.</p>}
                {results && results.results.map((s) => (
                  <div key={s.source} className="ppws-source-block"><h3 className="ppws-source-title">{s.source} — {s.status}{s.count ? ` (${s.count})` : ""}</h3>
                    {s.message && <p>{s.message}</p>}
                    <ul className="ppws-job-list">{s.jobs.map((j) => <li key={j.id}><a href={j.url}>{j.title}</a> — employer {j.company} ({j.location})</li>)}</ul>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <div className="col-12">
            <section className="card ppws-card">
              <div className="card-body">
                <h2 className="ppws-card-title">Resources</h2>
                <p>Free sources (verified 2026-11-07): Adzuna, Jooble, USAJOBS (free keys) + Remotive, RemoteOK, Arbeitnow (no key). Indeed, Dice and Monster are gated — no public search API. Research doc: <code>your_files/pocketprows-job-board-apis-2026-11-07.md</code>.</p>
                <div className="ppws-source-groups">
                  <p className="ppws-source-group"><span className="ppws-source-group-label">Free — API key:</span> <span className="badge ppws-source-badge">Adzuna</span> <span className="badge ppws-source-badge">Jooble</span> <span className="badge ppws-source-badge">USAJOBS</span></p>
                  <p className="ppws-source-group"><span className="ppws-source-group-label">Free — no key:</span> <span className="badge ppws-source-badge">Remotive</span> <span className="badge ppws-source-badge">RemoteOK</span> <span className="badge ppws-source-badge">Arbeitnow</span></p>
                  <p className="ppws-source-group"><span className="ppws-source-group-label">Gated — no public search API:</span> <span className="badge ppws-source-badge is-gated">Indeed</span> <span className="badge ppws-source-badge is-gated">Dice</span> <span className="badge ppws-source-badge is-gated">Monster</span></p>
                </div>
              </div>
            </section>
          </div>
        </div>
      </main>

      <footer className="ppws-footer">
        <div className="container d-flex flex-column flex-md-row justify-content-between align-items-md-center gap-2">
          <span className="ppws-footer-brand">PocketProWS — Recruiter Workstation</span>
          <span>One profile per client · The client seeks work; the employer hires</span>
          <a className="ppws-footer-link" href="#top">Back to top ↑</a>
        </div>
      </footer>
    </div>
  );
}
