import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  BookOpen, Brain, ChartNoAxesCombined, CircleHelp, FileText, GraduationCap,
  LayoutDashboard, Library, MessageCircle, Send, Sparkles, Target, Upload,
  Plus, X, CheckCircle2, AlertCircle, Loader2, Trash2, RefreshCw, LogOut, ShieldCheck
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const ACCEPT = ".pdf,.docx,.txt,.md";

const navItems = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "materials", label: "My materials", icon: Library },
  { id: "tutor", label: "Ask Lumina", icon: MessageCircle },
  { id: "assessment", label: "Assessments", icon: Target },
  { id: "mastery", label: "Mastery map", icon: Brain },
  { id: "evaluation", label: "Evaluation", icon: ChartNoAxesCombined },
];

function fmtSize(n) {
  if (!n) return "";
  const k = 1024;
  if (n < k) return `${n} B`;
  if (n < k * k) return `${(n / k).toFixed(1)} KB`;
  return `${(n / (k * k)).toFixed(1)} MB`;
}

function initials(name) {
  if (!name) return "L";
  const parts = name.trim().split(/\s+/);
  return (parts[0][0] + (parts[1]?.[0] || "")).toUpperCase();
}

function PageTitle({ eyebrow, title, detail, action }) {
  return (
    <div className="page-title">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {detail && <p className="subtle">{detail}</p>}
      </div>
      {action}
    </div>
  );
}

function MaterialRow({ m, onDelete, onRetry }) {
  const icon = {
    ready: <CheckCircle2 size={14} className="icon-ready" />,
    processing: <Loader2 size={14} className="icon-processing spin" />,
    failed: <AlertCircle size={14} className="icon-failed" />,
  }[m.status];
  return (
    <div className="material-row" data-testid={`material-${m.id}`}>
      <span className="file-icon terracotta"><FileText size={15} /></span>
      <div className="material-info">
        <b data-testid={`material-name-${m.id}`}>{m.filename}</b>
        <small>
          {m.type} · {fmtSize(m.size)}
          {m.status === "ready" && m.page_count ? ` · ${m.page_count} pages` : ""}
          {m.status === "failed" && m.error ? ` · ${m.error}` : ""}
        </small>
      </div>
      <span className={`material-status status-${m.status}`} data-testid={`material-status-${m.id}`}>
        {icon}
        {m.status === "ready" ? "Ready" : m.status === "processing" ? "Processing" : "Failed"}
      </span>
      {m.status === "failed" && (
        <button className="row-btn" onClick={() => onRetry(m)} data-testid={`retry-${m.id}`} title="Retry">
          <RefreshCw size={14} />
        </button>
      )}
      <button className="row-btn danger" onClick={() => onDelete(m)} data-testid={`delete-${m.id}`} title="Delete">
        <Trash2 size={14} />
      </button>
    </div>
  );
}

function UploadModal({ open, onClose, onUploaded }) {
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const inputRef = useRef(null);
  if (!open) return null;

  const doUpload = async (file) => {
    if (!file) return;
    const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
    if (![".pdf", ".docx", ".txt", ".md"].includes(ext)) {
      toast.error("Only PDF, DOCX, TXT, or MD");
      return;
    }
    if (file.size > 25 * 1024 * 1024) {
      toast.error("File is larger than 25 MB");
      return;
    }
    const body = new FormData();
    body.append("file", file);
    setUploading(true);
    setProgress(0);
    try {
      await axios.post(`${API}/materials/upload`, body, {
        onUploadProgress: (e) => e.total && setProgress(Math.round((e.loaded / e.total) * 100)),
      });
      toast.success(`${file.name} uploaded`);
      await onUploaded?.();
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="upload-modal" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} data-testid="close-upload"><X size={18} /></button>
        <div className="upload-icon"><Upload size={22} /></div>
        <h2>Add course material</h2>
        <p>Lumina will extract text and index it to pages so every answer can cite its source.</p>
        <label className="upload-zone" data-testid="upload-zone">
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            onChange={(e) => doUpload(e.target.files?.[0])}
            data-testid="upload-file-input"
          />
          <Upload size={22} />
          <b>{uploading ? `Uploading… ${progress}%` : "Choose a file"}</b>
          <span>PDF · DOCX · TXT · MD</span>
        </label>
      </div>
    </div>
  );
}

