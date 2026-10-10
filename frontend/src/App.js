import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { BrowserRouter, useLocation, useNavigate } from "react-router-dom";
import { GraduationCap } from "lucide-react";
import { Toaster } from "sonner";
import Login from "./components/Login";
import Workspace from "./components/Workspace";
import Onboarding from "./components/Onboarding";
import "@/App.css";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
axios.defaults.withCredentials = true;

function AuthCallback() {
  const location = useLocation();
  const navigate = useNavigate();
  const processed = useRef(false);
  useEffect(() => {
    if (processed.current) return;
    processed.current = true;
    const sessionId = new URLSearchParams(location.hash.replace(/^#/, "")).get("session_id");
    if (!sessionId) {
      navigate("/", { replace: true });
      return;
    }
    axios
      .post(`${API}/auth/session`, { session_id: sessionId })
      .then(() => navigate("/", { replace: true }))
      .catch(() => navigate("/", { replace: true }));
  }, [location.hash, navigate]);
  return (
    <div className="auth-loading" data-testid="auth-loading">
      <GraduationCap size={28} />
      <p>Opening your learning workspace…</p>
    </div>
  );
}

function AuthRouter() {
  const location = useLocation();
  const hasHash = location.hash?.includes("session_id=");
  const [user, setUser] = useState(null);
  const [onboarded, setOnboarded] = useState(null);
  const [checking, setChecking] = useState(true);

  const refreshOnboarding = async () => {
    try {
      const r = await axios.get(`${API}/onboarding/status`);
      setOnboarded(r.data.onboarded);
      return r.data.onboarded;
    } catch {
      setOnboarded(false);
      return false;
    }
  };

  useEffect(() => {
    if (hasHash) return;
    axios
      .get(`${API}/auth/me`)
      .then(async (r) => {
        setUser(r.data);
        await refreshOnboarding();
      })
      .catch(() => setUser(false))
      .finally(() => setChecking(false));
  }, [hasHash]);

  const logout = async () => {
    try {
      await axios.post(`${API}/auth/logout`, {});
    } finally {
      setUser(false);
      setOnboarded(null);
    }
  };

  if (hasHash) return <AuthCallback />;
  if (checking)
    return (
      <div className="auth-loading" data-testid="auth-loading">
        <GraduationCap size={28} />
        <p>Preparing your workspace…</p>
      </div>
    );
  if (!user) return <Login />;
  if (!onboarded) return <Onboarding user={user} onLogout={logout} onComplete={refreshOnboarding} />;
  return <Workspace user={user} onLogout={logout} />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Toaster position="top-right" richColors />
      <AuthRouter />
    </BrowserRouter>
  );
}
