const {readProjectFile}=require('./support.cjs');
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element{constructor(){this.children=[];this.listeners={};this.dataset={};this.classList={toggle(){}};}append(...children){this.children.push(...children);}replaceChildren(){this.children=[];}setAttribute(){}addEventListener(type,fn){this.listeners[type]=fn;}}
const elements={};const $=id=>elements[id]??=new Element();
const context=vm.createContext({$,document:{createElement:()=>new Element()},Map,Set,JSON});
vm.runInContext(readProjectFile('web/static/gallery_compare.js','utf8'),context);
const Rows=vm.runInContext('comparisonRows',context),canonical=vm.runInContext('comparisonCanonical',context);
const rows=Rows({settings:{seed:0,use_wd:false,clip_skip:0,generation_effective:{steps:30,cfg:7},loras:[]},generation_settings:{steps:28,cfg:0},result:{positive:'<script>test</script>'}});
const values=new Map(rows);assert.equal(values.get('シード'),0);assert.equal(values.get('WD Tagger'),false);assert.equal(values.get('Steps'),28);assert.equal(values.get('CFG'),0);assert.equal(values.get('最終Positive'),'<script>test</script>');
assert.equal(canonical({a:1,b:2}),canonical({b:2,a:1}));assert.notEqual(canonical(false),canonical(null));assert.notEqual(canonical(0),canonical(null));assert.equal(Rows({}).length,rows.length);
const Compare=vm.runInContext('GalleryComparison',context),compare=new Compare(),cards=[];
for(let i=0;i<6;i++){const item={job_id:'job'+i,filename:'image.png'};const card=new Element(),body=new Element();compare.register(item,card,body);cards.push(compare.controls.get(compare.key(item)).checkbox);}
for(let i=0;i<5;i++){cards[i].checked=true;cards[i].listeners.change();}
assert.equal(compare.selected.size,5);assert.equal(cards[5].disabled,true);assert.equal($('open-comparison').disabled,false);
cards[5].checked=true;cards[5].listeners.change();assert.equal(compare.selected.size,5);assert.equal(cards[5].checked,false);
cards[0].checked=false;cards[0].listeners.change();assert.equal(cards[5].disabled,false);
$('clear-comparison').listeners.click();assert.equal(compare.selected.size,0);assert.equal($('open-comparison').disabled,true);
console.log('Gallery compare passed: max five, minimum two, deselection, actual sampler values, zero/false/missing distinctions and canonical object equality.');
