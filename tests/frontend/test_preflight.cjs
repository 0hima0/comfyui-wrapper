const {readProjectFile}=require('./support.cjs');
const vm=require('node:vm'),assert=require('node:assert/strict');
const elements={'preflight-status':{},'preflight-results':{replaceChildren(){},append(){}},'restored-generation':{value:'{"steps":42,"cfg":9}'}};
let payload;
const context=vm.createContext({$:id=>elements[id],readGenerationFields:()=>({cfg:'6'}),loraValues:()=>[],referenceEditor:{entries:[{id:1,file:{}},{id:2,file:null}]},reuseSource:'source',getJSON:async(url,options)=>{payload=JSON.parse(options.body);return {ok:true,checks:[]};}});
vm.runInContext(readProjectFile('web/static/preflight.js'),context);
(async()=>{
 assert.equal(await vm.runInContext('checkDependencies(true)',context),true);
 assert.deepEqual(payload.restored_generation,{steps:42,cfg:9});
 assert.deepEqual(payload.fields,{cfg:'6'});
 assert.deepEqual(payload.reference_ids,[1]);
 assert.equal(payload.reuse_job_id,'source');
 console.log('Preflight passed: restored settings, explicit fields, uploaded references and reuse source sent together.');
})().catch(error=>{console.error(error);process.exitCode=1;});
