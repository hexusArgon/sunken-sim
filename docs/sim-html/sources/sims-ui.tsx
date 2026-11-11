// Shared page UI for the class sim pages (mage, priest, shaman, paladin, druid).
// Each <class>.tsx keeps only its data (TALENTS, GLYPHS, <SPEC>_DATA, ITEM_TIPS, NAME_TIPS) and renders <ClassPage>.
// Run selection: spec → pool ("Shop + drop" = top, "Только Shop Item" = top_shop, "Только Random drop" = top_random;
// top_shop_random is never shown, .cursor/rules/sim-canvas.mdc) → place 1..10. No all-runs summary table.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useCanvasState } from "cursor/canvas";

export type TipTable = Array<[string, string, boolean]>;
type Points = Record<string, number>;
export type Run = {
  farm_dps: number; dps: number; total: number; manaLeft: number;
  bound_spell: string | null; orb_mode: string | null;
  items: Array<{ name: string; code: string; source: string }>;
  talents: string[]; glyphs: string[]; points: Points; chunk: number;
  sources: Array<[string, number]>; actions: Array<[string, string]>; stats: Array<[string, string]>;
  talentDps?: Record<string, number>; glyphDps?: Record<string, number>;
};
export type Data = { level: number; targets: number; farm_file: string; done: number; runs: Record<string, Run[]>; [key: string]: any };
export type SpecDef = { id: string; title: string; pill: string; data: Data };
export type PageConfig = {
  hero: string;
  color: string;
  specs: SpecDef[];
  talents: TipTable;
  glyphs: TipTable;
  itemTips: Record<string, string>;
  nameTips: Record<string, [string, string]>;
  actionLabel?: string;
};

const POOLS: Array<[string, string, string]> = [
  ["mixed", "Shop + drop", "Общий топ: Shop, Random drop и связки"],
  ["shop", "Только Shop Item", "Все шесть предметов из магазина"],
  ["drop", "Только Random drop", "Все шесть предметов из дропа"],
  ["lantern", "С Soul Lantern", "Отдельный прогон с обязательным Soul Lantern"],
];
const SOURCE_LABEL: Record<string, string> = { shop: "Shop", drop: "Drop", legendary: "Legendary" };
const SOURCE_TITLE: Record<string, string> = { shop: "Shop Item", drop: "Random drop", legendary: "Mysterious Wanderer" };
const ESC_LABELS: Array<[string, string]> = [
  ["health", "Health"], ["mana", "Mana"], ["healing_power", "Healing Power"], ["haste", "Haste"],
  ["attack_speed", "Attack Speed"], ["damage", "Damage"], ["crit", "Critical Strike"], ["potency", "Potency"],
  ["mastery", "Mastery"], ["luck", "Luck"], ["pet_damage", "Pet Damage"],
];
const LANE_COLORS = ["#58a6ff", "#3fb950", "#d29922", "#f778ba", "#a371f7", "#39c5cf", "#ff9a5c", "#e3b341", "#8b949e", "#56d364"];
const DIAMOND_RING = "I00D";
const FIGHT = 30;

const fmt1 = (v: number) => v.toFixed(1);
const fmtInt = (v: number) => Math.round(v).toLocaleString("ru-RU");
const pct = (v: number) => `${v.toFixed(1)}%`;
const pointsTotal = (p: Points) => Object.values(p).reduce((a, b) => a + (Number(b) || 0), 0);

// ---------------------------------------------------------------- WC3 tooltips
const WC3_TOKEN = /\|c([0-9a-fA-F]{8})|\|r|\|n/gi;
function wc3Rich(tip: string) {
  const out: ReactNode[] = [];
  let color: string | null = null;
  let last = 0;
  let key = 0;
  const push = (s: string) => {
    if (s) out.push(color ? <span key={key++} style={{ color }}>{s}</span> : s);
  };
  WC3_TOKEN.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = WC3_TOKEN.exec(tip))) {
    push(tip.slice(last, m.index));
    if (m[1]) color = "#" + m[1].slice(2);
    else if (m[0].toLowerCase() === "|n") push("\n");
    else color = null;
    last = WC3_TOKEN.lastIndex;
  }
  push(tip.slice(last));
  return out;
}

