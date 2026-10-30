import React, { useState, useEffect } from "react";

const S = (o) => o;
const toneColor = { success: "var(--success)", info: "var(--info)", warning: "var(--warning)", danger: "var(--danger)", secondary: "var(--fg2)", tertiary: "var(--fg3)" };

export function useCanvasState(key, initial) {
  const k = "canvas:" + key;
  const [v, setV] = useState(() => {
    try { const s = localStorage.getItem(k); if (s != null) return JSON.parse(s); } catch (e) {}
    return initial;
  });
  useEffect(() => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }, [k, v]);
  return [v, setV];
}

export function Stack({ gap = 8, children, style }) {
  return <div style={{ display: "flex", flexDirection: "column", gap, minWidth: 0, ...style }}>{children}</div>;
}
export function Row({ gap = 8, wrap, align, justify, children, style }) {
  return <div style={{ display: "flex", flexDirection: "row", gap, flexWrap: wrap ? "wrap" : "nowrap", alignItems: align === "center" ? "center" : align || "flex-start", justifyContent: justify, ...style }}>{children}</div>;
}
export function Grid({ columns = 2, gap = 8, children, style }) {
  return <div className={"grid grid-" + columns} style={{ display: "grid", gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`, gap, ...style }}>{children}</div>;
}
export const H1 = ({ children }) => <h1 className="h1">{children}</h1>;
export const H2 = ({ children }) => <h2 className="h2">{children}</h2>;
export const H3 = ({ children }) => <h3 className="h3">{children}</h3>;
export function Text({ size, tone, style, children }) {
  return <div className={"text" + (size === "small" ? " small" : "")} style={{ color: tone ? toneColor[tone] : undefined, ...style }}>{children}</div>;
}
export const Divider = () => <hr className="divider" />;
export function Pill({ active, onClick, children }) {
  return <button type="button" className={"pill" + (active ? " active" : "") + (onClick ? "" : " static")} onClick={onClick}>{children}</button>;
}
export function Stat({ value, label, tone }) {
  return <div className="stat"><div className="stat-value mono" style={{ color: tone ? toneColor[tone] : undefined }}>{value}</div><div className="stat-label">{label}</div></div>;
}
export function Callout({ tone = "info", title, children }) {
  return <div className={"callout " + tone}>{title ? <div className="callout-title">{title}</div> : null}<div>{children}</div></div>;
}
export function Table({ headers, rows, columnAlign, striped, stickyHeader, rowTone }) {
  return (
    <div className={"table-wrap" + (stickyHeader ? " sticky" : "")}>
      <table className={"tbl" + (striped ? " striped" : "")}>
        {headers ? <thead><tr>{headers.map((h, i) => <th key={i} style={{ textAlign: columnAlign?.[i] || "left" }}>{h}</th>)}</tr></thead> : null}
        <tbody>
          {rows.map((r, ri) => (
            <tr key={ri} className={rowTone?.[ri] ? "tone-" + rowTone[ri] : ""}>
              {r.map((c, ci) => <td key={ci} style={{ textAlign: columnAlign?.[ci] || "left" }}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function BarChart({ categories, series, valueSuffix = "", showValues, height }) {
  const s = series[0] || { data: [] };
  const vals = s.data.map(Number);
  const max = Math.max(1, ...vals);
  const fmt = (v) => (Number.isInteger(v) ? String(v) : v.toFixed(1));
  return (
    <div className="bars" style={{ minHeight: height ? Math.min(height, categories.length * 30) : undefined }}>
      {categories.map((c, i) => (
        <div className="bar-row" key={i}>
          <div className="bar-label" title={c}>{c}</div>
          <div className="bar-track">
            <div className={"bar-fill " + (s.tone || "info")} style={{ width: (vals[i] / max) * 100 + "%" }} />
          </div>
          {showValues ? <div className="bar-val mono">{fmt(vals[i])}{valueSuffix}</div> : null}
        </div>
      ))}
    </div>
  );
}
