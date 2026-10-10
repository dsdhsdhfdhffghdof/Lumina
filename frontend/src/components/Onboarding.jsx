import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Upload, FileText, GraduationCap, LogOut, CheckCircle2, AlertCircle, Loader2, Trash2, RefreshCw } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const ACCEPT = ".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp,.tiff,.bmp";
const ALLOWED_EXT = [".pdf",".docx",".txt",".md",".png",".jpg",".jpeg",".webp",".tiff",".bmp"];

function fmtSize(n) {
  if (!n) return "";
  const k = 1024;
  if (n < k) return `${n} B`;
  if (n < k * k) return `${(n / k).toFixed(1)} KB`;
  return `${(n / (k * k)).toFixed(1)} MB`;
}

function MaterialRow({ m, onDelete, onRetry }) {
  const statusIcon = {
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
        {statusIcon}
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

export default function Onboarding({ user, onLogout, onComplete }) {
  const [materials, setMaterials] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef(null);
  const pollRef = useRef(null);

  const refresh = async () => {
    try {
      const r = await axios.get(`${API}/materials`);
      setMaterials(r.data.items);
      return r.data.items;
    } catch (e) {
      return [];
    }
  };

  useEffect(() => {
    refresh();
    return () => pollRef.current && clearInterval(pollRef.current);
  }, []);

  const hasReady = materials.some((m) => m.status === "ready");

  const doUpload = async (file) => {
    if (!file) return;
    const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
    if (!ALLOWED_EXT.includes(ext)) {
      toast.error("Only PDF, DOCX, TXT, MD, PNG, JPG, JPEG, WEBP, TIFF, or BMP are supported");
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
        onUploadProgress: (e) => {
          if (e.total) setProgress(Math.round((e.loaded / e.total) * 100));
        },
      });
      toast.success(`${file.name} uploaded`);
      const list = await refresh();
      if (list.some((m) => m.status === "ready")) {
        await onComplete?.();
      }
    } catch (e) {
      const msg = e?.response?.data?.detail || "Upload failed";
      toast.error(msg);
    } finally {
      setUploading(false);
      setProgress(0);
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer?.files?.[0];
    if (f) doUpload(f);
  };

  const onDelete = async (m) => {
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

  const start = async () => {
    const ok = await onComplete?.();
    if (!ok) toast.error("Upload at least one successfully processed document");
  };

  return (
    <div className="onboarding-page" data-testid="onboarding-page">
      <header className="onboarding-top">
        <div className="brand">
          <span className="brand-mark"><GraduationCap size={20} /></span>
          <span>Lumina<small>ACADEMIC WORKSPACE</small></span>
        </div>
        <button className="logout-text" onClick={onLogout} data-testid="onboarding-logout">
          <LogOut size={14} /> Sign out
        </button>
      </header>

      <main className="onboarding-main">
        <div className="onboarding-hero">
          <p className="eyebrow">Welcome, {user?.name?.split(" ")[0] || "friend"}</p>
          <h1>Give Lumina something to study with you.</h1>
          <p className="subtle">
            Upload a PDF, DOCX, TXT, or Markdown file from your course. Everything the tutor says
            will be grounded in your own materials, with the exact page cited.
          </p>
        </div>

        <div
          className={`upload-drop ${dragOver ? "over" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => fileRef.current?.click()}
          data-testid="upload-dropzone"
        >
          <input
            ref={fileRef}
            type="file"
            accept={ACCEPT}
            onChange={(e) => doUpload(e.target.files?.[0])}
            style={{ display: "none" }}
            data-testid="upload-file-input"
          />
          <div className="upload-ic"><Upload size={22} /></div>
          <b>{uploading ? "Uploading…" : "Drop a file here or click to choose"}</b>
          <small>PDF · DOCX · TXT · MD · PNG · JPG · WEBP (scanned docs & photos use built-in OCR) · up to 25 MB</small>
          {uploading && (
            <div className="progress-line" style={{ marginTop: 16 }}>
              <span style={{ width: `${progress}%` }} />
            </div>
          )}
        </div>

        {materials.length > 0 && (
          <section className="onboarding-list">
            <p className="eyebrow">Your uploads</p>
            {materials.map((m) => (
              <MaterialRow key={m.id} m={m} onDelete={onDelete} onRetry={onRetry} />
            ))}
          </section>
        )}

        <div className="onboarding-cta">
          <button
            className="button primary"
            disabled={!hasReady}
            onClick={start}
            data-testid="start-learning-button"
          >
            Start Learning <span>→</span>
          </button>
          {!hasReady && (
            <small className="subtle">
              At least one document must be successfully processed before you can begin.
            </small>
          )}
        </div>
      </main>
    </div>
  );
}
