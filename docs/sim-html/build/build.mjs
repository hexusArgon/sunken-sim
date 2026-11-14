import * as esbuild from "esbuild";
import fs from "fs";
const OUT = "..";
const pages = [["paladin","Paladin"],["priest","Priest"],["shaman","Shaman"],["mage","Mage"],["druid","Druid"],["berserker","Berserker"],["hunter","Hunter"]];
const css = fs.readFileSync("style.css","utf8");
const nav = (cur) => `<nav class="topnav"><a href="index.html">← Sunken City sims</a>${pages.map(([f,t])=>`<a href="${f}.html"${f===cur?' class="cur"':''}>${t}</a>`).join("")}</nav>`;
// Optional page names build only those pages; default remains all pages.
const requested = process.argv.slice(2);
if (requested.some(f => !pages.some(([name]) => name === f))) throw new Error("Unknown page: " + requested.join(", "));
for (const [f, title] of pages.filter(([name]) => !requested.length || requested.includes(name))) {
  fs.writeFileSync(`entry-${f}.jsx`, `import React from "react";import {createRoot} from "react-dom/client";import App from "../sources/${f}.tsx";createRoot(document.getElementById("root")).render(<App/>);`);
  const r = await esbuild.build({ entryPoints:[`entry-${f}.jsx`], bundle:true, minify:true, write:false, format:"iife", jsx:"automatic", target:"es2018",
    alias:{"cursor/canvas":"./canvas-shim.jsx"}, define:{"process.env.NODE_ENV":'"production"'}, nodePaths:["node_modules"], charset:"utf8" });
  const js = r.outputFiles[0].text.replace(/<\/script/gi,"<\\/script");
  const html = `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title} — Sunken City sims</title><style>${css}</style></head><body>${nav(f)}<main class="page" id="root"></main><script>${js}</script></body></html>`;
  fs.writeFileSync(`${OUT}/${f}.html`, html);
  console.log(f, html.length);
}

