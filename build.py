import init, { WasmNodeRouter } from './noderouter.js'
import fs from 'fs'

const nodesLinks = JSON.parse(fs.readFileSync('./nodes_links.json'))
const expl = JSON.parse(fs.readFileSync('./exploration.json'))
const pzs = JSON.parse(fs.readFileSync('./plantzone.json'))

await init()
const router = new WasmNodeRouter(nodesLinks)
console.log('graph: nodes=', router.n, 'towns=', router.townIndices.length)

// build adjacency for INDEPENDENT verification (not using router internals)
const adj = new Map(), cp = new Map(), town = new Set()
for (const [k,v] of Object.entries(nodesLinks)) {
  const key = Number(k)
  cp.set(key, Number(v.need_exploration_point)||0)
  if (v.is_base_town) town.add(key)
  if (!adj.has(key)) adj.set(key, new Set())
  for (const l of v.link_list||[]) {
    const j = Number(l)
    if (!nodesLinks[j]) continue
    adj.get(key).add(j)
    if (!adj.has(j)) adj.set(j, new Set())
    adj.get(j).add(key)
  }
}

function verify(active, pairs) {
  const S = new Set(active)
  // components within S
  const comp = new Map(); let id=0; const townComp=new Set()
  for (const s of S) {
    if (comp.has(s)) continue
    const cid = id++; const st=[s]; comp.set(s,cid)
    while (st.length) {
      const u = st.pop()
      if (town.has(u)) townComp.add(cid)
      for (const v of (adj.get(u)||[])) if (S.has(v) && !comp.has(v)) { comp.set(v,cid); st.push(v) }
    }
  }
  for (const [src,dst] of pairs) {
    if (!S.has(src)) return `source ${src} not activated`
    if (dst === 99999) { if (!townComp.has(comp.get(src))) return `src ${src} not connected to any town` }
    else { if (!S.has(dst)) return `dst ${dst} not activated`
           if (comp.get(src)!==comp.get(dst)) return `pair ${src}->${dst} disconnected` }
  }
  return null
}
const costOf = (active) => active.reduce((s,k)=>s+(cp.get(k)||0),0)

// realistic pairs: plantzones -> towns, plus wildcard grind nodes
const pzKeys = Object.keys(pzs).map(Number).filter(k=>nodesLinks[k])
const townKeys = [...town]
function makePairs(nWorkers, nGrind, seed=1) {
  let s=seed; const rnd=()=>{s=(s*1103515245+12345)&0x7fffffff; return s/0x7fffffff}
  const pairs=[]; const used=new Set()
  for (let i=0;i<nWorkers;i++){
    const pz = pzKeys[Math.floor(rnd()*pzKeys.length)]
    if (used.has(pz)) continue; used.add(pz)
    pairs.push([pz, townKeys[Math.floor(rnd()*townKeys.length)]])
  }
  for (let i=0;i<nGrind;i++){
    const g = pzKeys[Math.floor(rnd()*pzKeys.length)]
    if (used.has(g)) continue; used.add(g)
    pairs.push([g, 99999])
  }
  return pairs
}

let allOk = true
for (const [nw,ng] of [[5,0],[25,3],[60,8],[120,15],[200,25]]) {
  const pairs = makePairs(nw,ng)
  const t0=performance.now()
  const [active, cost] = router.solveForTerminalPairs(pairs)
  const ms=performance.now()-t0
  const err = verify(active, pairs)
  const recomputed = costOf(active)
  // naive baseline: route each pair independently, union (no sharing)
  const solo = new WasmNodeRouter(nodesLinks)
  let union=new Set()
  for (const p of pairs){ const [a]=solo.solveForTerminalPairs([p]); a.forEach(x=>union.add(x)) }
  const naive = costOf([...union])
  const status = err ? `FAIL(${err})` : 'connected-OK'
  if (err) allOk=false
  if (recomputed !== cost) { allOk=false; console.log('  COST MISMATCH', cost, recomputed) }
  console.log(`pairs=${String(pairs.length).padStart(3)} | CP=${String(cost).padStart(4)} | naive=${String(naive).padStart(4)} | saved=${String(naive-cost).padStart(3)} (${((1-cost/naive)*100).toFixed(1)}%) | ${ms.toFixed(0)}ms | ${status}`)
}
console.log(allOk ? '\nALL CHECKS PASS' : '\nFAILURES PRESENT')
