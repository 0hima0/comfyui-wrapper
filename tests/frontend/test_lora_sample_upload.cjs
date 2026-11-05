const {readProjectFile}=require('./support.cjs');
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element{constructor(){this.children=[];this.listeners={};this.dataset={};this.value='chosen.png';this.classList={toggle:(name,on)=>this.error=on};}append(...items){this.children.push(...items);}replaceChildren(){this.children=[];}setAttribute(){}addEventListener(kind,fn){this.listeners[kind]=fn;}}
const elements={},$=id=>elements[id]??=new Element();let request,posts=0,revoked=0;
const context=vm.createContext({$,document:{createElement:()=>new Element()},URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){revoked++;}},FormData:class{set(){}append(){}},loraRegistry:{test:{}},getJSON:(url,options)=>{if(options?.method==='POST'){posts++;return request();}return Promise.resolve({items:[]});}});
const source=readProjectFile('web/static/lora_samples.js','utf8');
vm.runInContext(source.slice(source.indexOf('class LoraSamples'),source.indexOf('let loraSamples;')),context);const Samples=vm.runInContext('LoraSamples',context);
(async()=>{
 const samples=new Samples();samples.name='test';let resolve;request=()=>new Promise(done=>resolve=done);
 const file={name:'test.png',size:123};const pending=samples.upload([file]);
 assert.equal(samples.pending.length,1);assert.equal($('managed-sample-pending').children.length,1);assert.equal($('managed-sample-files').value,'chosen.png');assert(samples.busy);
 resolve({items:[{id:'a',filename:'test.png',width:20,height:20,thumbnail_url:'/thumb',image_url:'/image'}]});await pending;
 assert.equal(samples.pending.length,0);assert.equal(samples.items.length,1);assert.equal($('managed-sample-files').value,'');assert($('sample-status').textContent.includes('保存しました'));
 $('managed-sample-files').value='failed.png';request=()=>Promise.reject(Error('permission denied'));
 await samples.upload([{name:'failed.png',size:123}]);assert(samples.failed);assert.equal(samples.pending.length,1);assert.equal($('managed-sample-files').value,'failed.png');assert.equal($('retry-sample-upload').hidden,false);assert($('sample-status').textContent.includes('permission denied'));assert.equal(samples.busy,false);
 request=()=>Promise.resolve({items:samples.items});await $('retry-sample-upload').listeners.click();assert.equal(samples.pending.length,0);assert.equal(samples.failed,false);
 const before=posts;await samples.upload([{name:'big.png',size:6*1024*1024}]);assert.equal(posts,before);assert(samples.failed);assert($('sample-status').textContent.includes('big.png'));assert.equal(samples.pending.length,1);assert.equal($('managed-sample-pending').hidden,false);assert.equal($('retry-sample-upload').hidden,true);
 assert(revoked>=3);console.log('Sample upload passed: immediate preview, success, retained failed files, retry, visible capacity error and no oversize upload.');
})().catch(error=>{console.error(error);process.exitCode=1;});
