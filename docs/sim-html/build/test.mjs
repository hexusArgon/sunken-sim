import puppeteer from "puppeteer-core";
const b = await puppeteer.launch({executablePath:"/usr/bin/google-chrome",args:["--no-sandbox","--allow-file-access-from-files"]});
for (const f of ["paladin","priest","shaman","mage"]) {
  const p = await b.newPage(); const errs=[];
  p.on("pageerror",e=>errs.push(e.message)); p.on("console",m=>{if(m.type()==="error")errs.push(m.text())});
  await p.setViewport({width:1280,height:900});
  await p.goto(`file:///workspace/ss/docs/sim-html/${f}.html`);
  await p.screenshot({path:`/workspace/ss/docs/sim-html/build/shot-${f}.png`,fullPage:false});
  // click every pill, record h1 + DPS
  const n = await p.$$eval(".pill",x=>x.length);
  const seen=new Set();
  for (let i=0;i<60;i++){ const pills=await p.$$(".pill"); if(i>=pills.length)break; await pills[i].click();
    seen.add(await p.$eval(".h1",e=>e.textContent)+" | "+await p.$eval(".stat-value",e=>e.textContent)); }
  console.log(f,"pills",n,"states",seen.size,"errors",errs.length, errs.slice(0,2), [...seen].slice(0,4));
  await p.evaluate(()=>localStorage.clear());
}
await b.close();
