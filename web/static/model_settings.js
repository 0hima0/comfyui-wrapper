let modelRequest=0;let generationOptionsRequest=0;let availableModels=[];let loraCatalog=[];let generationWarnings=[];
const presetFallback={sd15:{steps:28,cfg:7,sampler_name:'euler_ancestral',scheduler:'normal',clip_skip:0},anima:{steps:30,cfg:4,sampler_name:'er_sde',scheduler:'simple',clip_skip:0},animagine31:{steps:28,cfg:7,sampler_name:'euler_ancestral',scheduler:'normal',clip_skip:0},animagine4:{steps:28,cfg:5,sampler_name:'euler_ancestral',scheduler:'normal',clip_skip:0},wai17:{steps:28,cfg:5,sampler_name:'euler_ancestral',scheduler:'normal',clip_skip:0},sdxl:{steps:28,cfg:7,sampler_name:'euler_ancestral',scheduler:'normal',clip_skip:0}};
function selectValue(select,value){if(![...select.options].some(o=>o.value===String(value))){const option=document.createElement('option');option.value=String(value);option.textContent=String(value);select.append(option);}select.value=String(value);}
function applyProfile(){const entry=availableModels[Number($('generation-model').value)];const profile=$('profile').value==='auto'?(entry?.profile||($('target').value==='anima'?'anima':'sdxl')):$('profile').value;const preset=presetFallback[profile]||presetFallback.sdxl;const form=$('form');form.elements.namedItem('steps').value=preset.steps;form.elements.namedItem('cfg').value=preset.cfg;form.elements.namedItem('denoise').value=1;selectValue($('sampler'),preset.sampler_name);selectValue($('scheduler'),preset.scheduler);$('clip-skip').value=preset.clip_skip;$('quality-tags').checked=profile==='animagine4';const anima=$('target').value==='anima';$('lora-unavailable').hidden=!anima;for(const field of $('lora-rows').querySelectorAll('input,select'))field.disabled=anima;$('clip-skip').disabled=anima;$('restored-generation').value='{}';filterLoras();}
function appendSettingHelp(field,control,text){
 const title=field.firstChild.textContent;field.firstChild.remove();
 const heading=document.createElement('div');heading.className='field-heading';
 const label=document.createElement('label');label.htmlFor=control.id;label.textContent=title;
 const id='help-'+control.id;control.setAttribute('aria-describedby',id);
 heading.append(label,SettingTooltips.create(id,title,text));field.prepend(heading);
}
function createLoraRows(){for(let index=0;index<3;index++){const box=document.createElement('div');box.className='lora-row';box.setAttribute('role','group');box.setAttribute('aria-label','LoRA '+(index+1));const label=document.createElement('div');label.className='field';label.textContent='LoRA '+(index+1);const select=document.createElement('select');select.id='lora-'+index;const none=document.createElement('option');none.value='';none.textContent='使用しない';select.append(none);const search=document.createElement('input');search.type='search';search.id='lora-'+index+'-search';search.placeholder='フォルダー名・LoRA名で検索';search.setAttribute('aria-label','LoRA '+(index+1)+'を検索');search.addEventListener('input',filterLoras);const searchInfo=document.createElement('span');searchInfo.id='lora-'+index+'-search-status';searchInfo.className='lora-search-status';searchInfo.setAttribute('role','status');const clearSearch=document.createElement('button');clearSearch.type='button';clearSearch.id='lora-'+index+'-clear-search';clearSearch.className='secondary';clearSearch.textContent='検索を解除';clearSearch.hidden=true;clearSearch.addEventListener('click',()=>{search.value='';filterLoras();search.focus();});label.append(search,clearSearch,searchInfo,select);appendSettingHelp(label,select,"人物・衣装・画風などの特徴を追加する補助モデルです。モデルごとに登録したLoRAフォルダーから選べます。未登録のモデルは従来の系列判定を使います。不要なら「使用しない」にします。");box.append(label);for(const [key,title,value] of [['model','MODEL強度','0.7'],['clip','CLIP強度','0.7'],['trigger','トリガーワード（任意）','']]){const field=document.createElement('div');field.className='field';field.textContent=title;const input=document.createElement('input');input.id='lora-'+index+'-'+key;input.value=value;input.type=key==='trigger'?'text':'number';if(key==='trigger')input.maxLength=2000;else{input.min='-2';input.max='2';input.step='0.05';}field.append(input);appendSettingHelp(field,input,({model:"見た目にLoRAを反映する強さです。0は無効、通常は配布元の推奨値を使います。高すぎると特徴が強く出たり形が崩れたりします。",clip:"Promptの解釈にLoRAを反映する強さです。通常は配布元の推奨値を使います。MODEL強度とは別に調整できます。",trigger:"LoRAを呼び出すための言葉です。登録済みなら自動入力されます。ここでの編集は今回だけ有効で、人物用は対応する人物のPromptへ入ります。"})[key]);box.append(field);}const scopeLabel=document.createElement('div');scopeLabel.className='field';scopeLabel.textContent='適用先（人物維持モード）';const scope=document.createElement('select');scope.id='lora-'+index+'-scope';for(const [value,title] of [['auto','自動（人物用LoRA順 → 画像追加順）'],['global','全体（画風など）']]){const option=document.createElement('option');option.value=value;option.textContent=title;scope.append(option);}scopeLabel.append(scope);appendSettingHelp(scopeLabel,scope,"人物維持モードでLoRAを適用する対象です。「自動」は人物用LoRA順に画像へ割り当て、「画像」を選ぶと対象を固定します。画風用は「全体」を選びます。人物維持オフでは全体に適用します。");box.append(scopeLabel);$('lora-rows').append(box);select.addEventListener('change',()=>{fillLoraTrigger(index);filterLoras();if(typeof refreshLoraRecommendation==='function')refreshLoraRecommendation(index);});}}
function loraValues(){if($('target').value==='anima')return [];const rows=[];for(let i=0;i<3;i++){const name=$('lora-'+i).value;if(name)rows.push({name,strength_model:Number($('lora-'+i+'-model').value),strength_clip:Number($('lora-'+i+'-clip').value),trigger:$('lora-'+i+'-trigger').value,scope:$('lora-'+i+'-scope').value||'auto'});}return rows;}
function compatibleLoraNames(){
 const entry=availableModels[Number($('generation-model').value)];
 if(entry?.target==='anima')return [];
 if(Array.isArray(entry?.lora_folders))return loraCatalog.filter(row=>entry.lora_folders.some(folder=>{const parent=row.name.replace(/\\/g,'/').split('/').slice(0,-1).join('/').toLocaleLowerCase(),path=folder.toLocaleLowerCase();return path==='.'?!parent:parent===path||parent.startsWith(path+'/');})).map(row=>row.name);
 return loraCatalog.filter(row=>['sd15','sdxl','illustrious'].includes(entry?.family)&&row.family===entry.family).map(row=>row.name);
}
function filterLoras(){
 if(typeof refreshPersonState==='function')refreshPersonState();
 const entry=availableModels[Number($('generation-model').value)];
 const names=compatibleLoraNames(),allowed=new Set(names);let removed=false;
 const explicit=Array.isArray(entry?.lora_folders);
 const supported=entry?.target!=='anima'&&(explicit||['sd15','sdxl','illustrious'].includes(entry?.family));
 const sources={config:'設定ファイルで指定',folder:'フォルダー名から判定',filename:'ファイル名から判定',loader:'読み込み方式から判定',unknown:'未判定'};
 $('model-family').textContent='モデルの種類：'+(entry?.family_label||'未判定')+' · '+(sources[entry?.family_source]||'未判定');
 for(let i=0;i<3;i++){
  const select=$('lora-'+i),old=select.value;select.replaceChildren();
  const query=($('lora-'+i+'-search').value||'').trim().toLocaleLowerCase();
  const matches=names.filter(name=>name.toLocaleLowerCase().includes(query));
  const shown=[...(old&&allowed.has(old)?[old]:[]),...matches.filter(name=>name!==old)];
  const info=$('lora-'+i+'-search-status');if(info)info.textContent='選択中：'+(allowed.has(old)?old.replace(/\\/g,'/').split('/').pop():'使用しない')+' ／ 検索結果 '+matches.length+'件'+(query&&allowed.has(old)&&!matches.includes(old)?'（選択中のLoRAは検索対象外ですが維持しています）':'');
  const clear=$('lora-'+i+'-clear-search');if(clear){clear.hidden=!query;clear.disabled=!supported; }
  for(const name of ['',...shown]){const option=document.createElement('option');option.value=name;option.title=name;option.textContent=name?(name===old?'選択中：'+name.replace(/\\/g,'/').split('/').pop():name):'使用しない';select.append(option);}
  if(old&&allowed.has(old))select.value=old;
  else if(old){$('lora-'+i+'-trigger').value='';removed=true;}
  select.title=allowed.has(old)?old:'';
  select.disabled=!supported||!names.length;
  $('lora-'+i+'-search').disabled=!supported||!names.length;
  for(const key of ['model','clip','trigger','scope'])$('lora-'+i+'-'+key).disabled=!supported||!names.length;
 }
 $('lora-unavailable').hidden=supported;
 $('lora-unavailable').textContent=entry?.family==='anima'?'Animaは今回のLoRA機能の対象外です。':'モデルの種類が未判定です。アプリ設定で生成モデルとLoRAフォルダーの対応を登録してください。';
 if(typeof renderLoraNotes==='function')renderLoraNotes();
 if(typeof refreshLoraRecommendation==='function')for(let i=0;i<3;i++)refreshLoraRecommendation(i);
 $('lora-hint').textContent=[supported?(explicit?'モデル別フォルダー対応：'+(entry.lora_folders.join('、')||'使用を許可するフォルダーなし')+' ／ '+names.length+'件。':(entry.family_label||entry.family)+'用LoRA：'+names.length+'件。対応フォルダーのLoRAのみ選べます。'):'',removed?'対応外、または一覧にないLoRAを解除しました。':'',...generationWarnings].filter(Boolean).join(' ');
}
function restoreLoras(rows){
 const allowed=new Set(compatibleLoraNames());let skipped=false;
 for(let i=0;i<3;i++){const row=rows[i];if(row&&allowed.has(row.name)){
  selectValue($('lora-'+i),row.name);$('lora-'+i+'-model').value=row.strength_model;$('lora-'+i+'-clip').value=row.strength_clip;$('lora-'+i+'-trigger').value=row.trigger||'';const scope=$('lora-'+i+'-scope');scope.dataset??={};scope.dataset.pendingScope=row.scope||'auto';scope.value=row.scope||'auto';
 }else{$('lora-'+i).value='';$('lora-'+i+'-trigger').value='';$('lora-'+i+'-scope').value='auto';if(row)skipped=true;}}
 filterLoras();
 if(skipped)$('lora-hint').textContent+=' 履歴内の未対応・未判定・一覧にないLoRAは復元しませんでした。';
}
async function loadGenerationOptions(){const requestId=++generationOptionsRequest;try{
 const data=await getJSON('/api/generation-options');if(requestId!==generationOptionsRequest)return;
 if(data.loras_available===false||!Array.isArray(data.lora_options))throw Error('LoRA一覧を取得できませんでした。');
 loraCatalog=data.lora_options;generationWarnings=data.warnings||[];
 filterLoras();
 for(const [id,values] of [['sampler',data.samplers],['scheduler',data.schedulers]]){const select=$(id);const old=select.value;if(values.length){select.replaceChildren();for(const value of values)selectValue(select,value);selectValue(select,old);}}
 }catch(error){if(requestId!==generationOptionsRequest)return;generationWarnings=['一覧の確認に失敗しました。直前の一覧と入力を保持しています。'+error.message];filterLoras();}}
