/* Poll only running reviews; reuse gallery thumbnails rather than original images. */
class BatchListUpdater{
 constructor(cards,request=getJSON){this.cards=cards;this.request=request;this.timer=null;this.stopped=true;this.epoch=0;}
 async update(card,epoch){
  try{
   const data=await this.request('/api/batches/'+encodeURIComponent(card.dataset.batchId));
   if(this.stopped||epoch!==this.epoch)return;
   const labels={running:'連続生成中',review:'選別待ち',cancelled:'停止済み',interrupted:'中断・選別待ち',error:'エラー・選別待ち'};
   card.querySelector('.batch-state').textContent=(labels[data.state]||'終了')+' ／ '+data.completed+' / '+data.count+'回完了';
   card.querySelector('[data-batch-message]').textContent=data.message||'';
   if(data.checkpoint)card.querySelector('.batch-model').textContent=data.checkpoint;
   if(data.completed>0&&(card.dataset.completed!==String(data.completed)||!card.querySelector('.batch-preview img'))){
    const gallery=await this.request('/api/gallery?batch_id='+encodeURIComponent(card.dataset.batchId));
    if(this.stopped||epoch!==this.epoch)return;
    const items=(gallery.items||[]).slice(0,3),item=items[0];
    if(item){
     const preview=card.querySelector('.batch-preview');
     const link=document.createElement('a');link.className='batch-preview';link.href='/batch/'+encodeURIComponent(card.dataset.batchId);link.setAttribute('aria-label','生成セットを開く');
     for(let index=0;index<3;index++){
      const current=items[index];
      if(current){const image=document.createElement('img');image.src=current.thumbnail_url;image.alt='セット内の生成画像 '+(index+1);image.loading='lazy';image.decoding='async';link.append(image);}
      else{const placeholder=document.createElement('span');placeholder.className='batch-preview-placeholder';placeholder.textContent='画像';placeholder.setAttribute('aria-hidden','true');link.append(placeholder);}
     }
     preview.replaceWith(link);
     if(item.checkpoint)card.querySelector('.batch-model').textContent=item.checkpoint;
    }
   }
   card.dataset.completed=String(data.completed);card.dataset.state=data.state;
  }catch(error){if(!this.stopped&&epoch===this.epoch)card.querySelector('[data-batch-message]').textContent='更新できませんでした。自動で再確認します。';}
 }
 start(){
  if(!this.stopped)return;this.stopped=false;const epoch=++this.epoch;
  const poll=async()=>{
   if(this.stopped||epoch!==this.epoch)return;
   const active=this.cards.filter(card=>card.dataset.state==='running');
   await Promise.all(active.map(card=>this.update(card,epoch)));
   if(!this.stopped&&epoch===this.epoch&&this.cards.some(card=>card.dataset.state==='running'))this.timer=setTimeout(poll,3000);
  };poll();
 }
 stop(){this.stopped=true;this.epoch++;clearTimeout(this.timer);this.timer=null;}
}
const batchListUpdater=new BatchListUpdater([...document.querySelectorAll('[data-batch-id]')]);
document.addEventListener('visibilitychange',()=>{if(document.hidden)batchListUpdater.stop();else batchListUpdater.start();});
window.addEventListener('pagehide',()=>batchListUpdater.stop());
window.addEventListener('pageshow',()=>{if(!document.hidden)batchListUpdater.start();});
if(!document.hidden)batchListUpdater.start();

for(const form of document.querySelectorAll('.batch-name-form'))form.addEventListener('submit',async event=>{
 event.preventDefault();const card=form.closest('[data-batch-id]'),button=form.querySelector('button'),message=form.querySelector('[data-name-status]');button.disabled=true;
 try{const data=await getJSON('/api/batches/'+encodeURIComponent(card.dataset.batchId)+'/name',{method:'PUT',headers:{'Content-Type':'application/json','X-Requested-With':'LLMPC'},body:JSON.stringify({name:form.elements.name.value})});form.elements.name.value=data.name;card.querySelector('[data-batch-name]').textContent=data.name||'生成セット';message.textContent='名前を保存しました。';}
 catch(error){message.textContent='保存できませんでした：'+error.message;}finally{button.disabled=false;}
});