const {readProjectFile}=require('./support.cjs');
const vm=require('node:vm'),assert=require('node:assert/strict');
const source=readProjectFile('web/static/model_settings.js');
const nodes={};const $=id=>nodes[id]??={value:'',disabled:false,children:[],replaceChildren(){this.children=[];this.value='';},append(item){this.children.push(item);}};
let reset=0,filter=0,fail=false;
const entry={name:'selected.safetensors',target:'animagine'};
const ctx=vm.createContext({$,modelRequest:0,availableModels:[],document:{createElement:()=>({})},getJSON:async()=>{if(fail)throw Error('offline');return {models:[entry]};},chooseModel(){reset++;},filterLoras(){filter++;}});
vm.runInContext(source.slice(source.indexOf('async function loadModels()'),source.indexOf('function updateLoraScopes(')),ctx);
(async()=>{
 $('checkpoint').value=entry.name;$('target').value=entry.target;$('profile').value='custom';
 $('steps').value='41';$('cfg').value='6.2';$('restored-generation').value='saved';
 await vm.runInContext('loadModels()',ctx);
 assert.equal(reset,0);assert.equal(filter,1);
 assert.equal($('steps').value,'41');assert.equal($('cfg').value,'6.2');assert.equal($('profile').value,'custom');assert.equal($('restored-generation').value,'saved');
 fail=true;await vm.runInContext('loadModels()',ctx);assert.equal(reset,0);assert.equal($('steps').value,'41');assert.equal($('generation-model').disabled,false);
 fail=false;$('checkpoint').value='removed';await vm.runInContext('loadModels()',ctx);assert.equal(reset,1);
 console.log('Model refresh preserves settings and restored values, including on request failure; missing model uses defaults.');
})().catch(e=>{console.error(e);process.exitCode=1;});
