const {readProjectFile}=require('./support.cjs');
const vm=require('node:vm'),assert=require('node:assert/strict');
const elements={};const node=id=>elements[id]??={hidden:true,textContent:'',dataset:{},disabled:false,addEventListener(type,fn){this[type]=fn;}};
const root={hidden:true,dataset:{},querySelector:node},single={hidden:false,dataset:{}};
let active='batch-1',cancelled=false,done=false,failed=false;
const ctx=vm.createContext({Date,encodeURIComponent,setTimeout,clearTimeout,getJSON:async(url,options)=>{
 if(options?.method==='POST'){assert.equal(url,'/api/batches/batch-1/cancel');cancelled=true;return {};}
 if(url==='/api/generation-state')return {active_batch:active};
 if(failed)throw Error('offline');
 return {state:done?'review':'running',current:3,count:10,completed:done?10:2,created_at:new Date(Date.now()-65000).toISOString(),message:'完了',active_job:done?null:{progress:{stage:'generate',detail:'sampling'}}};
}});
vm.runInContext(readProjectFile('web/static/batch_progress.js'),ctx);
vm.runInContext(readProjectFile('web/static/generation_gate.js'),ctx);
const Gate=vm.runInContext('GenerationGate',ctx),gate=new Gate({},{},{},{root,single});
(async()=>{
 gate.setLocalBusy(false);await gate.refresh();
 assert(node('[data-batch-stage]').textContent.includes('3 / 10回目'));assert(node('[data-batch-stage]').textContent.includes('画像生成'));
 assert(node('[data-batch-elapsed]').textContent.includes('1分'));assert.equal(gate.snapshot.showBatch,true);assert.equal(node('[data-batch-review]').href,'/batch/batch-1');
 await gate.cancelBatch();assert(cancelled);assert.equal(node('[data-batch-stop]').disabled,true);
 active=null;done=true;await gate.refresh();assert(node('[data-batch-stage]').textContent.includes('選別待ち'));assert(node('[data-batch-stop]').hidden);
 gate.setLocalBusy(true);assert(root.hidden);assert.equal(gate.snapshot.showBatch,false);
 console.log('Batch runbar passed: iteration, phase, elapsed, review link, cancellation, terminal state and next single run.');
})().catch(e=>{console.error(e);process.exitCode=1;});

const person=vm.createContext({});
vm.runInContext(readProjectFile('web/static/person_state.js'),person);
const state=vm.runInContext('personPreservationState',person);
assert(state(0,true,'sdxl').includes('未適用'));assert(state(1,true,'sdxl').includes('未適用'));
assert(state(2,true,'sdxl').includes('人物維持を使用'));assert(state(2,true,'anima').includes('未適用'));assert(state(2,false,'sdxl').includes('オフ'));

let calls=0,confirmed=0;
const fields={'submit':{disabled:false},'restored-note':{textContent:''},'instruction':{value:'my draft'}};
const history=vm.createContext({$:id=>fields[id],workspaceEdited:true,window:{confirm(){confirmed++;return false;}},getJSON(){calls++;throw Error('must not request');}});
vm.runInContext(readProjectFile('web/static/history.js'),history);
vm.runInContext("selectedHistory={job_id:'saved'}",history);
(async()=>{
 const result=await vm.runInContext('restoreHistory(true)',history);
 assert.equal(result,false);assert.equal(calls,0);assert.equal(confirmed,1);assert.equal(fields.instruction.value,'my draft');
 assert(fields['restored-note'].textContent.includes('キャンセル'));
 console.log('Draft restore passed: cancel keeps editing values and does not fetch or apply saved settings.');
})().catch(e=>{console.error(e);process.exitCode=1;});
