let managedLoraNames=[];
let managerDirty = false;
let managerSnapshot = '';
let managerRequest = 0;
let managerLoading = false;
let managerDetailRequest = 0;
const managedFields=['managed-trigger','managed-url','managed-note','managed-tags','managed-recommended-prompt'];
function setManagerLoading(loading){
 managerLoading=loading;
 for(const id of managedFields)$(id).disabled=loading;
 $('managed-lora').disabled=loading||loraSamples.busy;
 $('refresh-managed-loras').disabled=loading||loraSamples.busy;
 $('save-managed-lora').disabled=loading||loraSamples.busy||!managedName;
 $('delete-managed-lora').disabled=loading||loraSamples.busy||!loraRegistry[managedName];
 loraSamples.render();
}
function managedFormValue(){return JSON.stringify(['managed-trigger','managed-url','managed-note','managed-tags','managed-recommended-prompt'].map(id=>$(id).value));}
function updateManagerSaveState(){const node=$('manager-save-state');if(!node)return;node.textContent=managerDirty?'未保存の変更があります。「保存」で登録してください。':managedName?(loraRegistry[managedName]?'登録情報は保存済みです。':'未登録です。入力後に「保存」してください。'):'LoRAを選択してください。';node.classList?.toggle('unsaved',managerDirty);}
let managedName = '';
async function readManagedRecord() {
  const name=$('managed-lora').value, previous=managedName;
  const requestId=++managerDetailRequest, listRequest=managerRequest;
  const snapshot=managedFormValue();
  setManagerLoading(true);
  try {
    await loadLoraDetail(name);
    if(requestId!==managerDetailRequest||listRequest!==managerRequest)return;
    if(managedFormValue()!==snapshot){managerDirty=true;updateManagerSaveState();return;}
    populateManagedRecord();
  } catch(error) {
    if(requestId!==managerDetailRequest||listRequest!==managerRequest)return;
    $('managed-lora').value=previous;
    $('manager-status').textContent='詳細を取得できません。入力を保持しています。'+error.message;
  } finally {
    if(requestId===managerDetailRequest&&listRequest===managerRequest)setManagerLoading(false);
  }
}
function populateManagedRecord() {
  managedName = $('managed-lora').value;
  if(typeof refreshManagedRecommendation==='function')refreshManagedRecommendation();
  syncManagedTree();
  loraSamples.load(managedName);
  const row = loraRegistry[managedName] || {};
  $('managed-trigger').value = row.trigger || '';
  $('managed-url').value = row.url || '';
  $('managed-note').value = row.note || '';
  $('managed-recommended-prompt').value = row.recommended_prompt || '';
  $('managed-tags').value = (row.tags||[]).join(', ');
  managerDirty = false;
  managerSnapshot = managedFormValue();
  updateManagerSaveState();
  $('manager-status').textContent = managedName ? (loraRegistry[managedName] ? 'トリガーワード設定：登録済みの内容を表示しています。' : '未登録です。トリガーワードを入力して保存してください。') : 'ComfyUIにLoRAを配置して一覧を更新してください。';
  $('save-managed-lora').disabled = !managedName;
  $('delete-managed-lora').disabled = !loraRegistry[managedName];
}
function mayDiscard() {
  return !managerDirty || window.confirm('保存していない変更を破棄しますか？');
}
async function loadManagedLoras() {
  const requestId=++managerRequest;
  const snapshot=managedFormValue();
  setManagerLoading(true);
  $('manager-status').textContent='一覧を読み込んでいます。入力内容は読み込み完了まで保持しています…';
  try {
    const [records, options, samples] = await Promise.all([
      getJSON('/api/lora-triggers?summary=1'), getJSON('/api/generation-options'),getJSON('/api/lora-samples/names').catch(()=>({names:[],unavailable:true}))
    ]);
    if(requestId!==managerRequest)return;
    if(options.loras_available===false||!Array.isArray(options.loras))throw Error('LoRA一覧の確認に失敗しました。');
    replaceLoraIndex(records.records);
    if(typeof updateLoraNotesState==='function')updateLoraNotesState('ready');
    registryReady = Promise.resolve(true);
    const old = $('managed-lora').value;
    const names = [...new Set(options.loras || [])].sort((a,b)=>a.localeCompare(b));
    $('managed-lora').replaceChildren();
    for (const name of names) {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      $('managed-lora').append(option);
    }
    // Keep a draft even if a programmatic input arrived while controls were locked.
    const edited=managedFormValue()!==snapshot;
    if(edited&&old&&!names.includes(old)){const option=document.createElement('option');option.value=old;option.textContent=old;$('managed-lora').append(option);}
    if (names.includes(old)||edited) $('managed-lora').value = old;
    managedLoraNames=names;refreshManagedTagFilter();
    loraSamples.apiAvailable=!samples.unavailable;
    $('managed-lora-hint').textContent = [...options.warnings,...(samples.unavailable?['サンプル画像APIを利用できません。ZIP全体の上書きとWebUI本体の再起動、接続先を確認してください。']:[]),...(!$('managed-sample-files')?['画面テンプレートが古いため画像追加欄がありません。templatesも更新してWebUIを再起動してください。']:[])].join(' ');
    if(!edited)await readManagedRecord();
    else{managerDirty=true;updateManagerSaveState();}
  } catch (error) {
    if(requestId!==managerRequest)return;
    $('manager-status').textContent = '一覧の確認に失敗しました。入力を保持しています。'+error.message;
  } finally {
    if(requestId===managerRequest)setManagerLoading(false);
  }
}
function showManager() {
  document.body?.classList.remove('generation-page');
  $('page-title').textContent='LoRA管理';$('page-description').textContent='LoRAのトリガーワード・配布元・サンプル画像を管理します。';
  document.title='ComfyUI Wrapper | LoRA管理';
  document.dispatchEvent(new CustomEvent('sidebar-page',{detail:'loras'}));
  $('workspace').hidden = true;
  $('lora-manager').hidden = false;
  window.scrollTo?.(0,0);
  if(!managerDirty)loadManagedLoras();
}
async function saveManagedLora(remove) {
  const name = managedName;
  if (!name) return;
  if (remove && !window.confirm('このLoRAの登録情報を削除しますか？')) return;
  const previous = loraRegistry[name]?.trigger || '';
  loraSamples.busy=true;if($('managed-sample-files'))$('managed-sample-files').disabled=true;
  $('save-managed-lora').disabled = true;
  $('delete-managed-lora').disabled = true;
  $('managed-lora').disabled = true;
  $('close-lora-manager').disabled = true;
  $('refresh-managed-loras').disabled = true;
  for (const id of ['managed-trigger','managed-url','managed-note','managed-tags','managed-recommended-prompt']) $(id).disabled = true;
  try {
    const data = await getJSON('/api/lora-triggers?summary=1', {
      method: remove ? 'DELETE' : 'PUT',
      headers: {'Content-Type':'application/json','X-Requested-With':'LLMPC'},
      body: JSON.stringify({name, trigger: $('managed-trigger').value, url: $('managed-url').value, note: $('managed-note').value,recommended_prompt:$('managed-recommended-prompt').value,tags:$('managed-tags').value.split(/[,、\n]/).map(x=>x.trim()).filter(Boolean)})
    });
    loraIndex = data.records;
    cacheLoraRecord(name,data.record===undefined?(data.records[name]||null):data.record);
    if(typeof updateLoraNotesState==='function')updateLoraNotesState('ready');
    registryReady = Promise.resolve(true);
    for (let i = 0; i < 3; i++) {
      const input = $('lora-' + i + '-trigger');
      if ($('lora-' + i).value === name && input.value === previous)
        input.value = loraRegistry[name]?.trigger || '';
    }
    populateManagedRecord();refreshManagedTagFilter();
    $('manager-status').textContent = remove ? '登録情報を削除しました。' : '保存しました。LoRA選択時に自動入力されます。';
  } catch (error) {
    $('manager-status').textContent = error.message;
  } finally {
    loraSamples.busy=false;loraSamples.render();
    $('save-managed-lora').disabled = !managedName;
    $('delete-managed-lora').disabled = !loraRegistry[managedName];
    $('managed-lora').disabled = false;
    $('close-lora-manager').disabled = false;
    $('refresh-managed-loras').disabled = false;
    for (const id of ['managed-trigger','managed-url','managed-note','managed-tags','managed-recommended-prompt']) $(id).disabled = false;
  }
}