function chooseModel(){const entry=availableModels[Number($('generation-model').value)];$('target').value=entry?entry.target:'';$('checkpoint').value=entry?entry.name:'';applyProfile();if(typeof refreshModelRecommendation==='function')refreshModelRecommendation();}
async function loadModels(){const requestId=++modelRequest;const old=$('checkpoint').value;const oldTarget=$('target').value;$('generation-model').disabled=true;$('refresh-models').disabled=true;$('model-hint').textContent='モデル一覧を取得しています…';try{const data=await getJSON('/api/models');if(requestId!==modelRequest)return;availableModels=data.models;$('generation-model').replaceChildren();availableModels.forEach((entry,index)=>{const option=document.createElement('option');option.value=String(index);option.textContent=entry.label;$('generation-model').append(option);});const index=availableModels.findIndex(m=>m.name===old&&m.target===oldTarget);$('generation-model').value=String(index<0?0:index);if(index>=0){const entry=availableModels[index];$('target').value=entry.target;$('checkpoint').value=entry.name;filterLoras();}else{chooseModel();}$('model-hint').textContent=data.warning||(availableModels.length?'ComfyUIに登録されているモデルを取得しました。':'ComfyUIにモデルがありません。');}catch(error){availableModels=[];$('generation-model').replaceChildren();$('model-hint').textContent=error.message;}finally{if(requestId===modelRequest){$('generation-model').disabled=false;$('refresh-models').disabled=false;}}}


function updateLoraScopes(entries){
 for(let i=0;i<3;i++){
  const select=$('lora-'+i+'-scope');if(!select)continue;
  const old=select.dataset?.pendingScope||select.value||'auto';
  if(select.dataset)delete select.dataset.pendingScope;
  select.replaceChildren();
  const choices=[['auto','自動（人物用LoRA順 → 画像追加順）'],['global','全体（画風など）'],...entries.map(ref=>['image:'+ref.id,'画像'+ref.id+'：'+ref.filename])];
  if(!choices.some(([value])=>value===old))choices.push([old,'以前の適用先（画像を再選択してください）']);
  for(const [value,title] of choices){const option=document.createElement('option');option.value=value;option.textContent=title;select.append(option);}
  select.value=old;
 }
}

function initializeModelSettings(){
 createLoraRows();
$('profile').addEventListener('change',applyProfile);
$('refresh-loras').addEventListener('click',loadGenerationOptions);
$('generation-model').addEventListener('change',()=>{$('profile').value='auto';chooseModel();$('restored-generation').value='{}';$('restored-note').textContent='生成モデルを変更したため、復元したStepsなどは既定値に戻ります。';});$('refresh-models').addEventListener('click',loadModels);
}
