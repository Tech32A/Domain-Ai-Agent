import { useState, useEffect, useCallback } from "react";

const API = "http://localhost:8000/api";

const fmt_k = (n) => !n ? "—" : n >= 1000 ? `$${(n/1000).toFixed(0)}K` : `$${n}`;

const VERTICAL_COLORS = {
  healthcare: "#00C9A7", legal: "#6C63FF",
  finance: "#FFB347",    education: "#FF6B9D",
};

const TYPE_BADGE = {
  unregistered: { label: "NEW",    color: "#00C9A7" },
  expiring:     { label: "DROP",   color: "#FFB347" },
  aftermarket:  { label: "MKT",    color: "#6C63FF" },
};

const TREND_COLORS = {
  "🚀 BREAKOUT":  "#FF6B9D",
  "📈 RISING":    "#00C9A7",
  "➡ STABLE":    "#666",
  "📉 DECLINING": "#FF4466",
  "💀 DEAD":      "#444",
  "🌲 EVERGREEN": "#00C9A7",
};

function StatCard({ label, value, color = "#fff", sub }) {
  return (
    <div style={{
      background: "#0D0D18", border: "1px solid #ffffff10",
      borderRadius: "10px", padding: "16px 20px", minWidth: "110px"
    }}>
      <div style={{ fontSize: "22px", fontWeight: "800", color }}>{value ?? "—"}</div>
      <div style={{ fontSize: "10px", color: "#555", letterSpacing: "2px", marginTop: "2px" }}>{label}</div>
      {sub && <div style={{ fontSize: "10px", color: "#444", marginTop: "2px" }}>{sub}</div>}
    </div>
  );
}

