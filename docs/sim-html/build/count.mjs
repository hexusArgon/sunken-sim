import * as esbuild from "esbuild"; import fs from "fs";
// Counts runs per class. Old canvases: RUNS keys. New mage: DATA[spec].runs[pool] arrays. Druid: farm JSON lists.
const res={};
for (const [f,sym] of [["paladin","RUNS"],["priest","RUNS"],["shaman","RUNS"],["mage","DATA"]]) {
  fs.writeFileSync(`tmp-${f}.tsx`, fs.readFileSync(`../sources/${f}.tsx`,"utf8")+`\nexport { ${sym} };\n`);
  const r = await esbuild.build({entryPoints:[`tmp-${f}.tsx`],bundle:true,write:false,format:"cjs",platform:"node",jsx:"automatic",alias:{"cursor/canvas":"./canvas-shim.jsx"},nodePaths:["node_modules"]});
  const m={exports:{}}; new Function("module","exports","require",r.outputFiles[0].text)(m,m.exports,()=>null);
  fs.unlinkSync(`tmp-${f}.tsx`);
  if (sym==="RUNS") res[f]={total:Object.keys(m.exports.RUNS).length, keys:Object.keys(m.exports.RUNS)};
  else { const by={}; let t=0; for (const [s,v] of Object.entries(m.exports.DATA)) for (const [p,l] of Object.entries(v.runs)) { by[`${s}|${p}`]=l.length; t+=l.length; } res[f]={total:t, byList:by}; }
}
const d=JSON.parse(fs.readFileSync("../sources/druid-balance-farm.json","utf8")); const by={}; let t=0;
for (const k of ["top","top_shop_random","top_shop","top_random"]) { by[k]=d[k].length; t+=d[k].length; }
res.druid={total:t, byList:by};
fs.writeFileSync("runkeys.json",JSON.stringify(res,null,1));
for (const [f,v] of Object.entries(res)) console.log(f, v.total, JSON.stringify(v.byList||""));