function initializeLoraManager(){
 initializeLoraSamples();
 registryReady=refreshRegistry();
$('open-lora-manager').addEventListener('click', showManager);
$('close-lora-manager').addEventListener('click', () => {
  if (!mayDiscard()) return;
  ++managerRequest;
  ++managerDetailRequest;
  setManagerLoading(false);
  managerDirty = false;
  document.body?.classList.add('generation-page');
  $('page-title').textContent='画像生成';$('page-description').textContent='指示や参考画像からプロンプトを組み立て、ComfyUIで画像を生成します。';
  document.title='ComfyUI Wrapper | 画像生成';
  document.dispatchEvent(new CustomEvent('sidebar-page',{detail:'generate'}));
  $('workspace').hidden = false;
  $('lora-manager').hidden = true;
  $('open-lora-manager').focus();
});
$('managed-lora').addEventListener('change', () => {
  if (!mayDiscard()) { $('managed-lora').value = managedName; return; }
  readManagedRecord();
});
for (const id of ['managed-trigger','managed-url','managed-note','managed-tags','managed-recommended-prompt'])
  $(id).addEventListener('input', () => { managerDirty = managedFormValue() !== managerSnapshot; updateManagerSaveState(); });
$('refresh-managed-loras').addEventListener('click', () => { if (mayDiscard()) loadManagedLoras(); });
$('lora-manager-form').addEventListener('submit', event => { event.preventDefault(); saveManagedLora(false); });
$('delete-managed-lora').addEventListener('click', () => saveManagedLora(true));
window.addEventListener('beforeunload', event => { if (managerDirty) { event.preventDefault(); event.returnValue = ''; } });
document.addEventListener('click',event=>{
 const link=event.target.closest?.('a[href]');
 if(!link||event.defaultPrevented||event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey||link.target||link.hasAttribute('download')||!managerDirty)return;
 const url=new URL(link.href,window.location.href);
 if(url.href===window.location.href||url.protocol==='javascript:'||link.getAttribute('href')?.startsWith('#'))return;
 if(!mayDiscard()){event.preventDefault();event.stopImmediatePropagation();return;}
 managerDirty=false;updateManagerSaveState();
},true);


$('refresh-loras').addEventListener('click',()=>{registryReady=refreshRegistry();});

$('managed-tag-filter')?.addEventListener('change',refreshManagedTagFilter);
$('clear-managed-tag-filter')?.addEventListener('click',()=>{$('managed-tag-filter').value='';refreshManagedTagFilter();});

 if(managerInitiallyOpen)showManager();
}