function DomainRow({ d, onRegister }) {
  const [expanded, setExpanded] = useState(false);
  const type = TYPE_BADGE[d.type] || { label: "?", color: "#666" };
  const trendColor = TREND_COLORS[d.trend_label] || "#666";
  const scoreColor = d.score >= 90 ? "#FF6B9D" : d.score >= 80 ? "#FFB347" : d.score >= 70 ? "#00C9A7" : "#555";

  return (
    <>
      <tr
        onClick={() => setExpanded(!expanded)}
        style={{
          borderBottom: "1px solid #ffffff06",
          cursor: "pointer",
          background: expanded ? "#ffffff05" : "transparent",
          transition: "background 0.15s"
        }}
      >
        <td style={{ padding: "12px 16px", fontFamily: "monospace", color: "#fff", fontSize: "13px" }}>
          <span style={{
            display: "inline-block", width: "6px", height: "6px",
            borderRadius: "50%", background: type.color,
            marginRight: "10px", boxShadow: `0 0 6px ${type.color}80`
          }} />
          {d.domain}
        </td>
        <td style={{ padding: "12px 8px", textAlign: "center" }}>
          <span style={{
            fontSize: "9px", padding: "2px 7px",
            background: `${type.color}15`, border: `1px solid ${type.color}40`,
            borderRadius: "3px", color: type.color, letterSpacing: "1px"
          }}>{type.label}</span>
        </td>
        <td style={{ padding: "12px 8px", textAlign: "center" }}>
          <span style={{ fontSize: "14px", fontWeight: "800", color: scoreColor }}>{d.score}</span>
        </td>
        <td style={{ padding: "12px 8px", textAlign: "right", color: "#888", fontSize: "12px", fontFamily: "monospace" }}>
          {fmt_k(d.est_low)}–{fmt_k(d.est_high)}
        </td>
        <td style={{ padding: "12px 8px", textAlign: "right", color: "#00C9A7", fontSize: "12px", fontFamily: "monospace" }}>
          {d.suggested_ask ? fmt_k(d.suggested_ask) : "—"}
        </td>
        <td style={{ padding: "12px 8px", textAlign: "center", fontSize: "11px", color: trendColor }}>
          {d.trend_label || "—"}
        </td>
        <td style={{ padding: "12px 16px", textAlign: "right" }}>
          <button
            onClick={(e) => { e.stopPropagation(); onRegister(d.domain); }}
            style={{
              padding: "4px 10px", background: "#6C63FF20",
              border: "1px solid #6C63FF40", borderRadius: "4px",
              color: "#6C63FF", fontSize: "10px", cursor: "pointer",
              fontFamily: "monospace", letterSpacing: "1px"
            }}
          >REG →</button>
        </td>
      </tr>
      {expanded && (
        <tr style={{ background: "#080810" }}>
          <td colSpan={7} style={{ padding: "12px 32px 16px" }}>
            <div style={{ display: "flex", gap: "32px", flexWrap: "wrap", fontSize: "11px" }}>
              {d.price_basis && (
                <div>
                  <div style={{ color: "#555", marginBottom: "4px", letterSpacing: "1px" }}>PRICE BASIS</div>
                  <div style={{ color: "#888" }}>{d.price_basis}</div>
                  <div style={{ color: "#555", marginTop: "2px" }}>Confidence: {d.price_confidence}</div>
                </div>
              )}
              {d.trend_keyword && (
                <div>
                  <div style={{ color: "#555", marginBottom: "4px", letterSpacing: "1px" }}>TREND DATA</div>
                  <div style={{ color: "#888" }}>Keyword: "{d.trend_keyword}"</div>
                  <div style={{ color: "#555" }}>Velocity: {d.trend_velocity > 0 ? "+" : ""}{d.trend_velocity}%</div>
                </div>
              )}
              {d.registrar && (
                <div>
                  <div style={{ color: "#555", marginBottom: "4px", letterSpacing: "1px" }}>REGISTRAR</div>
                  <div style={{ color: "#888" }}>{d.registrar}</div>
                  {d.expiry_date && <div style={{ color: "#555" }}>Expires: {d.expiry_date?.slice(0,10)}</div>}
                </div>
              )}
              {d.first_seen && (
                <div>
                  <div style={{ color: "#555", marginBottom: "4px", letterSpacing: "1px" }}>FIRST SEEN</div>
                  <div style={{ color: "#888" }}>{d.first_seen?.slice(0,10)}</div>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function App() {
  const [domains,    setDomains]    = useState([]);
  const [stats,      setStats]      = useState({});
  const [loading,    setLoading]    = useState(true);
  const [scanning,   setScanning]   = useState(false);
  const [filter,     setFilter]     = useState({ type: "all", minScore: 0, sort: "score" });
  const [search,     setSearch]     = useState("");
  const [toast,      setToast]      = useState(null);
  const [activeTab,  setActiveTab]  = useState("domains");

  const showToast = (msg, color = "#00C9A7") => {
    setToast({ msg, color });
    setTimeout(() => setToast(null), 3000);
  };

  const fetchData = useCallback(async () => {
    try {
      const [domainsRes, statsRes] = await Promise.all([
        fetch(`${API}/domains?limit=200&sort=${filter.sort}&min_score=${filter.minScore}`),
        fetch(`${API}/stats`),
      ]);
      if (domainsRes.ok) {
        const d = await domainsRes.json();
        setDomains(d.domains || []);
      }
      if (statsRes.ok) {
        setStats(await statsRes.json());
      }
    } catch (e) {
      showToast("API connection failed — is the server running?", "#FF4466");
    } finally {
      setLoading(false);
    }
  }, [filter.sort, filter.minScore]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Poll scan status
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const r = await fetch(`${API}/scan/status`);
        if (r.ok) {
          const d = await r.json();
          if (scanning && !d.running) {
            setScanning(false);
            showToast("Scan complete!");
            fetchData();
          }
        }
      } catch {}
    }, 3000);
    return () => clearInterval(interval);
  }, [scanning, fetchData]);

  const triggerScan = async (mode = "full") => {
    setScanning(true);
    try {
      await fetch(`${API}/scan/trigger?mode=${mode}`, { method: "POST" });
      showToast(`${mode} scan started...`, "#FFB347");
    } catch {
      setScanning(false);
      showToast("Failed to start scan", "#FF4466");
    }
  };

  const registerDomain = async (domain) => {
    showToast(`Registering ${domain}...`, "#6C63FF");
    try {
      const r = await fetch(`${API}/register/${domain}`, { method: "POST" });
      const d = await r.json();
      showToast(d.success ? `✅ ${domain} registered!` : `❌ ${d.message}`, d.success ? "#00C9A7" : "#FF4466");
      if (d.success) fetchData();
    } catch {
      showToast("Registration failed", "#FF4466");
    }
  };

  const filtered = domains
    .filter(d => filter.type === "all" || d.type === filter.type)
    .filter(d => !search || d.domain.includes(search.toLowerCase()))
    .filter(d => d.score >= filter.minScore);

  const spend = stats.spend || {};

  return (
    <div style={{
      minHeight: "100vh", background: "#060610",
      fontFamily: "'Courier New', monospace", color: "#E0E0F0"
    }}>

      {/* Toast */}
      {toast && (
        <div style={{
          position: "fixed", top: "20px", right: "20px", zIndex: 999,
          background: "#0D0D18", border: `1px solid ${toast.color}`,
          borderRadius: "8px", padding: "12px 20px",
          color: toast.color, fontSize: "12px", letterSpacing: "1px",
          boxShadow: `0 0 20px ${toast.color}30`
        }}>{toast.msg}</div>
      )}

      {/* Header */}
      <div style={{
        padding: "20px 28px", borderBottom: "1px solid #ffffff0A",
        background: "linear-gradient(135deg, #060610, #0F0F1E)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexWrap: "wrap", gap: "16px"
      }}>
        <div>
          <div style={{ fontSize: "10px", color: "#6C63FF", letterSpacing: "4px", marginBottom: "4px" }}>
            AI DOMAIN FLIP BOT v4
          </div>
          <h1 style={{ margin: 0, fontSize: "22px", fontWeight: "800", color: "#fff" }}>
            Domain Intelligence Dashboard
          </h1>
        </div>

        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
          <StatCard label="TOTAL"     value={stats.total}        color="#fff" />
          <StatCard label="AVG SCORE" value={stats.avg_score ? Math.round(stats.avg_score) : "—"} color="#FFB347" />
          <StatCard label="SPENT TODAY" value={`$${(spend.spent || 0).toFixed(2)}`} color="#00C9A7"
                    sub={`cap $${spend.cap || 50}`} />
          <button
            onClick={() => triggerScan("full")}
            disabled={scanning}
            style={{
              padding: "0 20px", background: scanning ? "#222" : "#6C63FF",
              color: scanning ? "#555" : "#fff", border: "none",
              borderRadius: "8px", cursor: scanning ? "default" : "pointer",
              fontFamily: "inherit", fontSize: "11px", letterSpacing: "2px",
              fontWeight: "700", height: "64px"
            }}
          >
            {scanning ? "SCANNING..." : "▶ RUN SCAN"}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", borderBottom: "1px solid #ffffff08", background: "#0A0A14" }}>
        {["domains", "breakouts", "backorders"].map(tab => (
          <button key={tab} onClick={() => setActiveTab(tab)} style={{
            padding: "14px 24px", background: "transparent",
            border: "none", borderBottom: activeTab === tab ? "2px solid #6C63FF" : "2px solid transparent",
            color: activeTab === tab ? "#6C63FF" : "#444",
            cursor: "pointer", fontFamily: "inherit",
            fontSize: "10px", letterSpacing: "2px", textTransform: "uppercase"
          }}>{tab}</button>
        ))}

        {/* Scan mode buttons */}
        <div style={{ marginLeft: "auto", display: "flex", gap: "6px", alignItems: "center", padding: "0 16px" }}>
          {["fast","expiring","market"].map(mode => (
            <button key={mode} onClick={() => triggerScan(mode)} disabled={scanning} style={{
              padding: "5px 12px", background: "transparent",
              border: "1px solid #ffffff15", borderRadius: "4px",
              color: "#444", cursor: "pointer", fontFamily: "inherit",
              fontSize: "9px", letterSpacing: "1px", textTransform: "uppercase"
            }}>{mode}</button>
          ))}
        </div>
      </div>

      {/* Filters */}
      {activeTab === "domains" && (
        <div style={{
          padding: "12px 20px", borderBottom: "1px solid #ffffff06",
          background: "#080812", display: "flex", gap: "10px",
          flexWrap: "wrap", alignItems: "center"
        }}>
          <input
            placeholder="search domains..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{
              background: "#ffffff08", border: "1px solid #ffffff15",
              borderRadius: "5px", padding: "7px 12px", color: "#fff",
              fontFamily: "inherit", fontSize: "11px", width: "180px", outline: "none"
            }}
          />
          {["all","unregistered","expiring","aftermarket"].map(t => (
            <button key={t} onClick={() => setFilter(f => ({...f, type: t}))} style={{
              padding: "5px 12px",
              border: filter.type === t ? "1px solid #6C63FF" : "1px solid #ffffff10",
              background: filter.type === t ? "#6C63FF20" : "transparent",
              color: filter.type === t ? "#6C63FF" : "#444",
              borderRadius: "4px", cursor: "pointer", fontFamily: "inherit",
              fontSize: "9px", letterSpacing: "1px", textTransform: "uppercase"
            }}>{t}</button>
          ))}
          <div style={{ marginLeft: "auto", display: "flex", gap: "6px", alignItems: "center" }}>
            <span style={{ fontSize: "10px", color: "#444" }}>MIN SCORE</span>
            {[0,70,80,90].map(s => (
              <button key={s} onClick={() => setFilter(f => ({...f, minScore: s}))} style={{
                padding: "4px 10px",
                border: filter.minScore === s ? "1px solid #ffffff30" : "1px solid transparent",
                background: filter.minScore === s ? "#ffffff10" : "transparent",
                color: filter.minScore === s ? "#fff" : "#444",
                borderRadius: "4px", cursor: "pointer", fontFamily: "inherit",
                fontSize: "9px", textTransform: "uppercase"
              }}>{s || "ALL"}</button>
            ))}
            <button
              onClick={() => { const url = `${API}/export/csv`; window.open(url); }}
              style={{
                padding: "5px 12px", background: "transparent",
                border: "1px solid #00C9A730", borderRadius: "4px",
                color: "#00C9A7", cursor: "pointer", fontFamily: "inherit",
                fontSize: "9px", letterSpacing: "1px", marginLeft: "8px"
              }}
            >↓ CSV</button>
          </div>
        </div>
      )}

      {/* Domain Table */}
      {activeTab === "domains" && (
        <div style={{ overflowX: "auto" }}>
          {loading ? (
            <div style={{ padding: "60px", textAlign: "center", color: "#444", fontSize: "12px" }}>
              Loading... (make sure `python dashboard/api.py` is running)
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: "#0A0A14" }}>
                  {["Domain","Type","Score","Est Value","Ask Price","Trend",""].map(h => (
                    <th key={h} style={{
                      padding: "10px 8px", textAlign: h === "Domain" ? "left" : "center",
                      fontSize: "9px", color: "#444", letterSpacing: "2px",
                      fontWeight: "400", textTransform: "uppercase",
                      ...(h === "Domain" && { paddingLeft: "16px" }),
                      ...(h === "" && { paddingRight: "16px" }),
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr><td colSpan={7} style={{ padding: "40px", textAlign: "center", color: "#444" }}>
                    No domains found. Run a scan first.
                  </td></tr>
                ) : (
                  filtered.map(d => (
                    <DomainRow key={d.domain} d={d} onRegister={registerDomain} />
                  ))
                )}
              </tbody>
            </table>
          )}
          <div style={{ padding: "10px 16px", fontSize: "10px", color: "#333" }}>
            Showing {filtered.length} of {domains.length} domains
          </div>
        </div>
      )}

      {/* Breakouts Tab */}
      {activeTab === "breakouts" && (
        <div style={{ padding: "24px 28px" }}>
          <div style={{ fontSize: "11px", color: "#FF6B9D", letterSpacing: "2px", marginBottom: "16px" }}>
            🚀 TREND BREAKOUTS — keywords spiking on Google Trends in last 7 days
          </div>
          {domains.filter(d => d.trend_label?.includes("BREAKOUT")).length === 0 ? (
            <div style={{ color: "#444", fontSize: "12px" }}>No breakouts detected yet. Run a scan with trends enabled.</div>
          ) : (
            domains.filter(d => d.trend_label?.includes("BREAKOUT")).map(d => (
              <div key={d.domain} style={{
                background: "#FF6B9D08", border: "1px solid #FF6B9D30",
                borderRadius: "8px", padding: "16px", marginBottom: "10px",
                display: "flex", alignItems: "center", gap: "20px"
              }}>
                <div style={{ fontFamily: "monospace", fontSize: "15px", fontWeight: "700", color: "#fff", minWidth: "200px" }}>
                  {d.domain}
                </div>
                <div style={{ fontSize: "11px", color: "#FF6B9D" }}>🚀 BREAKOUT</div>
                <div style={{ fontSize: "11px", color: "#888" }}>keyword: "{d.trend_keyword}"</div>
                <div style={{ fontSize: "11px", color: "#FFB347" }}>score: {d.score}</div>
                <div style={{ marginLeft: "auto" }}>
                  <button onClick={() => registerDomain(d.domain)} style={{
                    padding: "6px 14px", background: "#FF6B9D20",
                    border: "1px solid #FF6B9D40", borderRadius: "5px",
                    color: "#FF6B9D", cursor: "pointer", fontFamily: "inherit", fontSize: "10px"
                  }}>REGISTER NOW →</button>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Backorders Tab */}
      {activeTab === "backorders" && (
        <div style={{ padding: "24px 28px" }}>
          <div style={{ fontSize: "11px", color: "#FFB347", letterSpacing: "2px", marginBottom: "16px" }}>
            🟡 ACTIVE BACKORDERS — domains being caught when they drop
          </div>
          <div style={{ color: "#444", fontSize: "12px" }}>
            Backorder data loads from local file. Run a scan with expiring mode to populate.
          </div>
        </div>
      )}
    </div>
  );
}
