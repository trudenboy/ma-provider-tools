import React, { useState, useMemo } from "react";

interface ProviderStat {
  name: string;
  repo: string;
  type: "music_provider" | "player_provider" | "server_fork";
  pr_open: number;
  pr_draft: number;
  pr_merged_30d: number;
  bugs: number;
  enhancements: number;
  incidents: number;
  issues_open: number;
  ci_status: string | null;
  ci_date: string | null;
  last_release: string | null;
  last_release_date: string | null;
  commits_30d: number;
  last_commit: string | null;
  contributors: number;
  py_files: number;
  code_size_kb: number;
  additions_30d: number;
  deletions_30d: number;
}

export interface DashboardData {
  generated_at: string;
  providers: ProviderStat[];
}

type SortKey = keyof ProviderStat;
type SortDir = "asc" | "desc";
type Tab = "prs" | "code" | "intensity";
type TypeFilter = "all" | "music_provider" | "player_provider" | "server_fork";

function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const dt = new Date(iso);
  const now = new Date();
  const days = Math.floor((now.getTime() - dt.getTime()) / 86400000);
  if (days === 0) return "today";
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

function CiStatus({ status }: { status: string | null }) {
  if (!status || status === "n/a") return <span>—</span>;
  const icons: Record<string, string> = {
    success: "✅",
    failure: "❌",
    cancelled: "⚫",
    timed_out: "⏱️",
    in_progress: "🔄",
    queued: "🕐",
  };
  const cls =
    status === "success"
      ? "ci-success"
      : status === "failure"
        ? "ci-failure"
        : "ci-unknown";
  return (
    <span className={cls} title={status}>
      {icons[status] ?? "❓"}
    </span>
  );
}

function TypeBadge({ type }: { type: string }) {
  const labels: Record<string, [string, string]> = {
    music_provider: ["🎵 Music", "badge-music"],
    player_provider: ["🔊 Player", "badge-player"],
    server_fork: ["🔧 Fork", "badge-fork"],
  };
  const [label, cls] = labels[type] ?? [type, ""];
  return <span className={`dashboard-badge ${cls}`}>{label}</span>;
}

function SortIcon({
  col,
  sortKey,
  sortDir,
}: {
  col: string;
  sortKey: string;
  sortDir: SortDir;
}) {
  if (col !== sortKey) return <span style={{ opacity: 0.3 }}> ↕</span>;
  return <span>{sortDir === "asc" ? " ↑" : " ↓"}</span>;
}

function sum(providers: ProviderStat[], key: keyof ProviderStat): number {
  return providers.reduce((acc, p) => acc + ((p[key] as number) || 0), 0);
}

