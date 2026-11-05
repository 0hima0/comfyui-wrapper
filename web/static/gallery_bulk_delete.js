/** Deletion selection is separate from comparison; shared outputs belong to one execution. */
class GalleryBulkDelete {
 constructor(){
  this.selected=new Map();this.controls=new Map();this.targets=[];this.busy=false;
  if(batchId)return;
  $('bulk-select-visible').addEventListener('click',()=>{
   for(const {item} of this.controls.values())if(!item.protected&&this.selected.size<500)this.selected.set(item.job_id,item);
   this.sync();
  });
  $('bulk-clear-selection').addEventListener('click',()=>{this.selected.clear();this.sync();});
  $('open-bulk-delete').addEventListener('click',()=>this.open());
  $('cancel-bulk-delete').addEventListener('click',()=>$('bulk-delete-dialog').close());
  $('confirm-bulk-delete').addEventListener('click',()=>this.remove());
  $('bulk-delete-dialog').addEventListener('cancel',event=>{if(favoriteBusy)event.preventDefault();});
 }
 register(item,body){
  const label=document.createElement('label');label.className='gallery-delete-select';
  const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.setAttribute('aria-label',(item.comfy_filename||item.filename)+'を削除対象に選択');
  label.append(checkbox,document.createTextNode(' この実行の'+item.image_count+'枚を削除'));body.append(label);
  this.controls.set(item.job_id+'/'+item.filename,{item,checkbox});
  checkbox.addEventListener('change',()=>{
   if(checkbox.checked&&!item.protected&&this.selected.size<500)this.selected.set(item.job_id,item);
   else this.selected.delete(item.job_id);
   this.sync();
  });
  this.sync();
 }
 reset(){this.selected.clear();this.controls.clear();this.sync();}
 protect(job,protectedJob){
  for(const {item} of this.controls.values())if(item.job_id===job)item.protected=protectedJob;
  if(protectedJob)this.selected.delete(job);
  this.sync();
 }
 sync(busy=this.busy){
  this.busy=busy;if(batchId)return;
  for(const {item,checkbox} of this.controls.values()){
   checkbox.checked=this.selected.has(item.job_id);
   checkbox.disabled=busy||item.protected||(!checkbox.checked&&this.selected.size>=500);
   checkbox.closest?.('.gallery-card')?.classList.toggle('delete-chosen',checkbox.checked);
   checkbox.title=item.protected?'お気に入りを含む実行は削除できません。':'同じ実行の画像・設定をまとめて削除します。';
  }
  $('bulk-delete-count').closest?.('.bulk-delete-bar')?.classList.toggle('has-selection',this.selected.size>0);
  const images=[...this.selected.values()].reduce((sum,item)=>sum+item.image_count,0);
  $('bulk-delete-count').textContent='削除対象：'+this.selected.size+'実行 ／ 画像'+images+'枚';
  $('open-bulk-delete').disabled=busy||!this.selected.size;
  $('bulk-clear-selection').disabled=busy||!this.selected.size;
  $('bulk-select-visible').disabled=busy||![...this.controls.values()].some(({item})=>!item.protected)||this.selected.size>=500;
 }
 open(){
  if(this.busy||!this.selected.size)return;
  this.targets=[...this.selected.values()];
  $('bulk-delete-description').textContent=this.targets.length+'実行・画像'+this.targets.reduce((sum,item)=>sum+item.image_count,0)+'枚と、対応する設定・Prompt・ワークフロー・保存済み参考画像を削除します。元に戻せません。';
  $('bulk-delete-names').replaceChildren();
  for(const item of this.targets){const row=document.createElement('li');row.textContent=(item.comfy_filename||item.filename)+' の実行（画像'+item.image_count+'枚）';$('bulk-delete-names').append(row);}
  $('bulk-delete-error').textContent='';$('bulk-delete-dialog').showModal();
 }
 async remove(){
  if(this.busy||galleryBusy||favoriteBusy||!this.targets.length)return;
  favoriteBusy=true;galleryControls();$('confirm-bulk-delete').disabled=true;$('cancel-bulk-delete').disabled=true;
  let result=null;
  try{
   result=await getJSON('/api/gallery/bulk-delete',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'LLMPC'},body:JSON.stringify({job_ids:this.targets.map(item=>item.job_id)})});
   if(!result.deleted.length){$('bulk-delete-error').textContent=result.skipped.map(item=>item.error).join(' ');return;}
   const deleted=new Set(result.deleted);
   for(const [key,item] of galleryComparison.selected)if(deleted.has(item.job_id))galleryComparison.selected.delete(key);
   galleryComparison.sync();$('bulk-delete-dialog').close();
  }catch(error){$('bulk-delete-error').textContent=error.message+' 一覧を更新して削除状況を確認してください。';}
  finally{favoriteBusy=false;galleryControls();$('confirm-bulk-delete').disabled=false;$('cancel-bulk-delete').disabled=false;}
  if(result?.deleted.length){
   if(typeof refreshStorageUsage==='function')refreshStorageUsage(true);
   await loadGallery(true);
   const skipped=result.skipped.length;
   $('gallery-status').classList.toggle('error',skipped>0);
   $('gallery-status').textContent=result.deleted.length+'実行を削除しました。'+(skipped?skipped+'実行は削除しませんでした。'+[...new Set(result.skipped.map(item=>item.error))].join(' '):'');
  }
 }
}
