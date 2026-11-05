const {readProjectFile}=require('./support.cjs');
const vm=require('node:vm'),assert=require('node:assert/strict');
const source=readProjectFile('web/static/model_settings.js');
const nodes={};
const $=id=>nodes[id]??={value:'',textContent:'',children:[],replaceChildren(){this.children=[];this.value='';},append(item){this.children.push(item);if(this.children.length===1)this.value=item.value;}};
const requests=[];
const ctx=vm.createContext({$,generationOptionsRequest:0,availableModels:[{family:'sdxl'}],generationWarnings:[],
 loraCatalog:[{name:'sdxl/keep',family:'sdxl'},{name:'sdxl/remove',family:'sdxl'}],document:{createElement:()=>({})},
 getJSON:()=>new Promise((resolve,reject)=>requests.push({resolve,reject}))});
vm.runInContext(source.slice(source.indexOf('function compatibleLoraNames()'),source.indexOf('function chooseModel()')),ctx);
const refresh=()=>vm.runInContext('loadGenerationOptions()',ctx);
const selection=()=>[$('lora-0').value,$('lora-0-trigger').value];
(async()=>{
 $('generation-model').value='0';vm.runInContext('filterLoras()',ctx);
 $('lora-0').value='sdxl/keep';$('lora-0-trigger').value='edited';
 $('lora-1').value='sdxl/remove';$('lora-1-trigger').value='removed trigger';
 let pending=refresh();assert.deepEqual(selection(),['sdxl/keep','edited']);
 requests.shift().reject(Error('offline'));await pending;
 assert.deepEqual(selection(),['sdxl/keep','edited']);assert.match($('lora-hint').textContent,/確認に失敗/);
 pending=refresh();requests.shift().resolve({loras_available:false,lora_options:[],warnings:['unavailable']});await pending;
 assert.deepEqual(selection(),['sdxl/keep','edited']);
 const older=refresh(),old=requests.shift(),newer=refresh(),latest=requests.shift();
 latest.resolve({lora_options:[{name:'sdxl/keep',family:'sdxl'}],samplers:[],schedulers:[]});await newer;
 old.resolve({lora_options:[],samplers:[],schedulers:[]});await older;
 assert.deepEqual(selection(),['sdxl/keep','edited']);
 assert.equal($('lora-1').value,'');assert.equal($('lora-1-trigger').value,'');
 const failedOlder=refresh(),staleFailure=requests.shift(),successfulNewer=refresh(),newReply=requests.shift();
 newReply.resolve({lora_options:[{name:'sdxl/keep',family:'sdxl'}],samplers:[],schedulers:[]});await successfulNewer;
 staleFailure.reject(Error('old failure'));await failedOlder;
 assert.deepEqual(selection(),['sdxl/keep','edited']);assert.doesNotMatch($('lora-hint').textContent,/確認に失敗/);
 pending=refresh();requests.shift().resolve({lora_options:[],samplers:[],schedulers:[]});await pending;
 assert.deepEqual(selection(),['','']);assert.match($('lora-hint').textContent,/一覧にないLoRAを解除/);
 console.log('LoRA refresh preserves input on failure, partial upstream failure, delay and stale response; confirmed removal clears it.');
})().catch(error=>{console.error(error);process.exitCode=1;});