export default function ProviderDashboard({
  data,
}: {
  data: DashboardData;
}): React.ReactElement {
  const [tab, setTab] = useState<Tab>("prs");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const filtered = useMemo(
    () =>
      data.providers.filter(
        (p) => typeFilter === "all" || p.type === typeFilter
      ),
    [data.providers, typeFilter]
  );

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [filtered, sortKey, sortDir]);

  function onSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  function Th({
    col,
    label,
    title,
  }: {
    col: SortKey;
    label: string;
    title?: string;
  }) {
    return (
      <th onClick={() => onSort(col)} title={title}>
        {label}
        <SortIcon col={col} sortKey={sortKey} sortDir={sortDir} />
      </th>
    );
  }

  const tabStyle = (t: Tab) => ({
    padding: "0.4rem 1rem",
    border: "1px solid var(--ifm-color-emphasis-300)",
    borderRadius: "0.25rem",
    background: tab === t ? "var(--ifm-color-primary)" : "transparent",
    color: tab === t ? "white" : "inherit",
    cursor: "pointer",
    fontWeight: tab === t ? 600 : 400,
  });

  return (
    <div>
      <p style={{ color: "var(--ifm-color-emphasis-600)", fontSize: "0.85rem" }}>
        Last updated:{" "}
        {new Date(data.generated_at).toLocaleString("en-GB", {
          dateStyle: "medium",
          timeStyle: "short",
          timeZone: "UTC",
        })}{" "}
        UTC
      </p>

      {/* Controls */}
      <div className="dashboard-controls">
        <div>
          <button style={tabStyle("prs")} onClick={() => setTab("prs")}>
            PRs &amp; Issues
          </button>{" "}
          <button style={tabStyle("code")} onClick={() => setTab("code")}>
            Codebase
          </button>{" "}
          <button
            style={tabStyle("intensity")}
            onClick={() => setTab("intensity")}
          >
            Dev Intensity
          </button>
        </div>
        <div>
          <label style={{ marginRight: "0.5rem", fontSize: "0.85rem" }}>
            Filter:
          </label>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as TypeFilter)}
            style={{ fontSize: "0.85rem", padding: "0.2rem 0.5rem" }}
          >
            <option value="all">All types</option>
            <option value="music_provider">🎵 Music</option>
            <option value="player_provider">🔊 Player</option>
            <option value="server_fork">🔧 Fork</option>
          </select>
        </div>
      </div>

      {/* PRs & Issues tab */}
      {tab === "prs" && (
        <div style={{ overflowX: "auto" }}>
          <table className="dashboard-table">
            <thead>
              <tr>
                <Th col="name" label="Provider" />
                <Th col="type" label="Type" />
                <Th col="pr_open" label="Open PRs" title="Open pull requests" />
                <Th col="pr_draft" label="Draft" />
                <Th col="pr_merged_30d" label="Merged 30d" />
                <Th col="bugs" label="🐛 Bugs" />
                <Th col="enhancements" label="💡 Enhance" />
                <Th col="incidents" label="🚨 CI Incidents" />
                <Th col="issues_open" label="Issues" />
                <th>CI Status</th>
                <Th col="last_release" label="Last Release" />
              </tr>
            </thead>
            <tbody>
              {sorted.map((p) => (
                <tr key={p.repo}>
                  <td>
                    <a
                      href={`https://github.com/${p.repo}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {p.name}
                    </a>
                  </td>
                  <td>
                    <TypeBadge type={p.type} />
                  </td>
                  <td style={{ textAlign: "center" }}>{p.pr_open}</td>
                  <td style={{ textAlign: "center" }}>{p.pr_draft}</td>
                  <td style={{ textAlign: "center" }}>{p.pr_merged_30d}</td>
                  <td style={{ textAlign: "center" }}>
                    {p.bugs > 0 ? (
                      <strong style={{ color: "#dc2626" }}>{p.bugs}</strong>
                    ) : (
                      p.bugs
                    )}
                  </td>
                  <td style={{ textAlign: "center" }}>{p.enhancements}</td>
                  <td style={{ textAlign: "center" }}>
                    {p.incidents > 0 ? (
                      <strong style={{ color: "#d97706" }}>{p.incidents}</strong>
                    ) : (
                      p.incidents
                    )}
                  </td>
                  <td style={{ textAlign: "center" }}>{p.issues_open}</td>
                  <td style={{ textAlign: "center" }}>
                    <CiStatus status={p.ci_status} />
                    {p.ci_date && (
                      <span
                        style={{
                          fontSize: "0.75rem",
                          color: "var(--ifm-color-emphasis-600)",
                          marginLeft: "0.3rem",
                        }}
                      >
                        {formatRelative(p.ci_date)}
                      </span>
                    )}
                  </td>
                  <td>
                    {p.last_release ? (
                      <>
                        {p.last_release}
                        {p.last_release_date && (
                          <span
                            style={{
                              fontSize: "0.75rem",
                              color: "var(--ifm-color-emphasis-600)",
                              marginLeft: "0.3rem",
                            }}
                          >
                            ({formatRelative(p.last_release_date)})
                          </span>
                        )}
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
              <tr className="total-row">
                <td colSpan={2}>Total</td>
                <td style={{ textAlign: "center" }}>{sum(sorted, "pr_open")}</td>
                <td style={{ textAlign: "center" }}>{sum(sorted, "pr_draft")}</td>
                <td style={{ textAlign: "center" }}>
                  {sum(sorted, "pr_merged_30d")}
                </td>
                <td style={{ textAlign: "center" }}>{sum(sorted, "bugs")}</td>
                <td style={{ textAlign: "center" }}>
                  {sum(sorted, "enhancements")}
                </td>
                <td style={{ textAlign: "center" }}>
                  {sum(sorted, "incidents")}
                </td>
                <td style={{ textAlign: "center" }}>
                  {sum(sorted, "issues_open")}
                </td>
                <td colSpan={2} />
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {/* Codebase tab */}
      {tab === "code" && (
        <div style={{ overflowX: "auto" }}>
          <table className="dashboard-table">
            <thead>
              <tr>
                <Th col="name" label="Provider" />
                <Th col="type" label="Type" />
                <Th col="py_files" label="🐍 Python Files" />
                <Th col="code_size_kb" label="📦 Code Size" />
                <Th col="contributors" label="👥 Contributors" />
              </tr>
            </thead>
            <tbody>
              {sorted.map((p) => (
                <tr key={p.repo}>
                  <td>
                    <a
                      href={`https://github.com/${p.repo}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {p.name}
                    </a>
                  </td>
                  <td>
                    <TypeBadge type={p.type} />
                  </td>
                  <td style={{ textAlign: "center" }}>{p.py_files}</td>
                  <td style={{ textAlign: "center" }}>{p.code_size_kb} KB</td>
                  <td style={{ textAlign: "center" }}>{p.contributors}</td>
                </tr>
              ))}
              <tr className="total-row">
                <td colSpan={2}>Total</td>
                <td style={{ textAlign: "center" }}>{sum(sorted, "py_files")}</td>
                <td style={{ textAlign: "center" }}>
                  {sum(sorted, "code_size_kb").toFixed(1)} KB
                </td>
                <td />
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {/* Dev Intensity tab */}
      {tab === "intensity" && (
        <div style={{ overflowX: "auto" }}>
          <table className="dashboard-table">
            <thead>
              <tr>
                <Th col="name" label="Provider" />
                <Th col="type" label="Type" />
                <Th col="commits_30d" label="📝 Commits (30d)" />
                <Th col="last_commit" label="Last Commit" />
                <Th col="pr_merged_30d" label="PRs Merged (30d)" />
                <Th col="additions_30d" label="➕ Additions" />
                <Th col="deletions_30d" label="➖ Deletions" />
              </tr>
            </thead>
            <tbody>
              {sorted.map((p) => (
                <tr key={p.repo}>
                  <td>
                    <a
                      href={`https://github.com/${p.repo}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {p.name}
                    </a>
                  </td>
                  <td>
                    <TypeBadge type={p.type} />
                  </td>
                  <td style={{ textAlign: "center" }}>{p.commits_30d}</td>
                  <td>{formatRelative(p.last_commit)}</td>
                  <td style={{ textAlign: "center" }}>{p.pr_merged_30d}</td>
                  <td style={{ textAlign: "center", color: "#16a34a" }}>
                    +{p.additions_30d.toLocaleString()}
                  </td>
                  <td style={{ textAlign: "center", color: "#dc2626" }}>
                    -{p.deletions_30d.toLocaleString()}
                  </td>
                </tr>
              ))}
              <tr className="total-row">
                <td colSpan={2}>Total</td>
                <td style={{ textAlign: "center" }}>
                  {sum(sorted, "commits_30d")}
                </td>
                <td />
                <td style={{ textAlign: "center" }}>
                  {sum(sorted, "pr_merged_30d")}
                </td>
                <td style={{ textAlign: "center", color: "#16a34a" }}>
                  +{sum(sorted, "additions_30d").toLocaleString()}
                </td>
                <td style={{ textAlign: "center", color: "#dc2626" }}>
                  -{sum(sorted, "deletions_30d").toLocaleString()}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
