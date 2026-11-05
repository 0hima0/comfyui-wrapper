/* Shared named settings; uploaded reference files stay in the current workspace. */
function initializePresets(){
 let items=[],busy=false,deleting=null;
 const select=$('settings-preset');
 const message=text=>$('preset-status').textContent=text;
 function sync(){
  const running=$('submit').disabled;
  for(const id of ['apply-preset','create-preset','update-preset','delete-preset','refresh-presets','settings-preset','preset-name'])$(id).disabled=busy||running;
  for(const id of ['apply-preset','update-preset','delete-preset'])$(id).disabled||=!select.value;
 }
 new MutationObserver(sync).observe($('submit'),{attributes:true,attributeFilter:['disabled']});
 function render(rows,chosen=select.value){
  items=rows;select.replaceChildren(new Option('選択してください',''));
  for(const row of items)select.append(new Option(row.name,row.id));
  select.value=chosen;sync();
 }
 async function action(call){
  if(busy||$('submit').disabled)return;
  busy=true;sync();
  try{await call();}catch(error){message(error.message);if($('delete-preset-dialog').open)$('delete-preset-error').textContent=error.message;}finally{busy=false;sync();}
 }
 async function refresh(){const data=await getJSON('/api/presets');render(data.items);}
 function snapshot(){
  const fields=readGenerationFields();
  return {name:$('preset-name').value.trim(),fields,loras:loraValues()};
 }
 async function save(update){
  const data=await getJSON('/api/presets'+(update?'/'+encodeURIComponent(select.value):''),{
   method:update?'PUT':'POST',headers:{'Content-Type':'application/json','X-Requested-With':'LLMPC'},body:JSON.stringify(snapshot())});
  render(data.items,data.id);message('プリセットを保存しました。');
 }
 async function apply(){
  const row=items.find(x=>x.id===select.value);if(!row)return;
  const fields=row.fields;
  const index=availableModels.findIndex(x=>x.name===fields.checkpoint&&x.target===fields.target);
  if(index<0)throw Error('プリセットの生成モデルが現在の一覧にありません。モデル一覧を更新してください。');
  // Resolve model before restoring numeric settings, because chooseModel applies defaults.
  $('generation-model').value=String(index);$('profile').value=fields.profile||'auto';chooseModel();
  const warnings=[];
  for(const [name,value] of Object.entries(fields)){
   const el=$('form').elements.namedItem(name);if(!el||['target','checkpoint'].includes(name))continue;
   if(el.type==='checkbox')el.checked=value;else if(el.tagName==='SELECT')selectValue(el,value);else el.value=value;
  }
  if($('use-wd').disabled&&$('use-wd').checked){$('use-wd').checked=false;if($('form').elements.namedItem('rating').value==='auto')$('form').elements.namedItem('rating').value='none';warnings.push('WDが利用できないためオフにしました');}
  $('use-wd').dispatchEvent(new Event('change'));toggleAdditionalPrompts();
  updateLoraScopes(referenceEditor.entries);restoreLoras(row.loras);updateLoraScopes(referenceEditor.entries);
  if(row.loras.some(x=>!compatibleLoraNames().includes(x.name)))warnings.push('利用できないLoRAを解除しました');
  $('restored-generation').value='{}';$('batch-mode').checked=false;syncBatchOptions();
  $('preset-name').value=row.name;
  markWorkspaceEdited();refreshPersonState();await saveWorkspace();
  message('プリセットを読み込みました。参考画像とLoRAの適用先を確認してください。'+warnings.join('。'));
 }
 select.addEventListener('change',()=>{$('preset-name').value=items.find(x=>x.id===select.value)?.name||'';sync();});
 $('apply-preset').addEventListener('click',()=>action(apply));
 $('create-preset').addEventListener('click',()=>action(()=>save(false)));
 $('update-preset').addEventListener('click',()=>action(()=>save(true)));
 $('refresh-presets').addEventListener('click',()=>action(refresh));
 $('delete-preset').addEventListener('click',()=>{if(busy||$('submit').disabled||!select.value)return;deleting=select.value;$('delete-preset-error').textContent='';$('delete-preset-description').textContent=items.find(x=>x.id===deleting)?.name||'';$('delete-preset-dialog').showModal();});
 $('cancel-preset-delete').addEventListener('click',()=>$('delete-preset-dialog').close());
 $('confirm-preset-delete').addEventListener('click',()=>action(async()=>{
  $('confirm-preset-delete').disabled=true;
  try{const data=await getJSON('/api/presets/'+encodeURIComponent(deleting),{method:'DELETE',headers:{'X-Requested-With':'LLMPC'}});render(data.items,'');$('delete-preset-dialog').close();message('プリセットを削除しました。');}
  finally{$('confirm-preset-delete').disabled=false;}
 }));
 refresh().catch(error=>message('プリセットを読み込めません。一覧を更新してください。'+error.message));sync();
}
