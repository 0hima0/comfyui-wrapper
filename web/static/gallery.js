let galleryOffset=0;
let galleryBusy=false;
let batchHasMore=false;
function updateBatchSelection(){
 if(!batchId)return;
 const keep=batchSelected.size,total=gallerySeen.size;
 $('batch-finalize').classList.toggle('danger',keep===0);
 $('batch-selection-count').textContent='保存：'+keep+'枚 ／ 削除：'+Math.max(0,total-keep)+'枚'+(batchHasMore?'（読み込み中）':'');
 $('batch-finalize').textContent=keep?'保存 '+keep+'枚・削除 '+Math.max(0,total-keep)+'枚で確定':'すべて破棄（'+total+'枚）';
}

let favoriteBusy=false;
let deleteTarget=null;
const batchId=$('gallery-main').dataset.batchId;
const batchSelected=new Set();
if(batchId){try{for(const key of JSON.parse(sessionStorage.getItem('llmpc-batch-selection-'+batchId)||'[]'))batchSelected.add(key);}catch{}}
const gallerySeen=new Set();
const galleryComparison=new GalleryComparison();
const galleryBulkDelete=new GalleryBulkDelete();
$('favorites-only').checked=!batchId&&new URLSearchParams(location.search).get('favorites')==='1';
function galleryControls(){
 const busy=galleryBusy||favoriteBusy;
 for(const id of ['refresh-gallery','load-more','favorites-only'])$(id).disabled=busy;
 for(const input of document.querySelectorAll('#gallery-search input,#gallery-search button'))input.disabled=busy;
 for(const button of document.querySelectorAll('.gallery-favorite'))button.disabled=busy;
 for(const button of document.querySelectorAll('.gallery-delete'))button.disabled=busy||button.dataset.protected==='true';
 galleryBulkDelete.sync(busy);
}
function favoriteLabel(button,item){
 button.textContent=item.favorite?'★':'☆';
 button.title=item.favorite?'お気に入りを解除':'お気に入りに追加';
 button.setAttribute('aria-pressed',String(item.favorite));
 button.setAttribute('aria-label',(item.comfy_filename||item.filename)+(item.favorite?'をお気に入りから解除':'をお気に入りに追加'));
}
async function toggleFavorite(item,button){
 if(galleryBusy||favoriteBusy)return;
 favoriteBusy=true;galleryControls();
 let reload=false;
 try{
  const data=await getJSON(item.favorite_url,{method:'PUT',headers:{'Content-Type':'application/json','X-Requested-With':'LLMPC'},body:JSON.stringify({favorite:!item.favorite})});
  item.favorite=data.favorite;favoriteLabel(button,item);
  if(typeof refreshStorageUsage==='function')refreshStorageUsage(true);
  const cards=[...document.querySelectorAll('.gallery-card')].filter(card=>card.dataset.jobId===item.job_id);
  const protectedJob=cards.some(card=>card.querySelector('.gallery-favorite').getAttribute('aria-pressed')==='true');
  for(const card of cards){const remove=card.querySelector('.gallery-delete');remove.dataset.protected=String(protectedJob);remove.title=protectedJob?'お気に入りを含む実行は削除できません。':'この実行の画像と設定を削除';}
  galleryBulkDelete.protect(item.job_id,protectedJob);
  reload=$('favorites-only').checked&&!item.favorite;
  $('gallery-status').classList.remove('error');
  $('gallery-status').textContent=item.favorite?'お気に入りに追加しました。':'お気に入りから解除しました。';
 }catch(error){$('gallery-status').classList.add('error');$('gallery-status').textContent=error.message;}
 finally{favoriteBusy=false;galleryControls();}
 if(reload)await loadGallery(true);
}
function galleryTime(value){return value?new Date(value).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo'}):'日時不明';}
function galleryCard(item){
 const card=document.createElement('article');card.className='gallery-card';card.dataset.jobId=item.job_id;
 const preview=document.createElement('button');preview.type='button';preview.className='gallery-preview';preview.setAttribute('aria-label',(item.comfy_filename||item.filename)+'を拡大表示');
 const image=document.createElement('img');image.src=item.thumbnail_url||item.image_url;image.alt=item.summary||'生成画像';image.loading='lazy';image.decoding='async';
 preview.append(image);preview.addEventListener('click',()=>{ $('gallery-viewer-image').src=item.image_url;$('gallery-viewer-name').textContent=item.comfy_filename||item.filename;$('gallery-viewer').showModal(); });
 const fallback=document.createElement('span');fallback.className='hint';fallback.hidden=true;fallback.textContent='画像を表示できません。一覧を更新してください。';
 image.addEventListener('error',()=>{if(item.thumbnail_url&&!image.dataset.originalFallback){image.dataset.originalFallback='1';image.src=item.image_url;return;}image.hidden=true;fallback.hidden=false;});preview.append(fallback);
 const body=document.createElement('div');body.className='gallery-card-body';galleryComparison.register(item,card,body);
 if(batchId){const label=document.createElement('label');label.className='gallery-keep';const keep=document.createElement('input');keep.type='checkbox';keep.checked=batchSelected.has(item.job_id+'/'+item.filename);keep.setAttribute('aria-label',(item.comfy_filename||item.filename)+'を残す');keep.addEventListener('change',()=>{const key=item.job_id+'/'+item.filename;if(keep.checked)batchSelected.add(key);else batchSelected.delete(key);try{sessionStorage.setItem('llmpc-batch-selection-'+batchId,JSON.stringify([...batchSelected]));}catch{}updateBatchSelection();});label.append(keep,document.createTextNode(' 残す'));body.append(label);}
 else{const favorite=document.createElement('button');favorite.type='button';favorite.className='secondary gallery-favorite';favoriteLabel(favorite,item);favorite.addEventListener('click',()=>toggleFavorite(item,favorite));card.append(favorite);}
 if(!batchId)galleryBulkDelete.register(item,body);
 const title=document.createElement('h2');title.textContent=item.comfy_filename||item.filename;
 const model=document.createElement('p');model.className='hint';model.textContent=item.checkpoint||'モデル未記録';
 const meta=document.createElement('p');meta.className='hint';meta.textContent=[item.width&&item.height?item.width+' × '+item.height:'',item.seed!==undefined?'シード：'+item.seed:''].filter(Boolean).join(' ／ ');
 if(batchId){const values=document.createElement('p');values.className='hint';values.textContent='第'+item.batch_index+'回'+(item.use_wd?' ／ WDしきい値：'+item.threshold:'')+(item.loras||[]).map((l,i)=>' ／ LoRA '+(i+1)+' MODEL '+l.strength_model+'・CLIP '+l.strength_clip).join('');body.append(values);}
 const actions=document.createElement('div');actions.className='downloads';
 if(!batchId)addAnnotationEditor(item,body,actions);
 const settings=document.createElement('button');settings.type='button';settings.className='secondary gallery-settings';settings.textContent='詳細';settings.setAttribute('aria-label',(item.comfy_filename||item.filename)+'の詳細を表示');settings.addEventListener('click',()=>galleryComparison.open([item]));actions.append(settings);
 for(const [url,label,primary] of [...(batchId?[]:[[item.restore_url,'この設定を使う',true]]),[item.download_url,'画像を保存',false]]){const a=document.createElement('a');a.href=url;a.className=primary?'download':'download secondary';a.textContent=label;actions.append(a);}
 const remove=document.createElement('button');remove.type='button';remove.className='secondary gallery-delete';remove.textContent='この実行の'+item.image_count+'枚を削除';remove.dataset.protected=String(item.protected);remove.disabled=item.protected;
 remove.title=item.protected?'お気に入りを含む実行は削除できません。':'この実行の画像と設定を削除';
 remove.addEventListener('click',()=>{deleteTarget=item;for(const c of document.querySelectorAll('.gallery-card'))c.classList.toggle('delete-preview',c.dataset.jobId===item.job_id);$('delete-gallery-description').textContent=(item.comfy_filename||item.filename)+'を生成した実行の画像'+item.image_count+'枚と、設定・Prompt・ワークフロー・保存済み参考画像を削除します。元に戻せません。';$('delete-gallery-error').textContent='';$('delete-gallery-dialog').showModal();});if(!batchId)actions.append(remove);
 body.append(title,model,meta,actions);card.append(preview,body);return card;
}
async function loadGallery(reset=false){
 if(galleryBusy||favoriteBusy)return;galleryBusy=true;galleryControls();
 if(reset){galleryOffset=0;gallerySeen.clear();galleryComparison.controls.clear();galleryBulkDelete.reset();$('gallery-grid').replaceChildren();}
 $('gallery-status').classList.remove('error');$('gallery-status').textContent='画像を読み込んでいます…';
 try{
  const data=await getJSON('/api/gallery?offset='+galleryOffset+'&favorites='+($('favorites-only').checked?'1':'0')+(batchId?'&batch_id='+encodeURIComponent(batchId):'&'+galleryFilters()));
  if(batchId)data.items.sort((a,b)=>(a.batch_index||0)-(b.batch_index||0));
  for(const item of data.items){const key=item.job_id+'/'+item.filename;if(gallerySeen.has(key))continue;gallerySeen.add(key);const grid=$('gallery-grid');if(batchId&&item.batch_cell){const cell=item.batch_cell;grid.classList.add('matrix-gallery');grid.style.setProperty('--matrix-columns',cell.columns);let group=grid.querySelector('[data-matrix-cell="'+item.job_id+'"]');if(!group){group=document.createElement('section');group.dataset.matrixCell=item.job_id;group.style.order=cell.row*cell.columns+cell.column;group.style.gridColumn=cell.column+1;group.style.gridRow=cell.row+1;const heading=document.createElement('h2');heading.className='matrix-cell-heading';heading.textContent=cell.values.map(v=>(v.lora!==null&&v.lora!==undefined?'LoRA '+(v.lora+1)+' ':'')+({strength_model:'MODEL',strength_clip:'CLIP',threshold:'WDしきい値',cfg:'CFG',steps:'Steps'}[v.field]||v.field)+' = '+v.value).join(' ／ ');group.append(heading);grid.append(group);}group.append(galleryCard(item));}else grid.append(galleryCard(item));}
  galleryOffset=data.next_offset;$('load-more').hidden=!data.has_more;
  if(batchId){batchHasMore=data.has_more;if(!batchHasMore){for(const key of batchSelected)if(!gallerySeen.has(key))batchSelected.delete(key);}updateBatchSelection();}
  $('gallery-status').textContent=gallerySeen.size?gallerySeen.size+'枚を表示しています。'+(data.has_more?'「さらに表示」で以前の画像を読み込めます。':''):data.has_more?'この範囲の画像ファイルは見つかりません。「さらに表示」で以前の実行を確認できます。':$('favorites-only').checked?'お気に入りの画像はありません。各画像右上の星マークで追加できます。':(!batchId&&galleryFilters()?'検索条件に一致する画像はありません。条件を変更するかクリアしてください。':'保存済みの生成画像はありません。');
 }catch(error){$('gallery-status').classList.add('error');$('gallery-status').textContent=error.message+' 「一覧を更新」または「さらに表示」で再試行してください。';}
 finally{galleryBusy=false;galleryControls();if(batchId&&batchHasMore&&!$('gallery-status').classList.contains('error'))setTimeout(()=>loadGallery(),0);}
}
$('favorites-only').addEventListener('change',()=>{const url=new URL(location.href);if($('favorites-only').checked)url.searchParams.set('favorites','1');else url.searchParams.delete('favorites');history.replaceState(null,'',url);loadGallery(true);});
$('refresh-gallery').addEventListener('click',()=>{if(typeof refreshStorageUsage==='function')refreshStorageUsage(true);loadGallery(true);});
$('load-more').addEventListener('click',()=>loadGallery());
$('cancel-gallery-delete').addEventListener('click',()=>$('delete-gallery-dialog').close());
$('confirm-gallery-delete').addEventListener('click',async()=>{
 if(!deleteTarget||galleryBusy||favoriteBusy)return;
 favoriteBusy=true;galleryControls();$('confirm-gallery-delete').disabled=true;$('cancel-gallery-delete').disabled=true;
 let deleted=false;
 try{
  await getJSON(deleteTarget.delete_url,{method:'DELETE',headers:{'X-Requested-With':'LLMPC'}});
  for(const [key,item] of galleryComparison.selected)if(item.job_id===deleteTarget.job_id)galleryComparison.selected.delete(key);
  galleryComparison.sync();$('delete-gallery-dialog').close();deleted=true;
 }catch(error){$('delete-gallery-error').textContent=error.message;}
 finally{favoriteBusy=false;galleryControls();$('confirm-gallery-delete').disabled=false;$('cancel-gallery-delete').disabled=false;}
 if(deleted){if(typeof refreshStorageUsage==='function')refreshStorageUsage(true);await loadGallery(true);}
});
$('delete-gallery-dialog').addEventListener('cancel',event=>{if(favoriteBusy)event.preventDefault();});
$('close-gallery-viewer').addEventListener('click',()=>$('gallery-viewer').close());
$('gallery-viewer').addEventListener('click',event=>{const rect=$('gallery-viewer').getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)$('gallery-viewer').close();});
loadGallery(true);

$('delete-gallery-dialog').addEventListener('close',()=>{for(const card of document.querySelectorAll('.delete-preview'))card.classList.remove('delete-preview');});