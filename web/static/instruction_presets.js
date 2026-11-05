/** Save just the natural-language instruction, with no generation side effects. */
function initializeInstructionPresets(){
 const select=$('saved-instruction'),field=$('field-instruction'),name=$('instruction-name'),status=$('instruction-save-status');
 let items=[],busy=false;
 const locked=()=>busy||!!generationGate.snapshot.activeBatch||(generationGate.snapshot.localBusy&&generationGate.snapshot.busyKind!=='loading');
 function sync(){const disabled=locked();for(const id of ['saved-instruction','instruction-name','refresh-instructions'])$(id).disabled=disabled;for(const id of ['load-instruction','update-instruction','delete-instruction'])$(id).disabled=disabled||!select.value;$('save-instruction').disabled=disabled||!name.value.trim()||!field.value.trim();$('update-instruction').disabled||=!name.value.trim()||!field.value.trim();}
 function render(rows,chosen=select.value){items=rows;select.replaceChildren(new Option('選択してください',''));for(const item of rows)select.add(new Option(item.name,item.id));select.value=rows.some(x=>x.id===chosen)?chosen:'';sync();}
 async function action(call){if(locked())return;busy=true;sync();try{await call();}catch(error){status.textContent=error.message;}finally{busy=false;sync();}}
 select.addEventListener('change',()=>{name.value=items.find(x=>x.id===select.value)?.name||'';sync();});name.addEventListener('input',sync);field.addEventListener('input',sync);generationGate.subscribe(sync);
 $('refresh-instructions').addEventListener('click',()=>action(async()=>{render((await getJSON('/api/instruction-presets')).items);status.textContent='指示の一覧を更新しました。';}));
 $('load-instruction').addEventListener('click',()=>{
  if(locked())return;const item=items.find(x=>x.id===select.value);if(!item)return;
  if(field.value.trim()&&field.value!==item.instruction&&!window.confirm('入力中の指示を、選択した指示に置き換えますか？'))return;
  field.value=item.instruction;field.dispatchEvent(new Event('input',{bubbles:true}));status.textContent='指示だけを読み込みました。生成は開始していません。';field.focus();
 });
 async function save(update){await action(async()=>{const item=items.find(x=>x.id===select.value);if(update&&!window.confirm('「'+item.name+'」の名前と指示を更新しますか？'))return;const data=await getJSON('/api/instruction-presets'+(update?'/'+encodeURIComponent(select.value):''),{method:update?'PUT':'POST',headers:{'Content-Type':'application/json','X-Requested-With':'LLMPC'},body:JSON.stringify({name:name.value,instruction:field.value})});render(data.items,data.id);status.textContent='指示を保存しました。';});}
 $('save-instruction').addEventListener('click',()=>save(false));$('update-instruction').addEventListener('click',()=>save(true));
 $('delete-instruction').addEventListener('click',()=>action(async()=>{const item=items.find(x=>x.id===select.value);if(!window.confirm('保存した指示「'+item.name+'」を削除しますか？入力中の指示や生成画像は削除しません。'))return;const data=await getJSON('/api/instruction-presets/'+encodeURIComponent(select.value),{method:'DELETE',headers:{'X-Requested-With':'LLMPC'}});render(data.items,'');name.value='';status.textContent='保存した指示を削除しました。入力中の指示は残しています。';}));
 action(async()=>render((await getJSON('/api/instruction-presets')).items));sync();
}
