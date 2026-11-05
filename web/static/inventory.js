let installedItems=[];
function renderInventory(){
 const query=$('inventory-search').value.trim().toLocaleLowerCase(),kind=$('inventory-kind').value;
 const rows=installedItems.filter(row=>(!kind||row.kind===kind)&&row.name.toLocaleLowerCase().includes(query));
 $('inventory-body').replaceChildren();
 for(const row of rows){const tr=document.createElement('tr');for(const value of [row.kind,row.family_label,row.name]){const td=document.createElement('td');td.textContent=value;tr.append(td);}$('inventory-body').append(tr);}
 $('inventory-status').textContent=rows.length+'件を表示（取得済み '+installedItems.length+'件）';
}
async function refreshInventory(){
 $('refresh-inventory').disabled=true;$('inventory-status').textContent='ComfyUIから一覧を取得しています…';
 try{const data=await getJSON('/api/inventory');installedItems=data.items;renderInventory();$('inventory-warning').textContent=data.warnings.join(' ');}
 catch(error){installedItems=[];renderInventory();$('inventory-warning').textContent=error.message;}
 finally{$('refresh-inventory').disabled=false;}
}
$('refresh-inventory').addEventListener('click',refreshInventory);
$('inventory-search').addEventListener('input',renderInventory);
$('inventory-kind').addEventListener('change',renderInventory);
$('check-comfy-update').addEventListener('click',async()=>{
 const button=$('check-comfy-update');button.disabled=true;$('comfy-update-status').textContent='確認中…';
 try{const data=await getJSON('/api/comfyui-update');const labels={update_available:'新しい安定版があります。',up_to_date:'最新の安定版と同じバージョンです。',ahead:'稼働版は最新の安定版より新しいバージョンです。',unknown:'更新の有無を判定できません。'};
 $('comfy-update-status').textContent=(labels[data.state]||labels.unknown)+' 稼働版：'+(data.current||'不明')+' ／ 最新安定版：'+(data.latest||'不明')+' ／ 確認日時：'+new Date(data.checked_at).toLocaleString('ja-JP')+' '+data.warnings.join(' ');
 }catch(error){$('comfy-update-status').textContent='確認できませんでした。'+error.message;}finally{button.disabled=false;}
});
let inventoryStarted=false;document.addEventListener('system-tab-change',event=>{if(event.detail==='inventory'&&!inventoryStarted){inventoryStarted=true;refreshInventory();}});