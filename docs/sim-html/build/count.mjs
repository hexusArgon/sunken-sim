import * as esbuild from "esbuild"; import fs from "fs";
const res={};
for (const f of ["paladin","priest","shaman","mage"]) {
  fs.writeFileSync(`tmp-${f}.tsx`, fs.readFileSync(`../sources/${f}.tsx`,"utf8")+"\nexport { RUNS };\n");
  const r = await esbuild.build({entryPoints:[`tmp-${f}.tsx`],bundle:true,write:false,format:"cjs",platform:"node",jsx:"automatic",alias:{"cursor/canvas":"./canvas-shim.jsx"},nodePaths:["node_modules"]});
  const m={exports:{}}; new Function("module","exports","require",r.outputFiles[0].text)(m,m.exports,(x)=>import.meta.resolve?null:null);
  const keys=Object.keys(m.exports.RUNS); res[f]=keys;
  fs.unlinkSync(`tmp-${f}.tsx`);
}
fs.writeFileSync("runkeys.json",JSON.stringify(res,null,1));
for (const [f,k] of Object.entries(res)) console.log(f,k.length, [...new Set(k.map(x=>x.split("|").slice(0,2).join("|")))].join(" "));
