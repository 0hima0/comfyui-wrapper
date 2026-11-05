/* Load independently so a capacity scan never delays gallery thumbnails. */
var refreshStorageUsage = (() => {
 const byId=id=>document.getElementById(id);
 const button=byId('refresh-storage');
 if(!button)return async()=>{};
 let pending=null;
 const number=value=>Number(value).toLocaleString('ja-JP');
 function size(value){
  if(!Number.isFinite(value)||value<0)return '取得できません';
  const units=['B','KB','MB','GB','TB','PB'];let index=0;
  while(value>=1000&&index<units.length-1){value/=1000;index++;}
  return value.toLocaleString('ja-JP',{maximumFractionDigits:index?1:0})+' '+units[index];
 }
 async function refresh(force=false){
  if(pending)return pending;
  button.disabled=true;
  byId('storage-status').textContent='容量を確認しています…';
  pending=(async()=>{
   try{
    const response=await fetch('/api/storage-usage'+(force?'?refresh=1':''),{cache:'no-store'});
    if(!response.ok)throw Error('保存容量を取得できません。しばらくしてから「容量を更新」を押してください。');
    const data=await response.json();
    byId('storage-total').textContent=size(data.total.bytes);
    byId('storage-total-count').textContent=number(data.total.files)+'ファイル';
    for(const [key,item] of Object.entries(data.categories)){
     byId('storage-'+key).textContent=size(item.bytes);
     byId('storage-'+key+'-count').textContent=(key==='other'?'':number(item.executions)+'実行 ／ ')+number(item.files)+'ファイル';
    }
    byId('storage-free').textContent=data.disk?size(data.disk.free):'取得できません';
    byId('storage-free-count').textContent=data.disk?'ディスク全体 '+size(data.disk.total):'';
    byId('storage-directory').textContent='保存先：'+data.output_directory;
    byId('storage-disk-used').hidden=!data.disk;
    if(data.disk)byId('storage-disk-used').value=data.disk.used_percent;
    byId('storage-disk-label').textContent=data.disk?'保存先ディスク全体の使用率：'+data.disk.used_percent+'%':'';
    const date=new Date(data.scanned_at).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo'});
    byId('storage-status').textContent='最終確認：'+date+'（日本時間）。通常は最大'+data.refresh_after_seconds+'秒前の集計を表示します。'+
     (data.partial?' 一部の容量を読み取れませんでした。表示は集計できた範囲の値です。':'')+
     (data.skipped_links?' リンク'+number(data.skipped_links)+'件を除外しました。':'');
   }catch(error){byId('storage-status').textContent=error.message;}
   finally{button.disabled=false;pending=null;}
  })();
  return pending;
 }
 button.addEventListener('click',()=>refresh(true));
 window.addEventListener('pageshow',event=>{if(event.persisted)refresh();});
 let storageStarted=false;document.addEventListener('system-tab-change',event=>{if(event.detail==='storage'&&!storageStarted){storageStarted=true;refresh();}});
 if(!document.getElementById('panel-storage'))refresh();return refresh;
})();
