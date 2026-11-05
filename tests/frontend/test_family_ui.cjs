const {readProjectFile}=require('./support.cjs');
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=readProjectFile('web/static/model_settings.js','utf8');
const source=html.slice(html.indexOf('function compatibleLoraNames()'),html.indexOf('async function loadGenerationOptions()'));
const elements={};
function $(id){return elements[id]??=( {value:'',textContent:'',hidden:false,disabled:false,children:[],
 replaceChildren(){this.children=[];this.value='';},append(option){this.children.push(option);if(this.children.length===1)this.value=option.value;}} );}
const sandbox={$,selectValue(select,value){select.value=value;},
 availableModels:[{family:'illustrious',family_label:'Illustrious (SDXL)'},{family:'sdxl',family_label:'SDXL'},{family:'sd15',family_label:'SD1.5'},{family:'unknown'}],
 loraCatalog:[{name:'illustrious/style.safetensors',family:'illustrious'},{name:'sdxl/style.safetensors',family:'sdxl'},{name:'sd15/style.safetensors',family:'sd15'},{name:'loose.safetensors',family:'unknown'}],
 generationWarnings:[],document:{createElement(){return {};}}
};
const context=vm.createContext(sandbox);vm.runInContext(source,context);
for(const [index,family] of ['illustrious','sdxl','sd15'].entries()){
 $('generation-model').value=String(index);vm.runInContext('filterLoras()',context);
 assert.deepEqual($('lora-0').children.map(o=>o.value),['',family+'/style.safetensors']);
 assert.equal($('lora-0').disabled,false);
 $('lora-0').value=family+'/style.safetensors';$('lora-0-trigger').value='trigger';
}
$('generation-model').value='0';vm.runInContext('filterLoras()',context);
assert.equal($('lora-0').value,'');assert.equal($('lora-0-trigger').value,'');
assert($('lora-hint').textContent.includes('解除'));
vm.runInContext("restoreLoras([{name:'sd15/style.safetensors',trigger:'incompatible'},{name:'illustrious/style.safetensors',trigger:'historic',strength_model:.7,strength_clip:.6}])",context);
assert.equal($('lora-0').value,'');assert.equal($('lora-1').value,'illustrious/style.safetensors');
assert.equal($('lora-1-trigger').value,'historic');
$('generation-model').value='3';vm.runInContext('filterLoras()',context);
assert.equal($('lora-0').disabled,true);assert.equal($('lora-1-trigger').value,'');
assert($('model-family').textContent.includes('未判定'));
console.log('Family UI logic passed: three filtered lists, clearing on switch, safe history restore, unknown blocked.');

$('generation-model').value='0';$('lora-0-search').value='SD15/';
vm.runInContext('filterLoras()',context);
assert.deepEqual($('lora-0').children.map(o=>o.value),['']);
$('lora-0-search').value='STYLE';vm.runInContext('filterLoras()',context);
assert.deepEqual($('lora-0').children.map(o=>o.value),['','illustrious/style.safetensors']);
$('lora-0').value='illustrious/style.safetensors';$('lora-0-trigger').value='keep';
$('lora-0-search').value='no-match';vm.runInContext('filterLoras()',context);
assert.equal($('lora-0').value,'illustrious/style.safetensors');assert.equal($('lora-0-trigger').value,'keep');
assert.deepEqual($('lora-0').children.map(o=>o.value),['','illustrious/style.safetensors']);
console.log('LoRA search passed: folder/name matching, case insensitive, compatible models only, selected LoRA retained.');

assert($('lora-0-search-status').textContent.includes('検索結果 0件'));
assert($('lora-0-search-status').textContent.includes('検索対象外'));
assert.equal($('lora-0-clear-search').hidden,false);
$('lora-0-search').value='';vm.runInContext('filterLoras()',context);
assert.equal($('lora-0-clear-search').hidden,true);

// Explicit per-checkpoint paths do not depend on the fixed family list.
sandbox.availableModels.push({family:'unknown',target:'animagine',lora_folders:['custom','shared']});
sandbox.loraCatalog.push({name:'custom/nested/style.safetensors',family:'unknown'},{name:'custom2/wrong.safetensors',family:'unknown'},{name:'shared/style.safetensors',family:'unknown'});
$('generation-model').value='4';vm.runInContext('filterLoras()',context);
assert.deepEqual($('lora-0').children.map(x=>x.value),['','custom/nested/style.safetensors','shared/style.safetensors']);assert.equal($('lora-0').disabled,false);
sandbox.availableModels.push({family:'sdxl',target:'animagine',lora_folders:[]});$('generation-model').value='5';vm.runInContext('filterLoras()',context);assert.deepEqual($('lora-0').children.map(x=>x.value),['']);assert($('lora-0').disabled);
