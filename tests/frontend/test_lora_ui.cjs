const {readProjectFile}=require('./support.cjs');
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const elements = new Map();
const documentListeners = {};
function $(id) {
  if (!elements.has(id)) elements.set(id, {
    value:'', disabled:false, hidden:false, listeners:{}, children:[],
    addEventListener(name,fn){this.listeners[name]=fn;},
    replaceChildren(){this.children=[];this.value='';},
    append(option){this.children.push(option);if(this.children.length===1)this.value=option.value;},
    querySelectorAll(){return [];},setAttribute(){},dataset:{},focus(){}
  });
  return elements.get(id);
}
let records = {'folder/style.safetensors':{trigger:'style_token',url:'',note:''}};
const context = vm.createContext({
  $, managerInitiallyOpen:false, CustomEvent:class{constructor(type,data){this.type=type;this.detail=data.detail;}},document:{createElement(){return {dataset:{},append(){},addEventListener(){},setAttribute(){}};},dispatchEvent(){},addEventListener(type,handler){documentListeners[type]=handler;}},
  URL,
  window:{confirm(){return true;},addEventListener(){},location:{href:'http://localhost/loras'}},
  async getJSON(url,options){
    if(url==='/api/lora-samples/names')return {names:[]};
    if(url.startsWith('/api/lora-samples?'))return {items:[]};
    if(url==='/api/generation-options')return {loras:['folder/style.safetensors','detail.safetensors'],warnings:[]};
    if(options){
      const row=JSON.parse(options.body);
      if(options.method==='DELETE')delete records[row.name];
      else records[row.name]={trigger:row.trigger,url:row.url,note:row.note};
    }
    return {records:structuredClone(records)};
  }
});
for(const name of ['lora_catalog','lora_samples','lora_manager_list','lora_manager'])vm.runInContext(readProjectFile('web/static/'+name+'.js','utf8'),context);
vm.runInContext('initializeLoraManager()',context);
(async()=>{
  await vm.runInContext('registryReady',context);
  $('lora-0').value='folder/style.safetensors';
  await vm.runInContext('fillLoraTrigger(0)',context);
  assert.equal($('lora-0-trigger').value,'style_token');
  $('lora-0-trigger').value='one_time_edit';
  await vm.runInContext('loadManagedLoras()',context);
  $('managed-lora').value='folder/style.safetensors';
  await vm.runInContext('readManagedRecord()',context);
  $('managed-trigger').value='updated_token';
  vm.runInContext("managerDirty = managedFormValue() !== managerSnapshot; updateManagerSaveState()",context);
  assert($('manager-save-state').textContent.includes('未保存'));
  $('managed-trigger').value='style_token';
  vm.runInContext("managerDirty = managedFormValue() !== managerSnapshot; updateManagerSaveState()",context);
  assert($('manager-save-state').textContent.includes('保存済み'));
  $('managed-trigger').value='updated_token';
  vm.runInContext('managerDirty = true',context);
  context.window.confirm=()=>false;
  let prevented=false,stopped=false;
  const link={href:'http://localhost/gallery',target:'',hasAttribute(){return false;},getAttribute(){return '/gallery';}};
  const navigation={target:{closest(){return link;}},button:0,preventDefault(){prevented=true;},stopImmediatePropagation(){stopped=true;}};
  documentListeners.click(navigation);
  assert(prevented&&stopped);assert.equal($('managed-trigger').value,'updated_token');assert.equal(vm.runInContext('managerDirty',context),true);
  context.window.confirm=()=>true;
  documentListeners.click(navigation);assert.equal(vm.runInContext('managerDirty',context),false);
  await vm.runInContext('saveManagedLora(false)',context);
  assert.equal(records['folder/style.safetensors'].trigger,'updated_token');
  assert.equal($('lora-0-trigger').value,'one_time_edit');
  $('lora-1').value='folder/style.safetensors';
  await vm.runInContext('fillLoraTrigger(1)',context);
  assert.equal($('lora-1-trigger').value,'updated_token');
  $('lora-1').value='';
  await vm.runInContext('fillLoraTrigger(1)',context);
  assert.equal($('lora-1-trigger').value,'');
  $('lora-2').value='detail.safetensors';
  await vm.runInContext('fillLoraTrigger(2)',context);
  assert.equal($('lora-2-trigger').value,'');
  $('instruction').value='keep my input';
  vm.runInContext('showManager()',context);
  assert.equal($('workspace').hidden,true);
  await $('close-lora-manager').listeners.click();
  assert.equal($('workspace').hidden,false);
  assert.equal($('instruction').value,'keep my input');
  console.log('LoRA UI logic passed: auto-fill, per-run edits, save, clear, unregistered, navigation.');
})().catch(error=>{console.error(error);process.exitCode=1;});

const olderContext=vm.createContext({$:id=>id==='managed-sample-files'?null:$(id),managerInitiallyOpen:false,CustomEvent:class{constructor(type,data){this.type=type;this.detail=data.detail;}},document:{createElement(){return {dataset:{},append(){},addEventListener(){},setAttribute(){}};},dispatchEvent(){},addEventListener(){},querySelector(){return null;}},window:{confirm(){return true;},addEventListener(){},location:{href:'http://localhost/loras'}},getJSON:async(url,options)=>{if(url==='/api/lora-samples/names')throw Error('older server');return context.getJSON(url,options);}});
for(const name of ['lora_catalog','lora_samples','lora_manager_list','lora_manager'])vm.runInContext(readProjectFile('web/static/'+name+'.js','utf8'),olderContext);
vm.runInContext('initializeLoraManager()',olderContext);
vm.runInContext('loadManagedLoras()',olderContext).then(()=>{assert($('managed-lora').children.length>=2);console.log('Standalone manager passed without a global LoraSamples, sample controls, or sample API.');}).catch(error=>{console.error(error);process.exitCode=1;});
