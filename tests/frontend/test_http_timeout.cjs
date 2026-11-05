const {readProjectFile}=require('./support.cjs');
const vm=require('node:vm'),assert=require('node:assert/strict');
let calls=0,mode='hang';
const context=vm.createContext({document:{getElementById(){}},AbortController,setTimeout,clearTimeout,
 fetch:async()=>{calls++;if(mode==='hang')return new Promise(()=>{});if(mode==='body')return {ok:true,json:()=>new Promise(()=>{})};if(mode==='disconnect')throw Error('network lost');return {ok:true,json:async()=>{throw Error('bad JSON');}};}});
vm.runInContext(readProjectFile('web/static/ui_common.js'),context);
(async()=>{
 for(const type of ['hang','body','disconnect','invalid']){
  mode=type;
  await assert.rejects(vm.runInContext("getJSON('/api/jobs',{method:'POST',timeoutMs:5})",context),error=>error.outcomeUnknown===true);
 }
 assert.equal(calls,4,'writes are never retried');
 mode='hang';await assert.rejects(vm.runInContext("getJSON('/api/history',{timeoutMs:5})",context),error=>!error.outcomeUnknown);
 console.log('HTTP wait ends on stalled fetch, invalid JSON and disconnect, including ambiguous write outcomes; no automatic POST retry.');
})().catch(error=>{console.error(error);process.exitCode=1;});
