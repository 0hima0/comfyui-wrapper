const {readProjectFile}=require('./support.cjs');
const vm=require('node:vm'),assert=require('node:assert/strict');
const nodes={};let preview={replaceWith(next){preview=next;}};
const card={dataset:{batchId:'abc',state:'running',completed:'0'},querySelector(selector){
 if(selector==='.batch-preview')return preview;
 if(selector==='.batch-preview img')return preview.children?.[0]||null;
 return nodes[selector]??={textContent:''};
}};
let requests=[],data={state:'running',completed:1,count:3,message:'working',checkpoint:'model'};
const context=vm.createContext({
 document:{createElement(){return {children:[],append(child){this.children.push(child);},setAttribute(){},replaceWith(next){preview=next;}};}},
 setTimeout(){return 1;},clearTimeout(){}
});
const source=readProjectFile('web/static/batch_list.js');
vm.runInContext(source.slice(0,source.indexOf('const batchListUpdater=')),context);
const Updater=vm.runInContext('BatchListUpdater',context);
const updater=new Updater([card],async url=>{
 requests.push(url);
 return url.startsWith('/api/gallery')?{items:[{thumbnail_url:'/thumb.jpg',checkpoint:'model'}]}:data;
});
(async()=>{
 updater.stopped=false;updater.epoch=1;
 await updater.update(card,1);
 assert(nodes['.batch-state'].textContent.includes('1 / 3'));assert.equal(preview.children[0].src,'/thumb.jpg');
 assert.equal(requests.filter(x=>x.startsWith('/api/gallery')).length,1);
 await updater.update(card,1);
 assert.equal(requests.filter(x=>x.startsWith('/api/gallery')).length,1);
 data={...data,state:'review',completed:3,message:'ready'};
 await updater.update(card,1);assert.equal(card.dataset.state,'review');assert(nodes['.batch-state'].textContent.includes('選別待ち'));
 const before=requests.length;updater.stop();updater.start();await new Promise(r=>setImmediate(r));assert.equal(requests.length,before);updater.stop();
 let resolve;const stale=new Updater([card],()=>new Promise(done=>resolve=done));stale.stopped=false;stale.epoch=1;
 const pending=stale.update(card,1);stale.stop();resolve({state:'running',completed:0,count:3});await pending;assert.equal(card.dataset.state,'review');
 console.log('Batch list passed: live status, thumbnail updates only on progress, terminal polling stop, stale response discarded.');
})().catch(e=>{console.error(e);process.exitCode=1;});

