const {readProjectFile}=require('./support.cjs');
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element {
 constructor(){this.children=[];this.dataset={};this.attributes={};this.hidden=false;}
 append(child){this.children.push(child);}
 setAttribute(k,v){this.attributes[k]=v;}
 removeAttribute(k){delete this.attributes[k];if(k==='value')delete this.value;}
}
const nodes={};const root=new Element();root.querySelector=id=>nodes[id]??=new Element();
const timers=new Set();let counter=0;
const context=vm.createContext({document:{createElement:()=>new Element()},Date,
 setInterval(){const id=++counter;timers.add(id);return id;},clearInterval(id){timers.delete(id);}});
vm.runInContext(readProjectFile('web/static/job_progress.js','utf8'),context);
const View=vm.runInContext('JobProgressView',context),view=new View(root);
const job={state:'running',created_at:new Date(Date.now()-10000).toISOString(),settings:{execute:true},progress:{stage:'analysis',detail:'Qwen解析中'}};
view.render(job);assert.equal(nodes['#progress-bar'].value,undefined);assert.equal(nodes['#progress-spinner'].hidden,false);
assert.equal(view.steps[1].item.dataset.state,'current');assert.equal(timers.size,1);
view.render({...job,progress:{stage:'generate',current:12,total:28}});
assert.equal(nodes['#progress-bar'].value,12);assert.equal(nodes['#progress-bar'].max,28);
assert.equal(root.hidden,false);assert(nodes['#progress-state'].textContent.includes('画像生成'));assert(nodes['#progress-label'].textContent.includes('12 / 28'));assert(nodes['#progress-elapsed'].textContent.includes('経過'));
view.setSuppressed(true);assert(root.hidden);view.render({...job,progress:{stage:"generate",current:12,total:28}});assert(root.hidden);view.setSuppressed(false);assert.equal(root.hidden,false);
assert(nodes['#progress-label'].textContent.includes('12 / 28'));assert.equal(timers.size,1);
view.render({...job,progress:{stage:'generate',detail:'デコード中'}});assert.equal(nodes['#progress-bar'].value,undefined);
view.render({...job,progress:{stage:'queue',current:12,total:28,detail:'キュー待ち'}});assert.equal(nodes['#progress-bar'].value,undefined);
view.render({...job,state:'error',message:'OOM',progress:{stage:'generate',current:12,total:28},finished_at:new Date().toISOString()});
assert.equal(nodes['#progress-spinner'].hidden,true);assert.equal(nodes['#progress-bar'].hidden,true);
assert.equal(view.steps[3].item.dataset.state,'failed');assert.equal(timers.size,0);
view.render(job);view.disconnected('接続エラー');assert.equal(nodes['#progress-state'].textContent,'接続確認');assert.equal(timers.size,0);
view.render({...job,state:'done',message:'作成完了',settings:{execute:false},progress:{stage:'done'},finished_at:new Date().toISOString()});
assert.equal(view.steps[3].item.dataset.state,'skipped');assert.equal(nodes['#progress-bar'].value,1);assert.equal(timers.size,0);
view.render({...job,cancel_requested:true});assert.equal(nodes['#progress-state'].textContent,'停止処理中…');
view.render({...job,state:'cancelled',message:'停止しました',finished_at:new Date().toISOString()});assert.equal(nodes['#progress-state'].textContent,'停止済み');assert.equal(nodes['#progress-spinner'].hidden,true);assert.equal(timers.size,0);
console.log('Progress UI passed: indeterminate phases, measured steps only, reset on decode, error/disconnect, elapsed timer and generation skip.');
