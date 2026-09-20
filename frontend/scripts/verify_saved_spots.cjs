// Offline behavioral tests; no browser, live account or network required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const ts = require('typescript');
function fixture() {
  const storage = new Map([['sumeungil:nickname:v1', 'A']]);
  const window = new EventTarget();
  window.localStorage = {getItem:k=>storage.get(k) ?? null, setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
  let alerts = 0;
  window.alert = () => alerts++;
  let remote = [], fail = false, reads = null;
  const calls=[];
  const api = {fetchSavedSpots:()=>reads ? reads() : Promise.resolve([...remote]),
    putSavedSpotRemote:async(id)=>{calls.push(['put',id]);if(typeof fail==='function'?fail(id):fail)throw Error('offline');remote.push(spot(id));},
    deleteSavedSpotRemote:async(id)=>{calls.push(['delete',id]);if(fail)throw Error('offline');remote=remote.filter(s=>s.id!==id);}};
  const exports={};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../lib/savedSpotsStorage.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,
    {exports,window,Event,require:(name)=> name==='./api'?api:{AUTH_CHANGED_EVENT:'auth',getNickname:()=>storage.get('sumeungil:nickname:v1') ?? null}});
  return {m:exports,storage,calls,window,setRemote:x=>remote=x,setReads:x=>reads=x,setFail:x=>fail=x,alerts:()=>alerts};
}
const spot=id=>({id,name:'spot',category:'nature',region_code:'11',saved_at:'2026-09-20',congestion:null,is_hidden_gem:false});
const flush=()=>new Promise(r=>setImmediate(r));
(async()=>{
 const f=fixture();
 f.storage.set('sumeungil:saved-spots:v1',JSON.stringify([spot(99)]));
 f.setRemote([spot(1)]);await f.m.syncSavedSpotsFromServer();
 assert.equal(f.m.loadSavedSpots()[0].id,1);assert.equal(f.calls.length,0);
 f.setRemote([]);await f.m.syncSavedSpotsFromServer();assert.equal(f.m.loadSavedSpots().length,0);
 let resolve;f.setReads(()=>new Promise(r=>resolve=r));const pending=f.m.syncSavedSpotsFromServer();
 await flush();f.window.dispatchEvent(new Event('auth'));resolve([spot(8)]);await pending;
 assert.equal(f.m.loadSavedSpots().length,0,'old account fetch must not populate new cache');
 f.setReads(null);f.m.toggleSavedSpot(spot(2));f.m.toggleSavedSpot(spot(2));await flush();
 assert.equal(f.calls.map(c=>c[0]).join(','),'put,delete');
 f.setFail(true);f.m.toggleSavedSpot(spot(3));await flush();
 assert.equal(f.m.isSpotSaved(3),false);assert.equal(f.alerts(),1);
 assert.equal(JSON.parse(f.storage.get('sumeungil:saved-spots:v1'))[0].id,99);
 const g=fixture();g.setFail(id=>id===4);g.m.toggleSavedSpot(spot(4));g.m.toggleSavedSpot(spot(5));await flush();
 assert.equal(g.m.isSpotSaved(4),false);assert.equal(g.m.isSpotSaved(5),true);
 let ok=false, cleared=0, events=0, storageError=false;
 const window=new EventTarget();window.localStorage={getItem:()=>null,removeItem:()=>{if(storageError)throw Error('storage disabled');cleared++;}};
 window.addEventListener('sumeungil:auth-changed',()=>events++);
 const exports={};
 vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../lib/authStorage.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,
  {exports,window,Event,fetch:async()=>({ok}),require:name=>name==='./api'?{API_BASE:'http://unused'}:{clearOnboardingResult:()=>{}}});
 await assert.rejects(exports.deleteAccount());assert.equal(cleared,0);assert.equal(events,0);
 ok=true;storageError=true;await exports.deleteAccount();assert.equal(events,1);
 console.log('PASS: server authority, no resurrection/upload, account isolation, ordered writes, failed-save rollback, guest preservation');
 console.log('PASS: independent write failures, failed deletion retains cache, successful deletion survives storage exception');
})().catch(e=>{console.error(e);process.exitCode=1;});
