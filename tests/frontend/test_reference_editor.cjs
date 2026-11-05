const {readProjectFile}=require('./support.cjs');
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element {
 constructor(){this.children=[];this.listeners={};this.value='';this.classList={add(){},remove(){}};this.accept='image/png,image/jpeg,image/webp';}
 addEventListener(type,fn){this.listeners[type]=fn;}
 append(...items){this.children.push(...items);}
 replaceChildren(){this.children=[];}
 setAttribute(){}
 querySelectorAll(){return this.children.flatMap(child=>[child,...child.querySelectorAll()]);}
}
const revoked=[];let nextUrl=0;
const context=vm.createContext({document:{createElement:()=>new Element()},URL:{createObjectURL(){return 'blob:'+(++nextUrl);},revokeObjectURL(url){revoked.push(url);}}});
vm.runInContext(readProjectFile('web/static/reference_images.js','utf8'),context);
const Editor=vm.runInContext('ReferenceEditor',context);
const controls={input:new Element(),drop:new Element(),list:new Element(),count:new Element(),message:new Element(),maxImages:4};
const editor=new Editor(controls);
const file=name=>({name,type:'image/png',size:1024});
editor.addFiles([file('person.png'),file('clothes.png'),file('background.png')]);
assert.equal(editor.entries.length,3);
const role=controls.list.children[0].children[1].children[2].children[0];role.value='人物';role.listeners.input();
editor.remove(2);assert.deepEqual(Array.from(editor.entries,x=>x.id),[1,3]);assert.equal(editor.entries[0].role,'人物');
editor.addFiles([file('style.png')]);assert.deepEqual(Array.from(editor.entries,x=>x.id),[1,3,4]);
editor.addFiles([file('too-many-a.png'),file('too-many-b.png')]);assert.equal(editor.entries.length,3);
assert(controls.message.textContent.includes('最大4枚'));
const body={values:[],delete(){},append(...args){this.values.push(args);},set(...args){this.values.push(args);}};
editor.appendTo(body);const info=JSON.parse(body.values.find(x=>x[0]==='reference_info')[1]);
assert.deepEqual(info.map(x=>x.id),[1,3,4]);assert.equal(info[0].role,'人物');
editor.restore([{id:1,filename:'person.png',role:'人物'},{id:3,filename:'background.png',role:'背景'}]);
assert.throws(()=>editor.appendTo(body),/再選択/);
editor.addFiles([file('background.png'),file('person.png')]);
assert.deepEqual(Array.from(editor.entries,x=>x.filename),['person.png','background.png']);
assert.equal(editor.entries[1].role,'背景');
editor.replace(1,file('renamed.png'));assert.equal(editor.entries[0].id,1);assert.equal(editor.entries[0].role,'人物');
editor.setDisabled(true);editor.remove(1);editor.addFiles([file('blocked.png')]);assert.equal(editor.entries.length,2);
editor.setDisabled(false);const before=nextUrl;
editor.addFiles([{name:'bad.exe',type:'application/octet-stream',size:1}]);assert.equal(editor.entries.length,2);assert.equal(nextUrl,before);
assert(revoked.length>=4);
console.log('Reference editor passed: multi-add, stable numbering, roles, limits, replacement, restore/reselection, upload serialization and cleanup.');

const retained=file('retained.png');editor.restore([{id:5,filename:retained.name,role:'人物',file:retained}],true);
assert.equal(editor.entries[0].file,retained);assert(editor.entries[0].url);editor.appendTo(body);
assert(body.values.some(x=>x[0]==='image'&&x[1]===retained));
console.log('Reference file restoration passed: file is reusable without reselection.');

editor.restore([]);body.values=[];editor.appendTo(body);
assert.equal(body.values.find(x=>x[0]==='reference_info')[1],'[]');