type TipPos = { x: number; y: number } | null;
function Wc3Name({ name, title, tip }: { name: ReactNode; title?: string; tip?: string | null }) {
  const [pos, setPos] = useState<TipPos>(null);
  if (!tip) return <>{name}</>;
  const move = (e: { clientX: number; clientY: number }) => setPos({ x: e.clientX, y: e.clientY });
  let box = null;
  if (pos) {
    const width = 380;
    const left = Math.max(8, Math.min(pos.x + 18, window.innerWidth - width - 8));
    const vertical = pos.y < window.innerHeight * 0.5 ? { top: pos.y + 20 } : { bottom: window.innerHeight - pos.y + 14 };
    box = (
      <div className="wc3tip" style={{ left, width, ...vertical }}>
        <div className="wc3tip-title">{title ?? name}</div>
        <div className="wc3tip-body">{wc3Rich(tip)}</div>
      </div>
    );
  }
  return (
    <span className="tipname" onMouseEnter={move} onMouseMove={move} onMouseLeave={() => setPos(null)}>
      {name}
      {box}
    </span>
  );
}

// ---------------------------------------------------------------- state
function readHash(specs: SpecDef[]): { spec?: string; pool?: string; place?: number } {
  try {
    const [spec, pool, place] = decodeURIComponent(window.location.hash.replace(/^#/, "")).split("/");
    if (!specs.some((s) => s.id === spec)) return {};
    return { spec, pool, place: Number(place) || undefined };
  } catch (e) {
    return {};
  }
}
function writeHash(value: string) {
  try {
    if (window.location.hash !== "#" + value) window.history.replaceState(null, "", "#" + value);
  } catch (e) {
    /* file:// in some browsers */
  }
}

// The six slots, identical copies merged into one tile with a count (stack items).
function groupItems(items: Run["items"]): Array<[Run["items"][number], number]> {
  const out: Array<[Run["items"][number], number]> = [];
  for (const it of items) {
    const hit = out.find(([o]) => o.code === it.code);
    if (hit) hit[1] += 1;
    else out.push([it, 1]);
  }
  return out;
}

// ---------------------------------------------------------------- sections
function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      <div className="card-head">
        <h2 className="card-title">{title}</h2>
        {aside ? <div className="card-aside">{aside}</div> : null}
      </div>
      {children}
    </section>
  );
}

function SourceBars({ run, tipName }: { run: Run; tipName: (n: string) => ReactNode }) {
  const total = run.sources.reduce((a, r) => a + r[1], 0) || 1;
  const max = Math.max(1, ...run.sources.map((r) => r[1]));
  return (
    <div className="srcbars" role="table">
      <div className="srcbar srcbar-head" role="row">
        <div>Источник</div>
        <div />
        <div className="num">DPS</div>
        <div className="num">Доля</div>
      </div>
      {run.sources.map(([name, dps]) => (
        <div className="srcbar" role="row" key={name}>
          <div className="srcbar-label">{tipName(name)}</div>
          <div className="srcbar-track"><div className="srcbar-fill" style={{ width: `${(dps / max) * 100}%` }} /></div>
          <div className="num mono">{fmt1(dps)}</div>
          <div className="num mono share">{pct((dps / total) * 100)}</div>
        </div>
      ))}
    </div>
  );
}

function actionSec(t: string): number {
  const v = parseFloat(String(t).replace(",", "."));
  return Number.isFinite(v) ? v : -1;
}

