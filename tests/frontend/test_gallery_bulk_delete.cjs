const {readProjectFile}=require('./support.cjs');
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element{
 constructor(){this.children=[];this.listeners={};this.classList={toggle(){}};this.textContent='';}
 addEventListener(k,f){this.listeners[k]=f;}append(...items){this.children.push(...items);}replaceChildren(){this.children=[];}setAttribute(k,v){this[k]=v;}showModal(){this.open=true;}close(){this.open=false;}
}
const elements={},requests=[];let reloads=0;
const $=id=>elements[id]??=new Element();
const context=vm.createContext({$,batchId:'',favoriteBusy:false,galleryBusy:false,bulk:null,Map,Set,JSON,
 document:{createElement:()=>new Element(),createTextNode:s=>s},
 galleryComparison:{selected:new Map([['a.png',{job_id:'a'}],['c.png',{job_id:'c'}]]),sync(){}},
 galleryControls(){vm.runInContext('bulk.sync(favoriteBusy||galleryBusy)',context);},
 getJSON:async(url,options)=>{requests.push([url,options]);return {deleted:['a'],skipped:[{job_id:'c',error:'お気に入りを含む実行は削除できません。'}]};},
 loadGallery:async()=>{reloads++;context.bulk.reset();}});
vm.runInContext(readProjectFile('web/static/gallery_bulk_delete.js','utf8'),context);
vm.runInContext('bulk = new GalleryBulkDelete()',context);const bulk=context.bulk;
function card(job,filename,count,protectedJob=false){const item={job_id:job,filename,image_count:count,protected:protectedJob};bulk.register(item,new Element());return bulk.controls.get(job+'/'+filename);}
const a=card('a','one.png',2),a2=card('a','two.png',2),b=card('b','favorite.png',1,true),c=card('c','other.png',1);
$('bulk-select-visible').listeners.click();assert.equal(bulk.selected.size,2);assert(a.checkbox.checked&&a2.checkbox.checked&&c.checkbox.checked);assert(b.checkbox.disabled&&!b.checkbox.checked);
assert.equal($('bulk-delete-count').textContent,'削除対象：2実行 ／ 画像3枚');
bulk.protect('a',true);assert(!a.checkbox.checked&&!a2.checkbox.checked&&a.checkbox.disabled);assert.equal(bulk.selected.size,1);
bulk.protect('a',false);a.checkbox.checked=true;a.checkbox.listeners.change();assert(a2.checkbox.checked);
bulk.open();assert.equal(requests.length,0);assert($('bulk-delete-dialog').open);
$('cancel-bulk-delete').listeners.click();assert(!$('bulk-delete-dialog').open);assert.equal(requests.length,0);
(async()=>{bulk.open();await bulk.remove();assert.equal(requests.length,1);assert.deepEqual(JSON.parse(requests[0][1].body),{job_ids:['c','a']});assert.equal(reloads,1);
 assert(!context.galleryComparison.selected.has('a.png'));assert(context.galleryComparison.selected.has('c.png'));assert($('gallery-status').textContent.includes('1実行を削除しました。1実行は削除しませんでした。'));
 console.log('Bulk delete UI passed: independent selection, grouped outputs, favorites excluded and selection cleared on favorite, explicit confirmation, partial results, and comparison cleanup.');
})().catch(error=>{console.error(error);process.exitCode=1;});
