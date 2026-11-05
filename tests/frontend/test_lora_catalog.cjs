const {readProjectFile}=require('./support.cjs');
const vm=require('node:vm'),assert=require('node:assert/strict');
let resolveOld,calls=0;
const context=vm.createContext({$:()=>({value:'',textContent:''}),getJSON:async url=>{
 calls++;const name=decodeURIComponent(url.split('name=')[1]);
 if(name==='pending')return new Promise(resolve=>resolveOld=resolve);
 return {records:{[name]:{note:name,tags:[]}}};
}});
vm.runInContext(readProjectFile('web/static/lora_catalog.js'),context);
(async()=>{
 const one=vm.runInContext("loadLoraDetail('pending')",context);
 const two=vm.runInContext("loadLoraDetail('pending')",context);
 assert.equal(calls,1,'concurrent detail reads share a request');
 vm.runInContext("cacheLoraRecord('pending',{note:'newly saved'})",context);
 resolveOld({records:{pending:{note:'stale reply'}}});
 assert.equal((await one).note,'newly saved');assert.equal((await two).note,'newly saved');
 for(const name of ['a','b','c','d','e'])await vm.runInContext(`loadLoraDetail('${name}')`,context);
 assert.equal(vm.runInContext('loraDetails.size',context),4);
 assert.equal(vm.runInContext('Object.keys(loraRegistry).length',context),4);
 assert.equal(vm.runInContext('loraRegistry.pending',context),undefined);
 console.log('Selected LoRA metadata uses a four-record LRU, deduplicates requests and ignores replies older than a saved record.');
})().catch(error=>{console.error(error);process.exitCode=1;});
