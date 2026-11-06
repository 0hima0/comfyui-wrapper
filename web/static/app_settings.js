let settingsRevision=null,settingsLoaded=false,settingsBusy=false,pendingSettings=null;
const settingsLabels={comfy_url:'ComfyUIの接続先',ollama_url:'Ollamaの接続先',wd_dir:'WD Taggerの保存先（未使用なら空欄）',model:'解析モデル（Ollamaのモデル名）',host:'WebUIの待受アドレス',port:'WebUIのポート',output_dir:'生成結果の保存先',ollama_urls:'複数のOllama接続先（1行に1件・最大4件）',ollama_keep_alive:'Ollamaモデル保持時間（0・秒数・10mなど）',checkpoint_families:'チェックポイントの系列指定',lora_folders:'LoRAフォルダーの系列指定（従来方式）',checkpoint_lora_folders:'生成モデルとLoRAフォルダーの対応'};
settingsLabels.gallery_retention_days='ギャラリー保持日数（0は自動削除しない・再起動後に反映）';
settingsLabels.trusted_hosts='接続を許可するホスト名・IP（1行に1件・ポート不要・再起動後に反映）';
function appSettingsBusy(value){settingsBusy=value;for(const el of $('app-settings-form').elements)el.disabled=value;syncLoraFolderBindings(value);$('app-settings-save').disabled=value;$('app-settings-cancel').disabled=value;}
function settingsMapping(key,values,container){
 const title=document.createElement('h3');title.textContent=settingsLabels[key];container.append(title);
 const table=document.createElement('div');table.dataset.mapping=key;container.append(table);
 function row(name='',family='sdxl'){const line=document.createElement('div');line.className='settings-mapping-row';const input=document.createElement('input');input.value=name;input.placeholder=key==='lora_folders'?'例：sdxl':'チェックポイント名';input.setAttribute('aria-label',settingsLabels[key]+'の名前');const select=document.createElement('select');select.setAttribute('aria-label','モデル系列');for(const label of ['sd15','sdxl','illustrious'])select.add(new Option(label,label));select.value=family;const remove=document.createElement('button');remove.type='button';remove.className='secondary';remove.textContent='削除';remove.addEventListener('click',()=>line.remove());line.append(input,select,remove);table.append(line);}
 for(const [name,family] of Object.entries(values))row(name,family);
 const add=document.createElement('button');add.type='button';add.className='secondary';add.textContent='対応を追加';add.addEventListener('click',()=>row());container.append(add);
}
function renderAppSettings(settings){
 $('app-settings-fields').replaceChildren();$('app-settings-advanced').replaceChildren();
 for(const [key,value] of Object.entries(settings)){
  const container=['comfy_url','ollama_url','wd_dir','model','checkpoint_lora_folders'].includes(key)?$('app-settings-fields'):$('app-settings-advanced');
  if(key==='checkpoint_lora_folders'){renderLoraFolderBindings(value,container);continue;}
  if(['checkpoint_families','lora_folders'].includes(key)){settingsMapping(key,value,container);continue;}
  const label=document.createElement('label');label.className='field';label.textContent=settingsLabels[key]||key;
  const input=document.createElement(['ollama_urls','trusted_hosts'].includes(key)?'textarea':'input');input.name=key;input.value=['ollama_urls','trusted_hosts'].includes(key)?value.join('\n'):(value??'');
  if(key==='port'){input.type='number';input.min='1';input.max='65535';input.step='1';}
  if(key==='gallery_retention_days'){input.type='number';input.min='0';input.max='36500';input.step='1';input.required=true;}
  if(key==='model'){input.type='text';input.maxLength=300;input.required=true;input.placeholder='例：gemma3:4b';}
  label.append(input);container.append(label);
 }
 const note=document.createElement('p');note.className='hint';note.textContent='相対パスは設定ファイルのあるフォルダーが基準です。WD保存先にはmodel.onnxとselected_tags.csvが必要です。解析モデルは画像対応のモデル名を指定し、使用するすべてのOllamaへ先に導入してください。保存後にWrapperを再起動します。';$('app-settings-fields').append(note);
}
function collectAppSettings(){
 const values={};for(const el of $('app-settings-form').elements)if(el.name)values[el.name]=el.value;
 values.port=Number(values.port);values.wd_dir=values.wd_dir.trim()||null;
 values.gallery_retention_days=Number(values.gallery_retention_days);
 values.trusted_hosts=values.trusted_hosts.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
 values.ollama_urls=values.ollama_urls.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
 if(/^-?\d+$/.test(values.ollama_keep_alive))values.ollama_keep_alive=Number(values.ollama_keep_alive);
 for(const table of document.querySelectorAll('[data-mapping]')){const entries=[];for(const row of table.children){const name=row.querySelector('input').value.trim();if(!name)throw Error('系列指定の名前が空欄です。不要な行は削除してください。');if(entries.some(([key])=>key===name))throw Error('系列指定の名前が重複しています。');entries.push([name,row.querySelector('select').value]);}values[table.dataset.mapping]=Object.fromEntries(entries);}
 values.checkpoint_lora_folders=collectLoraFolderBindings();
 return values;
}
async function loadAppSettings(){
 if(settingsBusy)return;appSettingsBusy(true);$('app-settings-status').textContent='読み込み中…';
 try{const data=await getJSON('/api/app-settings',{headers:{'X-Requested-With':'LLMPC'}});renderAppSettings(data.settings);settingsRevision=data.revision;settingsLoaded=true;$('app-settings-overrides').textContent=data.overrides.length?'起動引数で優先されている項目：'+data.overrides.map(key=>settingsLabels[key]||key).join('、')+'。反映するには起動引数も見直してください。':'';$('app-settings-status').textContent='保存済みの設定を表示しています。';}
 catch(error){settingsRevision=null;$('app-settings-status').textContent=error.message;}
 finally{appSettingsBusy(false);}
}
async function settingsRequest(body,method='POST'){return getJSON('/api/app-settings',{method,headers:{'Content-Type':'application/json','X-Requested-With':'LLMPC'},body:JSON.stringify(body)});}
$('app-settings-reload').addEventListener('click',()=>{if(window.confirm('編集中の内容を破棄して読み込み直しますか？'))loadAppSettings();});
$('app-settings-form').addEventListener('submit',async event=>{
 event.preventDefault();if(settingsBusy||!settingsRevision)return;
 try{const settings=collectAppSettings();appSettingsBusy(true);const result=await settingsRequest({settings,revision:settingsRevision});$('app-settings-diff').replaceChildren();for(const change of result.changes){const row=document.createElement('tr');for(const value of [settingsLabels[change.key]||change.key,JSON.stringify(change.before),JSON.stringify(change.after)]){const td=document.createElement('td');td.textContent=value;row.append(td);}$('app-settings-diff').append(row);}
 if(!result.changes.length){$('app-settings-status').textContent='変更はありません。';return;}
 pendingSettings={settings,revision:settingsRevision,confirmation:result.confirmation};$('app-settings-save-status').textContent='';$('app-settings-dialog').showModal();
 }catch(error){$('app-settings-status').textContent=error.message;}finally{appSettingsBusy(false);}
});
$('app-settings-cancel').addEventListener('click',()=>$('app-settings-dialog').close());
$('app-settings-dialog').addEventListener('cancel',event=>{if(settingsBusy)event.preventDefault();});
$('app-settings-save').addEventListener('click',async()=>{
 if(settingsBusy||!pendingSettings)return;appSettingsBusy(true);
 try{const result=await settingsRequest(pendingSettings,'PUT');$('app-settings-dialog').close();pendingSettings=null;settingsRevision=null;settingsLoaded=false;$('app-settings-status').textContent=result.saved?'保存しました。WebUIサービスを再起動してください。'+(result.backup?' バックアップ：'+result.backup:''):'変更はありません。';}
 catch(error){$('app-settings-save-status').textContent=error.message;}finally{appSettingsBusy(false);}
});
$('app-settings-test').addEventListener('click',async()=>{
 if(settingsBusy||!settingsRevision)return;
 try{const settings=collectAppSettings();appSettingsBusy(true);$('app-settings-status').textContent='接続を確認中…';const data=await settingsRequest({settings,action:'connection'});$('app-settings-connections').replaceChildren();for(const row of data.results){const li=document.createElement('li');li.textContent=row.name+'：'+(row.ok?'接続できました':'接続または応答形式を確認できませんでした');$('app-settings-connections').append(li);}$('app-settings-status').textContent='接続テストが完了しました。設定は保存していません。';}
 catch(error){$('app-settings-status').textContent=error.message;}finally{appSettingsBusy(false);}
});
document.addEventListener('system-tab-change',event=>{if(event.detail==='settings'&&!settingsLoaded&&!settingsBusy)loadAppSettings();});
