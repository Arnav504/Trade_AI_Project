"use client";

import { FormEvent, useRef, useState } from "react";

type ChartRow = {
  label: string;
  value: number;
  display: string;
  year?: number;
};

type YearPoint = {
  year: number;
  value: number;
  display: string;
};

type YearSeries = {
  label: string;
  source: string;
  chapter: string;
  span_display: string;
  points: YearPoint[];
};

type WebNotes = {
  summary?: string;
  links?: { title: string; url: string }[];
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
  macro?: string;
  web_notes?: WebNotes;
  disclaimer?: string;
  source?: string;
  focus?: string;
  tool_trace?: Trace[];
  charts?: { top_flows: ChartRow[]; yoy: ChartRow[]; series?: YearSeries[] };
};

type Gallery = {
  data_note: string;
  disclaimer: string;
  briefs: Brief[];
  charts: { top_flows: ChartRow[]; yoy: ChartRow[]; series?: YearSeries[] };
  how_it_works: { tools: string[]; backends: string };
};

const EXAMPLES = [
  "EU energy with India since 2019",
  "Japan–India trade in 2025",
  "US–China electronics",
];

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function Bars({ rows, signed, empty }: { rows: ChartRow[]; signed?: boolean; empty: string }) {
  if (!rows.length) {
    return <p className="caption">{empty}</p>;
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

function YearChart({ series }: { series: YearSeries[] }) {
  if (!series.length) return null;
  return (
    <div className="chart-block">
      <h3>Across the years</h3>
      {series.map((item) => (
        <div key={item.label}>
          <p className="caption">
            {item.source} · {item.chapter}. {item.label}. {item.span_display}
          </p>
          <Bars
            rows={item.points.map((point) => ({
              label: String(point.year),
              value: point.value,
              display: point.display,
            }))}
            empty=""
          />
        </div>
      ))}
    </div>
  );
}

export function BriefApp({ gallery, apiBase }: { gallery: Gallery; apiBase: string }) {
  const briefs = gallery.briefs;
  const [activeId, setActiveId] = useState(briefs[0]?.id || "brics");
  const [live, setLive] = useState<Brief | null>(null);
  const [draft, setDraft] = useState("");
  const [asked, setAsked] = useState("");
  const [status, setStatus] = useState("");
  const [pending, setPending] = useState(false);
  const [trouble, setTrouble] = useState("");
  const ticket = useRef(0);

  const selected = briefs.find((brief) => brief.id === activeId) ?? briefs[0];
  const waiting = Boolean(pending && asked && !live);
  const held = Boolean(asked && trouble && !live);
  const shown = live ?? selected;
  const chartEmpty = waiting || held ? "Waiting for official rows for this question." : gallery.data_note;
  const charts = live?.charts
    ? live.charts
    : waiting || held
      ? { top_flows: [], yoy: [], series: [] }
      : selected.charts ?? gallery.charts;
  const base = apiBase.replace(/\/$/, "");

  function selectSample(id: string) {
    ticket.current += 1;
    setPending(false);
    setLive(null);
    setAsked("");
    setTrouble("");
    setStatus("");
    setActiveId(id);
  }

  async function postAnalyze(query: string) {
    return fetch(`${base}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
  }

  function holdQuestion(query: string, message: string) {
    setLive(null);
    setAsked(query);
    setTrouble(message);
    setStatus(message);
    setPending(false);
  }

  async function runQuery(query: string) {
    const mine = ++ticket.current;
    setLive(null);
    setTrouble("");
    setAsked(query);
    setPending(true);
    if (!base) {
      holdQuestion(query, "Live generation is not connected on this deploy.");
      return;
    }
    setStatus("Checking the cache…");
    try {
      let response: Response;
      try {
        response = await postAnalyze(query);
      } catch {
        if (mine !== ticket.current) return;
        setStatus("Waking the data service…");
        await sleep(4000);
        if (mine !== ticket.current) return;
        response = await postAnalyze(query);
      }
      const data = await response.json().catch(() => ({}));
      if (mine !== ticket.current) return;
      if (response.status === 429 || !response.ok) {
        const detail = typeof data.detail === "string" ? data.detail : "The analysis service could not start this question.";
        holdQuestion(query, detail);
        return;
      }
      if (data.status === "complete" && data.brief) {
        setAsked("");
        setTrouble("");
        setLive(data.brief);
        setStatus(data.cached ? "Cached brief. The bars use the same rows as this answer." : "Live brief. The bars use the same rows as this answer.");
        setPending(false);
        return;
      }
      setStatus(typeof data.stage === "string" && data.stage ? data.stage : "Fetching UN Comtrade…");
      const jobId = data.job_id as string;
      for (let attempt = 0; attempt < 40; attempt += 1) {
        await sleep(3000);
        if (mine !== ticket.current) return;
        let job: { status?: string; brief?: Brief; error?: string; stage?: string } | null = null;
        try {
          const poll = await fetch(`${base}/analyze/${jobId}`);
          if (mine !== ticket.current) return;
          if (!poll.ok) continue;
          const parsed = await poll.json();
          if (!parsed || typeof parsed !== "object") continue;
          job = parsed;
        } catch {
          continue;
        }
        if (mine !== ticket.current) return;
        if (!job) continue;
        if (job.stage) setStatus(job.stage);
        if (job.status === "complete" && job.brief) {
          setAsked("");
          setTrouble("");
          setLive(job.brief);
          setStatus("Live brief. The bars use the same rows as this answer.");
          setPending(false);
          return;
        }
        if (job.status === "error") {
          holdQuestion(query, job.error || "Generation failed.");
          return;
        }
      }
      holdQuestion(query, "Still running. Ask again in a minute to read the cached result.");
    } catch {
      if (mine !== ticket.current) return;
      holdQuestion(query, "The analysis service is unreachable.");
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const query = draft.trim();
    if (!query || pending) return;
    void runQuery(query);
  }

  return (
    <main className="wrap">
      <header className="top">
        <div className="mark">ASAN <span>Macro</span></div>
        <a href="https://github.com/Arnav504/Trade_AI_Project">Source</a>
      </header>

      <section className="hero">
        <p className="kicker">Trade sentiment briefs</p>
        <h1>What the panel says, with the numbers attached.</h1>
        <p className="lede">
          Ask a question first. The answer stays on this card, and the bars use those same rows.
          Three sample corridors stay available underneath.
        </p>
        <p className="note">{gallery.data_note}</p>
      </section>

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
            placeholder="How has EU energy trade with India changed since 2019?"
          />
          <button type="submit" disabled={pending}>
            {pending ? "Working" : "Generate"}
          </button>
        </form>
        <div className="examples">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              disabled={pending}
              onClick={() => {
                setDraft(example);
                void runQuery(example);
              }}
            >
              {example}
            </button>
          ))}
        </div>
        <p className="status" role="status" aria-live="polite">{status}</p>
      </section>

      <div className="switcher" role="tablist" aria-label="Sample briefs">
        {briefs.map((brief) => (
          <button
            key={brief.id}
            type="button"
            role="tab"
            aria-pressed={brief.id === activeId && !live && !waiting && !held}
            onClick={() => brief.id && selectSample(brief.id)}
          >
            <strong>{brief.title}</strong>
            <em>{brief.kicker}</em>
          </button>
        ))}
      </div>

      <div className="layout">
        <article className="card">
          {waiting || held ? (
            <>
              <div className="pill">{held ? "Could not finish" : "Your question"}</div>
              <h2>{asked}</h2>
              <p>{status}</p>
            </>
          ) : (
            <>
          {live ? <div className="pill">Live brief · {live.focus || "query"}</div> : <div className="pill">Corridor · database tools</div>}
          <h2>Summary</h2>
          <p>{shown.summary}</p>
          <h2>Key regions and sectors</h2>
          <p>{shown.key_regions_sectors || "Not provided."}</p>
          {shown.macro ? (
            <>
              <h2>Wider accounts</h2>
              <p>{shown.macro}</p>
            </>
          ) : null}
          <h2>So what</h2>
          <p>{shown.so_what || "Not provided."}</p>
          <h2>What&apos;s next</h2>
          <p>{shown.whats_next || "Not provided."}</p>
          <p className="disclaimer">{shown.disclaimer || gallery.disclaimer}</p>
          {shown.web_notes?.links && shown.web_notes.links.length > 0 ? (
            <>
              <h2>What people are saying</h2>
              <p>{shown.web_notes.summary}</p>
              <ul className="links">
                {shown.web_notes.links.map((link) => (
                  <li key={link.url}>
                    <a href={link.url}>{link.title}</a>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
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
            </>
          )}
        </article>

        <aside className="card charts">
          <h3>Latest levels</h3>
          <p className="caption">{waiting || held ? status : gallery.data_note}</p>
          <Bars rows={charts.top_flows || []} empty={chartEmpty} />
          <YearChart series={charts.series || []} />
          <div className="chart-block">
            <h3>Latest year-over-year</h3>
            <Bars rows={charts.yoy || []} signed empty={chartEmpty} />
          </div>
        </aside>
      </div>

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
