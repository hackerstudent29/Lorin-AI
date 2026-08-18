import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

const API_BASE = import.meta.env.VITE_API_URL || "";

interface AdminStats {
  total_queries: number;
  cache_hits: number;
  feedback: {
    thumbs_up: number;
    thumbs_down: number;
  };
}

export function AdminDashboard() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const resStats = await fetch(`${API_BASE}/api/admin/stats`);
        if (resStats.ok) {
          setStats(await resStats.json());
        } else {
          throw new Error("Failed to load stats");
        }

        const resLogs = await fetch(`${API_BASE}/api/feedback/log`);
        if (resLogs.ok) {
          const data = await resLogs.json();
          setLogs(data.logs || []);
        }
      } catch (err: any) {
        setError(err.message);
      }
    }
    fetchData();
  }, []);

  return (
    <div className="min-h-screen p-8 text-foreground" style={{ backgroundColor: "var(--background)" }}>
      <div className="mx-auto max-w-5xl">
        <header className="mb-8 flex items-center justify-between border-b pb-4 border-border">
          <h1 className="text-3xl font-bold">RAG Admin Dashboard</h1>
          <Link to="/" className="text-emerald-600 hover:text-emerald-700 hover:underline font-medium">
            Back to Chat
          </Link>
        </header>

        {error && <div className="mb-4 rounded-md bg-red-500/20 p-4 text-red-500">{error}</div>}

        <div className="mb-8 grid grid-cols-1 gap-6 md:grid-cols-3">
          <div className="rounded-xl border border-border p-6 shadow-sm bg-card">
            <h2 className="text-sm text-muted-foreground uppercase tracking-wide">Total Queries</h2>
            <p className="mt-2 text-4xl font-bold">{stats?.total_queries ?? "—"}</p>
          </div>
          <div className="rounded-xl border border-border p-6 shadow-sm bg-card">
            <h2 className="text-sm text-muted-foreground uppercase tracking-wide">Cache Hits</h2>
            <p className="mt-2 text-4xl font-bold text-emerald-600">{stats?.cache_hits ?? "—"}</p>
          </div>
          <div className="rounded-xl border border-border p-6 shadow-sm bg-card">
            <h2 className="text-sm text-muted-foreground uppercase tracking-wide">Feedback Rating</h2>
            <div className="mt-2 flex items-baseline gap-4">
              <span className="text-4xl font-bold text-emerald-600">+{stats?.feedback.thumbs_up ?? 0}</span>
              <span className="text-4xl font-bold text-red-500">-{stats?.feedback.thumbs_down ?? 0}</span>
            </div>
          </div>
        </div>

        <h2 className="mb-4 text-2xl font-semibold">Recent Feedback &amp; Self-Healing Logs</h2>
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-left text-sm">
            <thead className="border-b bg-muted/50 border-border">
              <tr>
                <th className="p-4 font-medium">Time</th>
                <th className="p-4 font-medium">Query</th>
                <th className="p-4 font-medium">Verdict</th>
                <th className="p-4 font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {logs.length === 0 ? (
                <tr>
                  <td colSpan={4} className="p-8 text-center text-muted-foreground">
                    No logs found.
                  </td>
                </tr>
              ) : (
                logs.map((log) => (
                  <tr key={log.id} className="border-b border-border/50 last:border-0 hover:bg-muted/30">
                    <td className="p-4 align-top text-muted-foreground">
                      {new Date(log.created_at).toLocaleString()}
                    </td>
                    <td className="p-4 align-top font-medium max-w-[200px] truncate">
                      {log.user_query}
                    </td>
                    <td className="p-4 align-top">
                      <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                        log.verdict === 'VALID' ? 'bg-green-500/20 text-green-500' :
                        log.verdict === 'HALLUCINATION' ? 'bg-red-500/20 text-red-500' :
                        'bg-yellow-500/20 text-yellow-500'
                      }`}>
                        {log.verdict}
                      </span>
                    </td>
                    <td className="p-4 align-top">
                      {log.cache_updated ? (
                        <span className="text-green-500">Cache Updated</span>
                      ) : (
                        <span className="text-muted-foreground">No Change</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