function Timeline({ run, tipName, label }: { run: Run; tipName: (n: string) => ReactNode; label: string }) {
  const pre = run.actions.filter(([t]) => actionSec(t) < 0);
  const timed = run.actions.filter(([t]) => actionSec(t) >= 0);
  const lanes = useMemo(() => {
    const order: string[] = [];
    for (const [, n] of timed) if (!order.includes(n)) order.push(n);
    return order;
  }, [run]);
  const [open, setOpen] = useState(false);
  const half = (rows: Array<[string, string]>) =>
    rows.length ? (
      <table className="tbl striped">
        <thead><tr><th className="num">Секунда</th><th>{label}</th></tr></thead>
        <tbody>{rows.map(([t, n], i) => <tr key={i}><td className="num mono">{t}</td><td>{tipName(n)}</td></tr>)}</tbody>
      </table>
    ) : <div className="muted small">Нажатий нет.</div>;
  return (
    <>
      {pre.length ? (
        <div className="chips" style={{ marginBottom: 10 }}>
          {pre.map(([, n], i) => <span className="chip" key={i}>до боя · {tipName(n)}</span>)}
        </div>
      ) : null}
      <div className="lanes">
        <div className="lane lane-axis">
          <div />
          <div className="lane-track axis">
            {[0, 5, 10, 15, 20, 25, 30].map((s) => <span key={s} style={{ left: `${(s / FIGHT) * 100}%` }}>{s}</span>)}
          </div>
          <div />
        </div>
        {lanes.map((name, li) => {
          const hits = timed.filter(([, n]) => n === name);
          const color = LANE_COLORS[li % LANE_COLORS.length];
          return (
            <div className="lane" key={name}>
              <div className="lane-label">{tipName(name)}</div>
              <div className="lane-track">
                {hits.map(([t], i) => (
                  <span key={i} className="tick" title={`${t} с — ${name}`} style={{ left: `${(actionSec(t) / FIGHT) * 100}%`, background: color }} />
                ))}
              </div>
              <div className="lane-count mono">×{hits.length}</div>
            </div>
          );
        })}
      </div>
      <button type="button" className="linkbtn" onClick={() => setOpen(!open)}>
        {open ? "Скрыть список нажатий" : `Показать все нажатия по секундам (${run.actions.length})`}
      </button>
      {open ? (
        <div className="two-col" style={{ marginTop: 10 }}>
          {half(run.actions.filter(([t]) => actionSec(t) < 15))}
          {half(run.actions.filter(([t]) => actionSec(t) >= 15))}
        </div>
      ) : null}
    </>
  );
}

