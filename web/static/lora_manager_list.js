/** Folder tree and tag filters; consumes the lightweight index only. */
function syncManagedTree(){
 const title=$('managed-selected-name');if(title)title.textContent=managedName||'LoRAを選択してください。';
 const tree=$('managed-lora-tree');if(!tree)return;
 for(const button of tree.querySelectorAll('button[data-lora-name]')){
  const selected=button.dataset.loraName===managedName;
  button.setAttribute('aria-current',selected?'true':'false');
 }
}
function refreshManagedTagFilter(){
 const filter=$('managed-tag-filter');if(!filter)return;
 const selected=filter.value;
 const tags=new Map();for(const name of managedLoraNames)for(const tag of loraIndex[name]?.tags||[])if(!tags.has(tag.toLocaleLowerCase()))tags.set(tag.toLocaleLowerCase(),tag);
 if(selected.startsWith('tag:')&&!tags.has(selected.slice(4).toLocaleLowerCase()))tags.set(selected.slice(4).toLocaleLowerCase(),selected.slice(4));
 function option(text,value){const node=document.createElement('option');node.textContent=text;node.value=value;return node;}
 filter.replaceChildren(option('すべて',''),option('タグなし','untagged:'));
 for(const tag of [...tags.values()].sort((a,b)=>a.localeCompare(b)))filter.append(option(tag,'tag:'+tag.toLocaleLowerCase()));
 filter.value=selected;
 const matches=managedLoraNames.filter(name=>{const values=loraIndex[name]?.tags||[];return !selected||(selected==='untagged:'?!values.length:values.some(t=>t.toLocaleLowerCase()===selected.slice(4).toLocaleLowerCase()));});
 renderManagedTree(matches);
 $('managed-filter-status').textContent=matches.length+' / '+managedLoraNames.length+'件'+(managedName&&!matches.includes(managedName)?'。右側で編集中のLoRAは絞り込み対象外です。':'');
 $('clear-managed-tag-filter').disabled=!selected;
}
function renderManagedTree(names){
 const tree=$('managed-lora-tree');if(!tree)return;
 tree.replaceChildren();
 if(!names.length){const message=document.createElement('p');message.className='hint';message.textContent=managedLoraNames.length?'このタグに一致するLoRAはありません。絞り込みを解除してください。':'ComfyUIで利用できるLoRAがありません。接続と配置先を確認して一覧を更新してください。';tree.append(message);return;}
 const root={folders:new Map(),files:[]};
 for(const name of names){const parts=name.replace(/\\/g,'/').split('/').filter(Boolean);let node=root;for(const folder of parts.slice(0,-1)){if(!node.folders.has(folder))node.folders.set(folder,{folders:new Map(),files:[]});node=node.folders.get(folder);}node.files.push({name,label:parts.at(-1)||name});}
 function append(node,parent){
  for(const [label,child] of node.folders){const folder=document.createElement('details');folder.open=true;const summary=document.createElement('summary');summary.textContent=label;folder.append(summary);const contents=document.createElement('div');contents.className='managed-folder-content';append(child,contents);folder.append(contents);parent.append(folder);}
  for(const file of node.files){const button=document.createElement('button');button.type='button';button.className='managed-tree-file';button.dataset.loraName=file.name;button.textContent=file.label;button.title=file.name;button.addEventListener('click',()=>{if($('managed-lora').disabled||loraSamples.busy||!mayDiscard())return;$('managed-lora').value=file.name;readManagedRecord();});parent.append(button);}
 }
 append(root,tree);syncManagedTree();
}
