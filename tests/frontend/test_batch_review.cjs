const {readProjectFile}=require('./support.cjs');
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements={},requests=[],redirects=[],removed=[];
function $(id){return elements[id]??={textContent:'',disabled:false,hidden:false,open:false,dataset:{},listeners:{},classList:{contains:()=>false},querySelector(selector){return $(({'[data-batch-stop]':'batch-stop','[data-batch-detail]':'batch-status'})[selector]||selector);},addEventListener(k,f){this.listeners[k]=f;},showModal(){this.open=true;},close(){this.open=false;}};}
const context=vm.createContext({$,batchId:'test',batchSelected:new Set(['job/image_1.png']),gallerySeen:new Set(['job/image_0.png','job/image_1.png','job/image_2.png']),galleryBusy:false,
 loadGallery:async()=>{},getJSON:async(url,options)=>{requests.push([url,options]);return options?{redirect:'/gallery'}:{state:'review',completed:3,count:3,message:'完了'};},
 window:{location:{assign:url=>redirects.push(url)}},sessionStorage:{removeItem:key=>removed.push(key)},setTimeout(){},JSON,Set});
$('load-more').hidden=true;
vm.runInContext(readProjectFile('web/static/batch_progress.js','utf8'),context);
vm.runInContext(readProjectFile('web/static/batch_review.js','utf8'),context);
(async()=>{
 $('load-more').hidden=true;
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal($('batch-finalize').disabled,false);
 $('batch-finalize').listeners.click();assert($('batch-confirm-dialog').open);
 assert.equal($('batch-confirm-count').textContent,'残す画像：1枚 ／ 削除する画像：2枚');
 assert($('batch-confirm-save').textContent.includes('保存 1枚・削除 2枚'));
 assert(!requests.some(r=>r[1]));
 $('batch-confirm-cancel').listeners.click();assert(!$('batch-confirm-dialog').open);
 assert(!requests.some(r=>r[1]));
 context.batchSelected.clear();$('batch-finalize').listeners.click();assert.equal($('batch-confirm-save').textContent,'すべて破棄する');$('batch-confirm-cancel').listeners.click();context.batchSelected.add('job/image_1.png');
 $('batch-finalize').listeners.click();await $('batch-confirm-save').listeners.click();
 const post=requests.find(r=>r[1]);assert.equal(post[1].method,'POST');assert.deepEqual(JSON.parse(post[1].body),{selected:['job/image_1.png']});
 assert.deepEqual(redirects,['/gallery']);assert.deepEqual(removed,['llmpc-batch-selection-test']);
 console.log('Batch review passed: terminal state, explicit selection, keep/delete counts, cancel without mutation, exact selection sent only after confirmation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