function ScanBars({ values, picked, table }: { values?: Record<string, number>; picked: string[]; table: TipTable }) {
  if (!values || !Object.keys(values).length) return <div className="muted small">Нет данных.</div>;
  const rows = Object.entries(values).sort((a, b) => b[1] - a[1]);
  const max = rows[0][1] || 1;
  const min = Math.min(...rows.map((r) => r[1]));
  const lo = Math.max(0, min - (max - min) * 0.25);
  return (
    <div className="scan">
      {rows.map(([name, dps]) => {
        const on = picked.includes(name);
        return (
          <div className={"scan-row" + (on ? " on" : "")} key={name}>
            <div className="scan-label"><Wc3Name name={name} tip={table.find((r) => r[0] === name)?.[1]} /></div>
            <div className="srcbar-track"><div className="srcbar-fill" style={{ width: `${((dps - lo) / (max - lo || 1)) * 100}%` }} /></div>
            <div className="num mono">{fmt1(dps)}</div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- spec view
function SpecView({ cfg, spec, specTabs, initial }: { cfg: PageConfig; spec: SpecDef; specTabs: ReactNode; initial: { pool?: string; place?: number } }) {
  const data = spec.data;
  const pools = POOLS.filter(([id]) => data.runs[id] && data.runs[id].length);
  const [rawMode, setMode] = useCanvasState<string>(`${cfg.hero}-${spec.id}-pool`, "mixed");
  const [rawPlace, setPlace] = useCanvasState<number>(`${cfg.hero}-${spec.id}-place`, 1);
  useEffect(() => {
    if (initial.pool && pools.some(([id]) => id === initial.pool)) setMode(initial.pool);
    if (initial.place) setPlace(initial.place);
    initial.pool = undefined;
    initial.place = undefined;
  }, []);
  const mode = pools.some(([id]) => id === rawMode) ? rawMode : "mixed";
  const list = data.runs[mode];
  const place = Math.min(Math.max(1, Math.floor(Number(rawPlace)) || 1), list.length);
  const run = list[place - 1];
  const best = list[0];
  useEffect(() => writeHash(`${spec.id}/${mode}/${place}`), [spec.id, mode, place]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && /input|textarea|select/i.test(el.tagName)) return;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") { setPlace(Math.min(list.length, place + 1)); e.preventDefault(); }
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") { setPlace(Math.max(1, place - 1)); e.preventDefault(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [list.length, place]);

  const tipName = (n: string) => {
    const t = cfg.nameTips[n];
    return t ? <Wc3Name name={n} title={t[0]} tip={t[1]} /> : n;
  };
  const tipList = (names: string[], table: TipTable) =>
    names.length ? (
      <div className="chips">
        {names.map((n) => <span className="chip" key={n}><Wc3Name name={n} tip={table.find((r) => r[0] === n)?.[1]} /></span>)}
      </div>
    ) : <span className="muted">нет</span>;
  const top = data.top ?? Number((/top(\d+)/.exec(data.farm_file) || [])[1] || 0);
  const attrs = run.stats.filter(([label]) => label !== "Мана в конце");
  const esc = ESC_LABELS.filter(([k]) => (run.points[k] ?? 0) !== 0);
  const delta = best.dps ? (run.dps / best.dps - 1) * 100 : 0;
  const poolHint = pools.find(([id]) => id === mode)?.[2] ?? "";

  return (
    <div className="sims" style={{ ["--cls" as any]: cfg.color }}>
      <header className="hero">
        <div className="hero-row">
          <div>
            <div className="eyebrow">Sunken City v2.5.2b · уровень {data.level} · {data.targets} целей · 30 секунд · ожидаемый урон</div>
            <h1 className="hero-title">{spec.title}</h1>
          </div>
          {specTabs}
        </div>
        <div className="hero-meta">
          Полный перебор Top-{top || "?"} + Mind Amplifier на GPU (OpenCL, бит в бит с CPU): {fmtInt(data.done)} шестёрок · ESC {pointsTotal(run.points)} очков
          {mode === "lantern" ? <> · Soul Lantern: отдельный прогон ({fmtInt(data.lantern_done ?? 0)} шестёрок), бои пересчитаны текущим симом</> : null}
        </div>
      </header>

      <div className="toolbar">
        <div className="seg" role="tablist" aria-label="Пул предметов">
          {pools.map(([id, label, hint]) => (
            <button key={id} type="button" role="tab" title={hint} aria-selected={mode === id}
              className={"seg-btn" + (mode === id ? " on" : "")} onClick={() => { setMode(id); setPlace(1); }}>{label}</button>
          ))}
        </div>
        <div className="muted small">{poolHint} · ← → — соседнее место</div>
      </div>

      <div className="layout">
        <aside className="ranks" aria-label="Места">
          {list.map((r, i) => {
            const d = best.dps ? (r.dps / best.dps) * 100 : 100;
            return (
              <button key={i} type="button" className={"rank" + (i === place - 1 ? " on" : "")} onClick={() => setPlace(i + 1)}>
                <span className="rank-n">{i + 1}</span>
                <span className="rank-body">
                  <span className="rank-dps mono">{fmt1(r.dps)}</span>
                  <span className="rank-bar"><span style={{ width: `${Math.max(4, (d - 80) * 5)}%` }} /></span>
                </span>
                <span className="rank-delta mono">{i ? `${(d - 100).toFixed(1)}%` : "лучший"}</span>
              </button>
            );
          })}
        </aside>

        <div className="detail">
          <div className="kpis">
            <div className="kpi main">
              <div className="kpi-v mono">{fmt1(run.dps)}</div>
              <div className="kpi-l">DPS · место {place} {place > 1 ? <span className="neg">{delta.toFixed(1)}% от №1</span> : null}</div>
            </div>
            <div className="kpi"><div className="kpi-v mono">{fmtInt(run.total)}</div><div className="kpi-l">Урон за 30 с</div></div>
            <div className="kpi"><div className="kpi-v mono">{run.manaLeft.toFixed(0)}%</div><div className="kpi-l">Мана в конце</div></div>
            <div className="kpi"><div className="kpi-v mono">{pointsTotal(run.points)}</div><div className="kpi-l">Очков ESC</div></div>
          </div>

          <Section title="Сборка" aside={<span className="muted small mono">чанк {run.chunk}</span>}>
            <div className="items">
              {groupItems(run.items).map(([it, n], i) => (
                <div className="item" key={i}>
                  <span className="item-top">
                    <span className={"src src-" + it.source} title={SOURCE_TITLE[it.source] ?? it.source}>{SOURCE_LABEL[it.source] ?? it.source}</span>
                    {n > 1 ? <span className="item-count mono" title={`${n} копии в сборке`}>×{n}</span> : null}
                  </span>
                  <span className="item-name"><Wc3Name name={it.name} tip={cfg.itemTips[it.code]} /></span>
                  {it.code === DIAMOND_RING ? <span className="item-note">привязан: {run.bound_spell ?? "нет"}</span> : null}
                </div>
              ))}
            </div>
            <div className="kv">
              <div className="kv-k">Таланты</div><div>{tipList(run.talents, cfg.talents)}</div>
              <div className="kv-k">Глифы</div><div>{tipList(run.glyphs, cfg.glyphs)}</div>
              <div className="kv-k">Очки ESC</div>
              <div>
                {esc.length ? <div className="chips">{esc.map(([k, label]) => <span className="chip esc" key={k}>{label} <b className="mono">{run.points[k]}</b></span>)}</div> : <span className="muted">все 0</span>}
              </div>
              {run.bound_spell ? <><div className="kv-k">Diamond Ring</div><div>привязан к {run.bound_spell}</div></> : null}
              {run.orb_mode ? <><div className="kv-k">Elemental Orb</div><div>{run.orb_mode}</div></> : null}
            </div>
          </Section>

          <Section title="Урон по источникам" aside={<span className="muted small">{run.sources.length} источников</span>}>
            <SourceBars run={run} tipName={tipName} />
          </Section>

          <Section title="Атрибуты в бою">
            <div className="attrs">
              {attrs.map(([label, value]) => (
                <div className="attr" key={label}><div className="attr-v mono">{value}</div><div className="attr-l">{label}</div></div>
              ))}
            </div>
          </Section>

          <Section title="Порядок кнопок" aside={<span className="muted small">0–30 с, отметка = нажатие</span>}>
            <Timeline run={run} tipName={tipName} label={cfg.actionLabel ?? "Кнопка"} />
          </Section>

          {run.talentDps || run.glyphDps ? (
            <details className="card fold">
              <summary className="card-head"><h2 className="card-title">Альтернативы: таланты и глифы для этой сборки</h2><span className="muted small">лучший DPS с каждым, остальное как в сборке</span></summary>
              <div className="two-col">
                <div><h3 className="h3">Таланты</h3><ScanBars values={run.talentDps} picked={run.talents} table={cfg.talents} /></div>
                <div><h3 className="h3">Глифы</h3><ScanBars values={run.glyphDps} picked={run.glyphs} table={cfg.glyphs} /></div>
              </div>
            </details>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function ClassPage({ cfg }: { cfg: PageConfig }) {
  const hash = useMemo(() => readHash(cfg.specs), []);
  const [rawSpec, setSpec] = useCanvasState<string>(`${cfg.hero}-spec`, cfg.specs[0].id);
  useEffect(() => { if (hash.spec) setSpec(hash.spec); }, []);
  const spec = cfg.specs.find((s) => s.id === rawSpec) ?? cfg.specs[0];
  const specTabs = (
    <div className="seg spec" role="tablist" aria-label="Специализация">
      {cfg.specs.map((s) => (
        <button key={s.id} type="button" role="tab" aria-selected={s.id === spec.id}
          className={"seg-btn" + (s.id === spec.id ? " on" : "")} onClick={() => setSpec(s.id)}>{s.pill}</button>
      ))}
    </div>
  );
  return <SpecView key={spec.id} cfg={cfg} spec={spec} specTabs={specTabs} initial={hash.spec === spec.id ? hash : {}} />;
}

