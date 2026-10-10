import { GraduationCap } from "lucide-react";

export default function Login() {
  const begin = () => {
    const redirectUrl = window.location.origin + "/";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };
  return (
    <div className="login-page" data-testid="login-page">
      <div className="login-art">
        <div className="login-quote">
          "The best learning is a conversation with what you already know."
          <small>— Lumina learning principle</small>
        </div>
      </div>
      <div className="login-panel">
        <div className="brand login-brand">
          <span className="brand-mark">
            <GraduationCap size={20} />
          </span>
          <span>
            Lumina<small>ACADEMIC WORKSPACE</small>
          </span>
        </div>
        <div className="login-copy">
          <p className="eyebrow">Your course, grounded</p>
          <h1>Study with evidence.</h1>
          <p>
            Upload your lecture notes, textbooks, and slides. Lumina answers only from your own
            materials — every claim cited to a page you can open.
          </p>
          <button className="google-button" onClick={begin} data-testid="google-login-button">
            <span>G</span> Continue with Google <span>→</span>
          </button>
          <small className="login-note">
            Your materials and learning history are kept private to your account.
          </small>
        </div>
      </div>
    </div>
  );
}
