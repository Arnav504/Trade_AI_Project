"use client";

import { FormEvent, useRef, useState } from "react";

type ChartRow = {
  label: string;
  value: number;
  display: string;
  year?: number;
};

type Trace = {
  name: string;
  args?: Record<string, unknown>;
  latency_ms?: number;
};

type Brief = {
  id?: string;
  title?: string;
  kicker?: string;
  query?: string;
  summary: string;
  key_regions_sectors?: string;
  so_what?: string;
  whats_next?: string;
  disclaimer?: string;
  source?: string;
  focus?: string;
  tool_trace?: Trace[];
  charts?: { top_flows: ChartRow[]; yoy: ChartRow[] };
};

type Gallery = {
  data_note: string;
  disclaimer: string;
  briefs: Brief[];
  charts: { top_flows: ChartRow[]; yoy: ChartRow[] };
  how_it_works: { tools: string[]; backends: string };
};

function closestId(query: string, briefs: Brief[], fallback: string) {
  const q = query.toLowerCase();
  if (/brics|mineral|energy|russia/.test(q)) return "brics";
  if (/vietnam|mexico|textile|manufactur|nearshor/.test(q)) return "nearshoring";
  if (/electron|china|decoupl/.test(q)) return "us-china-electronics";
  return briefs.some((brief) => brief.id === fallback) ? fallback : briefs[0]?.id || fallback;
}

function Bars({ rows, signed }: { rows: ChartRow[]; signed?: boolean }) {
  if (!rows.length) {
    return <p className="caption">No matching rows in the seeded panel.</p>;
  }
  const max = Math.max(...rows.map((row) => Math.abs(row.value)), 1);
  return (
    <div>
      {rows.map((row, index) => {
        const down = signed && row.value < 0;
        const width = `${Math.max(4, (Math.abs(row.value) / max) * 100)}%`;
        return (
          <div className="bar-row" key={`${row.label}-${index}`}>
            <div className="bar-label">{row.label}</div>
            <div className="bar-track">
              <div className={down ? "bar-fill down" : "bar-fill"} style={{ width }} />
            </div>
            <div className="bar-value">{row.display}</div>
          </div>
        );
      })}
    </div>
  );
}

