/** Per-LoRA sample images are saved independently from trigger-word edits. */
class LoraSamples {
 constructor(){
  this.name='';this.request=0;this.busy=false;this.loading=false;this.apiAvailable=true;this.items=[];this.pending=[];this.message='';this.failed=false;this.retryable=false;
  $('managed-sample-files').addEventListener('change',()=>this.upload([...$('managed-sample-files').files]));
  $('retry-sample-upload')?.addEventListener('click',()=>this.upload(this.pending.map(row=>row.file)));
 }
 notify(message,error=false){this.message=message;this.failed=error;$('sample-status').textContent=message;$('sample-status').classList?.toggle('error',error);}
 clearPending(){for(const row of this.pending)URL.revokeObjectURL(row.url);this.pending=[];}
 async load(name){
  if(name!==this.name){this.clearPending();$('managed-sample-files').value='';this.message='';this.failed=false;}
  this.name=name;const version=++this.request;this.loading=Boolean(name);this.items=[];this.render();
  if(!name){this.notify('LoRAを選択してください。');return;}
  if(!this.apiAvailable){this.loading=false;this.render();this.notify('サンプル画像APIを利用できません。WebUI本体を更新して再起動してください。',true);return;}
  this.notify('サンプル画像を読み込んでいます…');
  try{const data=await getJSON('/api/lora-samples?name='+encodeURIComponent(name));if(version!==this.request)return;
   if(!Array.isArray(data.items))throw Error('画像一覧の応答が不正です。');
   this.items=data.items;this.loading=false;this.message='';this.render();
  }catch(error){if(version===this.request){this.loading=false;this.render();this.notify(error.message,true);}}
 }
 render(){
  const managerLoadingNow=typeof managerLoading!=='undefined'&&managerLoading;
  $('managed-samples').replaceChildren();$('managed-sample-files').disabled=managerLoadingNow||this.busy||this.loading||!this.apiAvailable||!this.name||this.items.length>=6;
  const pendingArea=$('managed-sample-pending');if(pendingArea){pendingArea.replaceChildren();pendingArea.hidden=!this.pending.length;
   for(const row of this.pending){const card=document.createElement('article');card.className='lora-sample-card pending-sample';
    const image=document.createElement('img');image.src=row.url;image.alt='選択した画像：'+row.file.name;image.className='pending-sample-image';
    const caption=document.createElement('p');caption.className='hint';caption.textContent=row.file.name+'（'+(row.file.size/1024/1024).toFixed(2)+' MB）';
    const badge=document.createElement('strong');badge.textContent=this.busy?'保存中…':'未保存';card.append(image,caption,badge);pendingArea.append(card);
   }
  }
  const retry=$('retry-sample-upload');if(retry){retry.hidden=!this.failed||!this.pending.length||!this.retryable;retry.disabled=this.busy||this.loading||!this.apiAvailable;}
  this.notify(this.message||(this.items.length?this.items.length+' / 6枚が保存済みです（画像は自動保存）。':'サンプル画像は未登録です。'),this.failed);
  for(const item of this.items){
   const card=document.createElement('article');card.className='lora-sample-card';
   const preview=document.createElement('button');preview.type='button';preview.className='lora-sample-preview';preview.setAttribute('aria-label',item.filename+'を拡大表示');
   const image=document.createElement('img');image.src=item.thumbnail_url;image.alt=item.filename;image.loading='lazy';image.decoding='async';preview.append(image);
   image.addEventListener('error',()=>{if(!image.dataset.originalFallback){image.dataset.originalFallback='1';image.src=item.image_url;}else this.notify('画像は保存されていますが、表示できません。一覧を更新してください。',true);});
   preview.addEventListener('click',()=>openImageViewer(item.image_url,item.filename));
   const caption=document.createElement('p');caption.className='hint';caption.textContent=item.filename+'（'+item.width+' × '+item.height+'）';
   const remove=document.createElement('button');remove.type='button';remove.className='secondary';remove.textContent='サンプルを削除';remove.setAttribute('aria-label',item.filename+'のサンプルを削除');remove.disabled=this.busy||managerLoadingNow;remove.addEventListener('click',()=>this.remove(item));
   card.append(preview,caption,remove);$('managed-samples').append(card);
  }
 }
 setBusy(busy){this.busy=busy;const loading=typeof managerLoading!=='undefined'&&managerLoading;for(const id of ['managed-lora','refresh-managed-loras'])$(id).disabled=busy||loading;$('close-lora-manager').disabled=busy;$('save-managed-lora').disabled=busy||loading||!this.name;$('delete-managed-lora').disabled=busy||loading||!loraRegistry[this.name];this.render();}
 async upload(files){
  if(!files?.length)return;
  if(this.busy||this.loading||(typeof managerLoading!=='undefined'&&managerLoading)||!this.name||!this.apiAvailable){this.notify('LoRAの選択と画像一覧の読み込みが完了してから選択してください。',true);return;}
  this.clearPending();this.pending=files.map(file=>({file,url:URL.createObjectURL(file)}));this.message='';this.failed=false;this.retryable=false;this.render();
  let problem='';
  if(files.length+this.items.length>6)problem='サンプル画像はLoRAごとに最大6枚です。登録済みの画像を削除するか、選択する枚数を減らしてください。';
  else if(files.some(file=>file.size>5*1024*1024))problem='5MBを超える画像があります：'+files.filter(file=>file.size>5*1024*1024).map(file=>file.name).join('、')+'。1枚5MB以内にしてください。';
  else if(files.reduce((sum,file)=>sum+file.size,0)>24*1024*1024)problem='選択した画像の合計を24MB以内にしてください。';
  if(problem){this.notify(problem,true);this.render();return;}
  const name=this.name;this.message='サンプル画像を保存しています…';this.setBusy(true);
  try{
   const form=new FormData();form.set('name',name);for(const file of files)form.append('images',file,file.name);
   const data=await getJSON('/api/lora-samples',{method:'POST',headers:{'X-Requested-With':'LLMPC'},body:form});
   if(!Array.isArray(data.items))throw Error('保存結果を読み取れませんでした。一覧を更新して保存状態を確認してください。');
   if(name===this.name){this.items=data.items;this.clearPending();$('managed-sample-files').value='';}
   this.message=files.length+'枚を保存しました（登録済み '+this.items.length+' / 6枚）。';this.failed=false;
  }catch(error){this.message='保存できませんでした：'+error.message;this.failed=true;this.retryable=true;}
  finally{this.setBusy(false);}
 }
 async remove(item){
  if(this.busy||(typeof managerLoading!=='undefined'&&managerLoading)||!window.confirm('このサンプル画像を削除しますか？'))return;
  this.message='サンプル画像を削除しています…';this.failed=false;this.setBusy(true);
  try{const data=await getJSON('/api/lora-samples/'+encodeURIComponent(item.id),{method:'DELETE',headers:{'X-Requested-With':'LLMPC'}});this.items=data.items;this.message='サンプル画像を削除しました。';}
  catch(error){this.message=error.message;this.failed=true;}
  finally{this.setBusy(false);}
 }
}

let loraSamples;
function initializeLoraSamples(){
 loraSamples=$('managed-sample-files')?new LoraSamples():{busy:false,load(){},render(){}};
}
