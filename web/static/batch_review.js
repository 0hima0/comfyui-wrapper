if(batchId){
 $('batch-selection-count').textContent='残す画像：'+batchSelected.size+'枚';
 const progressView=new BatchProgressView($('batch-progress'));
 observeFloatingProgress($('batch-progress'));
 let batchReady=false,lastCompleted=-1,polling=true,finalizing=false,cancelRequested=false;
 async function pollBatch(){
  if(!polling||finalizing)return;
  try{
   const data=await getJSON('/api/batches/'+encodeURIComponent(batchId));
   batchReady=data.state!=='running';
   const title=$('batch-set-title');if(title)title.textContent=data.name?data.name+' — 画像を選別':'この生成セットを選別する';
   if(batchReady)cancelRequested=false;
   progressView.render(data,{cancelRequested});
   $('batch-finalize').disabled=true;
   if(data.completed!==lastCompleted||batchReady){if(galleryBusy){setTimeout(pollBatch,300);return;}await loadGallery(true);lastCompleted=data.completed;}
   $('batch-finalize').disabled=!batchReady||!$('load-more').hidden||$('gallery-status').classList.contains('error');
   if(typeof updateBatchSelection==='function')updateBatchSelection();
   if(batchReady&&!$('gallery-status').classList.contains('error'))polling=false;
  }catch(error){progressView.error('進行状況を取得できませんでした。'+error.message);}
  if(polling)setTimeout(pollBatch,2500);
 }
 $('batch-stop').addEventListener('click',async()=>{
  cancelRequested=true;$('batch-stop').disabled=true;
  if(progressView.data)progressView.render(progressView.data,{cancelRequested});
  try{await getJSON('/api/batches/'+encodeURIComponent(batchId)+'/cancel',{method:'POST',headers:{'X-Requested-With':'LLMPC'}});$('batch-status').textContent='停止処理中です。完成済みの画像は残ります。';}
  catch(error){cancelRequested=false;$('batch-status').textContent=error.message;$('batch-stop').disabled=false;}
 });
 $('batch-finalize').addEventListener('click',()=>{
  if(!batchReady||finalizing||galleryBusy||!$('load-more').hidden)return;
  $('batch-confirm-count').textContent='残す画像：'+batchSelected.size+'枚 ／ 削除する画像：'+(gallerySeen.size-batchSelected.size)+'枚';
  $('batch-confirm-title').textContent=batchSelected.size?'選別を確定しますか？':'すべての画像・設定を破棄しますか？';
  $('batch-confirm-save').classList?.toggle?.('danger',batchSelected.size===0);
  $('batch-confirm-save').textContent=batchSelected.size?'保存 '+batchSelected.size+'枚・削除 '+(gallerySeen.size-batchSelected.size)+'枚で確定':'すべて破棄する';
  $('batch-confirm-dialog').showModal();
 });
 $('batch-confirm-cancel').addEventListener('click',()=>$('batch-confirm-dialog').close());
 $('batch-confirm-dialog').addEventListener('cancel',event=>{if(finalizing)event.preventDefault();});
 $('batch-confirm-save').addEventListener('click',async()=>{
  if(!batchReady||finalizing||galleryBusy||!$('load-more').hidden)return;
  finalizing=true;$('batch-finalize').disabled=true;
  $('batch-confirm-save').disabled=true;$('batch-confirm-cancel').disabled=true;
  try{const data=await getJSON('/api/batches/'+encodeURIComponent(batchId)+'/finalize',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'LLMPC'},body:JSON.stringify({selected:[...batchSelected]})});try{sessionStorage.removeItem('llmpc-batch-selection-'+batchId);}catch{}window.location.assign(data.redirect);}
  catch(error){$('batch-confirm-dialog').close();$('batch-status').textContent=error.message;finalizing=false;$('batch-finalize').disabled=false;$('batch-confirm-save').disabled=false;$('batch-confirm-cancel').disabled=false;}
 });
 pollBatch();
}else{
 getJSON('/api/batches').then(data=>{
  const root=$('pending-batches');root.hidden=!data.items.length;if(!data.items.length)return;
  const title=document.createElement('h2');title.textContent='未確定の生成セット（連続生成レビュー）';root.append(title);
  for(const item of data.items){const link=document.createElement('a');link.className='download secondary batch-folder-shortcut';link.href='/batch/'+encodeURIComponent(item.batch_id);link.textContent='生成セット：'+(item.name||galleryTime(item.created_at))+' ／ '+item.completed+' / '+item.count+'回完了';root.append(link);}
 }).catch(error=>{const root=$('pending-batches');root.hidden=false;root.textContent='連続生成レビュー一覧を取得できませんでした。'+error.message;});
}
