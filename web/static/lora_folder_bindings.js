/** Exact checkpoint name -> arbitrary relative LoRA folder paths. */
function renderLoraFolderBindings(values,container){
 const section=document.createElement('section');section.className='lora-bindings-panel';
 const title=document.createElement('h3');title.textContent='生成モデルとLoRAフォルダーの対応';
 const hint=document.createElement('p');hint.className='hint';hint.textContent='モデル名と、ComfyUIのmodels/loras内の相対フォルダーを対応付けます。同じモデルに複数行を追加できます。下位フォルダーも含みます。未登録のモデルは従来の系列判定を使います。保存後はWrapperを再起動してください。フォルダー対応は新しいモデル方式への対応を追加するものではなく、AnimaのLoRAは対象外です。';
 const rows=document.createElement('div');rows.id='checkpoint-lora-bindings';
 const models=document.createElement('datalist');models.id='binding-model-options';const folders=document.createElement('datalist');folders.id='binding-folder-options';
 function row(model='',folder='',deny=false){
  const line=document.createElement('div');line.className='lora-binding-row';line.dataset.loraBinding='';
  function field(title,value,list,kind){const label=document.createElement('label');label.className='field';label.textContent=title;const input=document.createElement('input');input.type='text';input.value=value;input.maxLength=1000;input.setAttribute('list',list);input.dataset.bindingField=kind;input.setAttribute('aria-label',title);label.append(input);line.append(label);return input;}
  field('生成モデル名（ComfyUIの相対パスを含む）',model,models.id,'model');
  const directory=field('LoRAフォルダー（例：my-model/characters）',folder,folders.id,'folder');
  const label=document.createElement('label');label.className='binding-deny';const check=document.createElement('input');check.type='checkbox';check.checked=deny;check.dataset.bindingField='deny';check.addEventListener('change',()=>directory.disabled=check.checked);label.append(check,document.createTextNode('LoRAを許可しない'));line.append(label);directory.disabled=deny;
  const remove=document.createElement('button');remove.type='button';remove.className='secondary';remove.textContent='対応を削除';remove.addEventListener('click',()=>line.remove());line.append(remove);rows.append(line);
 }
 for(const [model,paths] of Object.entries(values)){if(paths.length)for(const path of paths)row(model,path);else row(model,'',true);}
 const add=document.createElement('button');add.type='button';add.className='secondary';add.id='add-lora-binding';add.textContent='モデルとフォルダーの対応を追加';add.addEventListener('click',()=>row());
 const status=document.createElement('p');status.className='hint';status.setAttribute('role','status');status.textContent='現在のComfyUIから候補を取得しています…';
 section.append(title,hint,rows,add,models,folders,status);container.append(section);
 Promise.allSettled([getJSON('/api/models'),getJSON('/api/generation-options')]).then(results=>{
  if(results[0].status==='fulfilled')for(const name of new Set(results[0].value.models.filter(x=>x.target!=='anima').map(x=>x.name)))models.append(new Option(name,name));
  const paths=new Set(['.']);if(results[1].status==='fulfilled')for(const name of results[1].value.loras||[]){const parts=name.replace(/\\/g,'/').split('/');for(let i=1;i<parts.length;i++)paths.add(parts.slice(0,i).join('/'));}for(const path of [...paths].sort())folders.append(new Option(path==='.'?'直下のLoRAのみ':path,path));
  status.textContent=results.every(r=>r.status==='fulfilled')?'入力欄で候補を選べます。候補は現在の接続先が認識するモデル・LoRAから作成します。空のフォルダーや未導入のモデルは手入力できます。':'候補を取得できない項目があります。ComfyUIの接続を確認するか、名前を手入力してください。';
 });
}
function collectLoraFolderBindings(){
 const result=Object.create(null),denied=new Set();
 for(const row of document.querySelectorAll('[data-lora-binding]')){
  const model=row.querySelector('[data-binding-field=model]').value.trim(),folder=row.querySelector('[data-binding-field=folder]').value.trim(),deny=row.querySelector('[data-binding-field=deny]').checked;
  if(!model||(!deny&&!folder))throw Error('モデル名とLoRAフォルダーを入力してください。不要な行は削除してください。');
  if(deny){if(Object.hasOwn(result,model))throw Error('同じモデルに「許可しない」とフォルダー指定を併用できません。');result[model]=[];denied.add(model);}
  else{if(denied.has(model))throw Error('同じモデルの許可設定が重複しています。');result[model]??=[];if(result[model].includes(folder))throw Error('同じモデルとフォルダーの対応が重複しています。');result[model].push(folder);}
 }
 return result;
}
function syncLoraFolderBindings(busy){for(const row of document.querySelectorAll('[data-lora-binding]'))row.querySelector('[data-binding-field=folder]').disabled=busy||row.querySelector('[data-binding-field=deny]').checked;}
