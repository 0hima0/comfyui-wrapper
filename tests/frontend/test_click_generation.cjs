const {readProjectFile}=require('./support.cjs');
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=readProjectFile('web/static/generation_actions.js','utf8');
const html=readProjectFile('web/templates/index.html','utf8');
assert(html.includes('<button id="submit" type="button">'));
const elements={},handlers={};let valid=true,ready=true,posts=0,validations=0;
function $(id){if(id==='check-dependencies')return null;return elements[id]??={value:'',disabled:false,checked:true,replaceChildren(){},reportValidity(){validations++;return valid;},addEventListener(kind,fn){handlers[id+':'+kind]=fn;}};}
$('checkpoint').value='model.safetensors';$('target').value='anima';
const context=vm.createContext({$,JSON,Date,Uint8Array,crypto:require('node:crypto').webcrypto,activeJob:null,status(){},
 generationGate:{activeBatch:null,refresh:async()=>true,setLocalBusy:value=>{$('submit').disabled=value;}},
 referenceEditor:{appendTo(){},setDisabled(){}},FormData:class{},loraValues:()=>[],batchPlan:()=>null,
 progressView:{render(){},disconnected(){}},loadHistory(){},sessionStorage:{setItem(){},removeItem(){}},
 getJSON:async(url,options)=>{if(options){assert.equal(options.method,'POST');posts++;return {job_id:'test'};}return {state:'cancelled',message:'finished'};},monitor:async()=>{},saveWorkspace:async()=>{},checkDependencies:async()=>ready});
vm.runInContext(source,context);
vm.runInContext('initializeGenerationActions()',context);
(async()=>{
 let prevented=false;
 handlers['form:submit']({preventDefault(){prevented=true;}});
 assert(prevented);assert.equal(posts,0);assert.equal(validations,0);
 valid=false;await handlers['submit:click']();assert.equal(posts,0);
 valid=true;await handlers['submit:click']();assert.equal(posts,1);
 ready=false;await handlers['submit:click']();assert.equal(posts,1);
 $('submit').disabled=true;await handlers['submit:click']();assert.equal(posts,1);
 assert(!source.includes("addEventListener('keydown'"));
 console.log('Generation trigger passed: implicit submit blocked, explicit click runs once, validation and disabled guard retained, no Enter interception.');
})().catch(error=>{console.error(error);process.exitCode=1;});
