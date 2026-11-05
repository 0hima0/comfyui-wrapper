const {readProjectFile}=require('./support.cjs');
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let mode='batch',requests=0,resolveRequest;const timers=new Map();let nextTimer=0;
const context=vm.createContext({encodeURIComponent,
 getJSON:async()=>{requests++;if(mode==='pending')return new Promise(resolve=>resolveRequest=resolve);if(mode==='error')throw Error('offline');return {active_batch:mode==='batch'?'batch-id':null};},
 setTimeout:fn=>{const id=++nextTimer;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id)});
vm.runInContext(readProjectFile('web/static/generation_gate.js','utf8'),context);
const Gate=vm.runInContext('GenerationGate',context),button={},message={},link={},gate=new Gate(button,message,link);
(async()=>{
 gate.setLocalBusy(false);assert(button.disabled);await gate.refresh();assert(button.disabled);assert.equal(button.textContent,'連続生成中');assert.equal(link.href,'/batch/batch-id');
 gate.setLocalBusy(true);gate.setLocalBusy(false);assert(button.disabled); // Restoration/finally must not unlock a live batch.
 mode='none';gate.setLocalBusy(true);await gate.refresh();assert(button.disabled);gate.setLocalBusy(false);assert(!button.disabled);assert.equal(button.textContent,'解析して生成');
 mode='error';await gate.refresh();assert(button.disabled);mode='none';await gate.refresh();assert(!button.disabled);
 mode='pending';const before=requests,pending=gate.refresh(),same=gate.refresh();assert.equal(requests,before+1);
 gate.markBatch('new-batch');resolveRequest({active_batch:null});await Promise.all([pending,same]);assert(button.disabled);assert.equal(gate.activeBatch,'new-batch');
 gate.start();gate.stop();gate.start();resolveRequest({active_batch:null});await new Promise(resolve=>setImmediate(resolve));assert.equal(timers.size,1);gate.stop();assert.equal(timers.size,0);
 console.log('Generation gate passed: startup check, running batch lock, no restore/finally unlock, completion unlock, network failure/recovery, stale response rejection and single polling timer after navigation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