export function BriefApp({ gallery, apiBase }: { gallery: Gallery; apiBase: string }) {
  const briefs = gallery.briefs;
  const [activeId, setActiveId] = useState(briefs[0]?.id || "brics");
  const [live, setLive] = useState<Brief | null>(null);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState("");
  const [pending, setPending] = useState(false);
  const ticket = useRef(0);

  const selected = briefs.find((brief) => brief.id === activeId) ?? briefs[0];
  const shown = live ?? selected;
  const charts = live ? gallery.charts : selected.charts ?? gallery.charts;
  const base = apiBase.replace(/\/$/, "");

  function selectSample(id: string) {
    ticket.current += 1;
    setPending(false);
    setLive(null);
    setStatus("");
    setActiveId(id);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const query = draft.trim();
    if (!query) return;
    const mine = ++ticket.current;
    setLive(null);
    setActiveId(closestId(query, briefs, activeId));
    if (!base) {
      setStatus("Live generation is not connected on this deploy. Showing the closest sample brief.");
      return;
    }
    setPending(true);
    setStatus("Checking the cache…");
    try {
      const response = await fetch(`${base}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      const data = await response.json().catch(() => ({}));
      if (mine !== ticket.current) return;
      if (response.status === 429 || !response.ok) {
        const detail = typeof data.detail === "string" ? data.detail : "Showing the closest sample brief.";
        setStatus(detail);
        setPending(false);
        return;
      }
      if (data.status === "complete" && data.brief) {
        setLive(data.brief);
        setStatus(data.cached ? "Cached brief. Charts below stay on the seeded panel." : "Live brief. Charts below stay on the seeded panel.");
        setPending(false);
        return;
      }
      setStatus("Generating. The sample brief stays up until the model finishes.");
      const jobId = data.job_id as string;
      for (let attempt = 0; attempt < 40; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 3000));
        if (mine !== ticket.current) return;
        const poll = await fetch(`${base}/analyze/${jobId}`);
        if (mine !== ticket.current) return;
        if (!poll.ok) continue;
        let job: { status?: string; brief?: Brief; error?: string };
        try {
          job = await poll.json();
        } catch {
          if (mine !== ticket.current) return;
          setStatus("The analysis service returned an unreadable status. Showing the closest sample brief.");
          setPending(false);
          return;
        }
        if (!job || typeof job !== "object") {
          if (mine !== ticket.current) return;
          setStatus("The analysis service returned an unreadable status. Showing the closest sample brief.");
          setPending(false);
          return;
        }
        if (job.status === "complete" && job.brief) {
          setLive(job.brief);
          setStatus("Live brief ready. Charts below stay on the seeded panel.");
          setPending(false);
          return;
        }
        if (job.status === "error") {
          setStatus(job.error || "Generation failed. Showing the closest sample brief.");
          setPending(false);
          return;
        }
      }
      setStatus("Still running. The sample brief stays on screen. Ask again in a minute to read the cached result.");
      setPending(false);
    } catch {
      if (mine !== ticket.current) return;
      setStatus("The analysis service is unreachable. Showing the closest sample brief.");
      setPending(false);
    }
  }

  return (
    <main className="wrap">
      <header className="top">
        <div className="mark">ASAN <span>Macro</span></div>
        <a href="https://github.com/Arnav504/ASAN_AI_Project">Source</a>
      </header>

      <section className="hero">
        <p className="kicker">Trade sentiment briefs</p>
        <h1>What the panel says, with the numbers attached.</h1>
        <p className="lede">
          Three briefs are already computed from the database tools. A live query calls the model,
          rate-limited, and falls back to the closest sample if generation is still running or the API is down.
        </p>
        <p className="note">{gallery.data_note}</p>
      </section>

      <div className="switcher" role="tablist" aria-label="Sample briefs">
        {briefs.map((brief) => (
          <button
            key={brief.id}
            type="button"
            role="tab"
            aria-pressed={brief.id === activeId && !live}
            onClick={() => brief.id && selectSample(brief.id)}
          >
            <strong>{brief.title}</strong>
            <em>{brief.kicker}</em>
          </button>
        ))}
      </div>

      <div className="layout">
        <article className="card">
          {live ? <div className="pill">Live brief · {live.focus || "query"}</div> : <div className="pill">Sample · database tools</div>}
          <h2>Summary</h2>
          <p>{shown.summary}</p>
          <h2>Key regions and sectors</h2>
          <p>{shown.key_regions_sectors || "Not provided."}</p>
          <h2>So what</h2>
          <p>{shown.so_what || "Not provided."}</p>
          <h2>What&apos;s next</h2>
          <p>{shown.whats_next || "Not provided."}</p>
          <p className="disclaimer">{shown.disclaimer || gallery.disclaimer}</p>
          {shown.tool_trace && shown.tool_trace.length > 0 ? (
            <details>
              <summary>Tool trace ({shown.tool_trace.length})</summary>
              <ul className="trace">
                {shown.tool_trace.map((call, index) => (
                  <li key={`${call.name}-${index}`}>
                    {call.name}
                    {call.latency_ms != null ? ` · ${call.latency_ms} ms` : ""}
                    {call.args && Object.keys(call.args).length > 0 ? ` · ${JSON.stringify(call.args)}` : ""}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </article>

        <aside className="card charts">
          <h3>Latest levels</h3>
          <p className="caption">
            {live
              ? "These bars are the seeded panel, not sentences from the model."
              : "Largest latest value in this focus. Computed in SQL."}
          </p>
          <Bars rows={charts.top_flows || []} />
          <div className="chart-block">
            <h3>Latest year-over-year</h3>
            <Bars rows={charts.yoy || []} signed />
          </div>
        </aside>
      </div>

      <section className="card ask">
        <h2>Ask a focus</h2>
        <p className="caption">
          Short trade questions only. The service refuses instruction overrides and does not accept file or URL uploads.
          New generations are limited to five an hour; a repeated question is free if it is already cached.
        </p>
        <form onSubmit={onSubmit}>
          <label className="visually-hidden" htmlFor="focus">Focus query</label>
          <input
            id="focus"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            maxLength={200}
            placeholder="BRICS minerals, or US-China electronics"
          />
          <button type="submit" disabled={pending}>
            {pending ? "Working" : "Generate"}
          </button>
        </form>
        <p className="status" role="status" aria-live="polite">{status}</p>
      </section>

      <section className="method">
        <div className="card">
          <h2>How a brief is made</h2>
          <p>{gallery.how_it_works.backends}</p>
          <p className="caption">The sample text above is composed from those tool results so the figures match the charts. A live brief is the model&apos;s writing over the same tools.</p>
        </div>
        <div className="card">
          <h2>Tools</h2>
          <ul>
            {gallery.how_it_works.tools.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
        </div>
      </section>
    </main>
  );
}