function Overview({ dashboard, materials, setView, setUploadOpen }) {
  const stats = [
    { label: "Materials ready", value: dashboard.ready_count || 0, note: `${dashboard.total_pages || 0} pages indexed`, icon: "✦" },
    { label: "Questions asked", value: dashboard.questions || 0, note: `${dashboard.grounded || 0} grounded`, icon: "◷" },
    { label: "Source confidence", value: `${dashboard.confidence || 0}%`, note: "Answers backed by your pages", icon: "✓" },
    { label: "Needs attention", value: materials.filter((m) => m.status !== "ready").length, note: "Failed or processing", icon: "↗", alert: materials.some((m) => m.status === "failed") },
  ];
  return (
    <>
      <PageTitle
        eyebrow="Your workspace"
        title="Grounded in your materials."
        detail="Every answer Lumina gives is based on documents you have uploaded — nothing else."
        action={
          <button className="button primary" onClick={() => setView("tutor")} data-testid="start-session-button">
            <MessageCircle size={16} /> Ask a question
          </button>
        }
      />
      <section className="hero-strip" data-testid="hero">
        <div>
          <p className="eyebrow light">Source-grounded tutor</p>
          <h2>Only your pages. Only your citations.</h2>
          <p>
            Lumina does not use outside knowledge. If something is not in your uploads, it will say so and
            point you to upload the relevant document.
          </p>
          <button className="text-button" onClick={() => setView("tutor")} data-testid="open-tutor-button">
            Open the tutor <span>→</span>
          </button>
        </div>
        <div className="ring">
          <strong data-testid="confidence-value">{dashboard.confidence || 0}%</strong>
          <span>grounded answers</span>
        </div>
      </section>

      <div className="stats-grid" data-testid="stats-grid">
        {stats.map((s) => (
          <div className="stat" key={s.label}>
            <span className={`stat-icon ${s.alert ? "alert" : ""}`}>{s.icon}</span>
            <div>
              <p>{s.label}</p>
              <strong>{s.value}</strong>
              <small>{s.note}</small>
            </div>
          </div>
        ))}
      </div>

      <div className="section-head">
        <div>
          <p className="eyebrow">Your sources</p>
          <h2>Course library</h2>
        </div>
        <button className="text-button" onClick={() => setView("materials")} data-testid="view-materials-link">
          Manage all →
        </button>
      </div>
      {materials.length === 0 ? (
        <div className="empty-block" data-testid="overview-empty">
          <p>You have no materials yet.</p>
          <button className="button outline" onClick={() => setUploadOpen(true)} data-testid="overview-add-material">
            <Plus size={14} /> Add your first document
          </button>
        </div>
      ) : (
        <div className="source-list">
          {materials.slice(0, 5).map((m) => (
            <div className="source-row" key={m.id} data-testid={`overview-source-${m.id}`}>
              <span className="file-icon terracotta"><FileText size={15} /></span>
              <div>
                <b>{m.filename}</b>
                <small>{m.type} · {m.page_count || 0} pages</small>
              </div>
              <span className={`ready status-${m.status}`}>
                {m.status === "ready" ? "Ready" : m.status === "processing" ? "Processing" : "Failed"}
              </span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function Materials({ materials, refresh, setUploadOpen }) {
  const onDelete = async (m) => {
    if (!window.confirm(`Delete "${m.filename}"? This also removes extracted pages.`)) return;
    try {
      await axios.delete(`${API}/materials/${m.id}`);
      toast.success("Removed");
      await refresh();
    } catch {
      toast.error("Could not delete");
    }
  };
  const onRetry = async (m) => {
    try {
      await axios.post(`${API}/materials/${m.id}/retry`);
      toast.success("Reprocessing");
      await refresh();
    } catch {
      toast.error("Retry failed");
    }
  };
  return (
    <>
      <PageTitle
        eyebrow="Private knowledge base"
        title="My materials"
        detail="Only you can read or ask questions about these documents."
        action={
          <button className="button primary" onClick={() => setUploadOpen(true)} data-testid="add-material-button">
            <Upload size={16} /> Add material
          </button>
        }
      />
      <div className="source-banner" data-testid="materials-banner">
        <div className="source-banner-icon"><ShieldCheck size={20} /></div>
        <div>
          <b>Private to your account</b>
          <p>Files are stored in managed object storage. Downloads require your session.</p>
        </div>
        <span data-testid="materials-count">
          {materials.length} file{materials.length === 1 ? "" : "s"}
        </span>
      </div>
      {materials.length === 0 ? (
        <div className="empty-block" data-testid="materials-empty">
          <p>No documents yet.</p>
        </div>
      ) : (
        <div className="material-list" data-testid="material-list">
          {materials.map((m) => (
            <MaterialRow key={m.id} m={m} onDelete={onDelete} onRetry={onRetry} />
          ))}
        </div>
      )}
    </>
  );
}

function Tutor({ user, materials }) {
  const [chat, setChat] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    axios
      .get(`${API}/tutor/history`)
      .then((r) => {
        const items = r.data.items || [];
        const rendered = [];
        items.forEach((it) => {
          rendered.push({ role: "user", text: it.question });
          rendered.push({ role: "assistant", text: it.answer, citations: it.citations || [], grounded: it.grounded });
        });
        setChat(rendered);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [chat.length, busy]);

  const send = async () => {
    const q = draft.trim();
    if (!q || busy) return;
    setDraft("");
    setChat((c) => [...c, { role: "user", text: q }]);
    setBusy(true);
    try {
      const r = await axios.post(`${API}/tutor/chat`, { message: q });
      setChat((c) => [
        ...c,
        { role: "assistant", text: r.data.answer, citations: r.data.citations || [], grounded: r.data.grounded },
      ]);
    } catch (e) {
      setChat((c) => [...c, { role: "assistant", text: "The tutor is temporarily unavailable. Please try again.", citations: [], grounded: false }]);
    } finally {
      setBusy(false);
    }
  };

  const ready = materials.filter((m) => m.status === "ready");
  const presetPrompts = ready.length
    ? [`Summarize the key ideas in ${ready[0].filename}`, `What are the main concepts in page 1 of ${ready[0].filename}?`]
    : [];

  return (
    <>
      <PageTitle
        eyebrow="Source-grounded tutor"
        title="Ask Lumina"
        detail="Answers come only from your uploaded documents — with page citations."
        action={<span className="grounded-pill" data-testid="grounded-mode-pill"><i /> Upload-grounded mode</span>}
      />
      <div className="tutor-layout">
        <div className="chat-panel" data-testid="chat-panel">
          <div className="chat-scroll" ref={scrollRef}>
            {chat.length === 0 && (
              <div className="empty-chat">
                <div className="tutor-emblem"><MessageCircle size={25} /></div>
                <h2>What are you studying?</h2>
                <p>Ask a question from your materials. Every answer cites the exact page.</p>
                {presetPrompts.length > 0 && (
                  <div className="prompt-row">
                    {presetPrompts.map((p, i) => (
                      <button
                        key={i}
                        onClick={() => setDraft(p)}
                        data-testid={`prompt-${i}`}
                      >
                        {p}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            {chat.map((m, i) => (
              <div key={i} className={`bubble ${m.role}`} data-testid={`chat-message-${i}`}>
                <span>{m.role === "user" ? initials(user?.name) : "L"}</span>
                <div>
                  <p data-testid={`chat-text-${i}`}>{m.text}</p>
                  {m.role === "assistant" && m.citations?.length > 0 && (
                    <div className="citations-list" data-testid={`citations-${i}`}>
                      <div className="citation-head">
                        <FileText size={13} />
                        <b>Evidence</b>
                      </div>
                      {m.citations.map((c, j) => (
                        <div key={j} className="citation-item" data-testid={`citation-${i}-${j}`}>
                          <b>{c.filename}, p.{c.page}</b>
                          <small>{c.excerpt}…</small>
                        </div>
                      ))}
                    </div>
                  )}
                  {m.role === "assistant" && !m.grounded && m.citations?.length === 0 && (
                    <div className="not-covered-tag" data-testid={`not-covered-${i}`}>
                      <AlertCircle size={13} /> No evidence in your uploads
                    </div>
                  )}
                </div>
              </div>
            ))}
            {busy && (
              <div className="bubble assistant" data-testid="chat-thinking">
                <span>L</span>
                <div><p className="thinking"><Loader2 size={14} className="spin" /> Searching your materials…</p></div>
              </div>
            )}
          </div>
          <div className="composer">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder={ready.length ? "Ask a question grounded in your materials…" : "Upload a document first"}
              disabled={!ready.length}
              data-testid="tutor-input"
            />
            <button onClick={send} disabled={!ready.length || !draft.trim() || busy} data-testid="tutor-send-button">
              <Send size={17} />
            </button>
          </div>
        </div>
        <aside className="context-panel" data-testid="context-panel">
          <p className="eyebrow">In this workspace</p>
          <h3>Your materials</h3>
          {ready.length === 0 && <p className="subtle">Upload a document to start asking questions.</p>}
          {ready.map((m) => (
            <div className="context-card" key={m.id} data-testid={`context-${m.id}`}>
              <b>{m.filename}</b>
              <small>{m.page_count || 0} pages indexed</small>
            </div>
          ))}
        </aside>
      </div>
    </>
  );
}

function Placeholder({ eyebrow, title, note }) {
  return (
    <>
      <PageTitle eyebrow={eyebrow} title={title} detail={note} />
      <div className="placeholder" data-testid="placeholder">
        <Sparkles size={18} />
        <p>
          Coming in a future iteration: this view will be rebuilt on top of your uploaded materials
          so questions, mastery, and metrics are grounded in your own study content.
        </p>
      </div>
    </>
  );
}

export default function Workspace({ user, onLogout }) {
  const [view, setView] = useState("overview");
  const [materials, setMaterials] = useState([]);
  const [dashboard, setDashboard] = useState({ ready_count: 0, total_pages: 0, questions: 0, grounded: 0, confidence: 0 });
  const [uploadOpen, setUploadOpen] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);

  const refresh = async () => {
    try {
      const [m, d] = await Promise.all([axios.get(`${API}/materials`), axios.get(`${API}/dashboard`)]);
      setMaterials(m.data.items);
      setDashboard(d.data);
    } catch {
      // auth will push user back to login via interceptor
    }
  };

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 8000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="shell" data-testid="workspace-shell">
      <aside className={`sidebar ${mobileNav ? "open" : ""}`} data-testid="sidebar">
        <div className="brand">
          <span className="brand-mark"><GraduationCap size={20} /></span>
          <span>Lumina<small>ACADEMIC WORKSPACE</small></span>
        </div>
        <p className="eyebrow nav-label">Your workspace</p>
        <nav>
          {navItems.map((n) => {
            const I = n.icon;
            return (
              <button
                key={n.id}
                className={view === n.id ? "nav-active" : ""}
                onClick={() => { setView(n.id); setMobileNav(false); }}
                data-testid={`nav-${n.id}`}
              >
                <I size={17} />
                {n.label}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="profile-block">
            <span className="profile-avatar" data-testid="profile-initials">{initials(user?.name)}</span>
            <div>
              <b data-testid="profile-name">{user?.name || "Student"}</b>
              <small data-testid="profile-email">{user?.email || ""}</small>
            </div>
          </div>
          <button className="logout-btn" onClick={onLogout} data-testid="logout-button">
            <LogOut size={14} /> Sign out
          </button>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <button className="mobile-nav-toggle" onClick={() => setMobileNav(!mobileNav)} data-testid="mobile-nav-toggle">
            <GraduationCap size={19} /> Lumina
          </button>
          <div className="top-actions">
            <span className="status" data-testid="synced-status"><i /> Materials private · you only</span>
            <button className="icon-btn" title="Help" data-testid="help-button"><CircleHelp size={18} /></button>
            <button className="avatar" onClick={onLogout} data-testid="profile-button" title="Sign out">
              {initials(user?.name)}
            </button>
          </div>
        </header>
        <div className="content">
          {view === "overview" && <Overview dashboard={dashboard} materials={materials} setView={setView} setUploadOpen={setUploadOpen} />}
          {view === "materials" && <Materials materials={materials} refresh={refresh} setUploadOpen={setUploadOpen} />}
          {view === "tutor" && <Tutor user={user} materials={materials} />}
          {view === "assessment" && <Placeholder eyebrow="Adaptive assessment" title="Checkpoint studio" note="Will generate quizzes from your own uploaded materials." />}
          {view === "mastery" && <Placeholder eyebrow="Learner model" title="Mastery map" note="Tracks per-topic understanding across questions you ask about your materials." />}
          {view === "evaluation" && <Placeholder eyebrow="System evaluation" title="Trust, measured" note="Faithfulness, precision, and recall against your uploads." />}
        </div>
      </main>

      <UploadModal open={uploadOpen} onClose={() => setUploadOpen(false)} onUploaded={refresh} />
    </div>
  );
}
