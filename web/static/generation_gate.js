/** Keep submission disabled across navigation while a server-side batch owns generation. */
class GenerationGate {
 constructor(button,message,link,batchView=null){
  this.showingBatch=false;this.listeners=new Set();this.batchView=batchView;this.batchRecord=null;this.batchCancelRequested=false;this.busyKind='loading';this.actionLabel='解析して生成';
  batchView?.root.querySelector('[data-batch-stop]').addEventListener('click',()=>this.cancelBatch());
  Object.assign(this,{button,message,link,localBusy:true,checking:true,error:false,activeBatch:null,pending:null,epoch:0,timer:null,stopped:true,cycle:0});
  this.progressView=batchView?new BatchProgressView(batchView.root):null;
  this.sync();
 }
 get snapshot(){return {localBusy:this.localBusy,busyKind:this.busyKind,activeBatch:this.activeBatch,showBatch:this.showingBatch,batchTerminal:!!this.batchRecord?.terminal,canSubmit:!this.localBusy&&!this.checking&&!this.error&&!this.activeBatch};}
 subscribe(listener){this.listeners.add(listener);return ()=>this.listeners.delete(listener);}
 notify(){for(const listener of this.listeners)listener(this.snapshot);}
 sync(){
  const disabled=this.localBusy||this.checking||this.error||!!this.activeBatch;
  if(this.button.disabled!==disabled)this.button.disabled=disabled;
  const busyLabels={loading:'設定読み込み中…',preparing:'実行前チェック中…',submitting:'送信中…',running:'生成中…'};
  const label=this.activeBatch?'連続生成中':this.error?'実行状態を確認できません':this.localBusy?(busyLabels[this.busyKind]||'処理中…'):this.checking?'実行状態を確認中…':this.actionLabel;
  if(this.button.textContent!==label)this.button.textContent=label;
  this.message.textContent=this.error?'実行状態を確認できません。接続を確認してください。自動で再確認します。':this.activeBatch?'連続生成中です。完了または停止後に実行できます。':'';
  this.link.hidden=!this.activeBatch;
  if(this.activeBatch)this.link.href='/batch/'+encodeURIComponent(this.activeBatch);
  if(this.batchView&&this.activeBatch){this.showingBatch=true;this.batchView.root.hidden=false;}
  this.notify();
 }
 async refreshBatch(epoch){
  const id=this.activeBatch||this.batchRecord?.id;
  if(!id)return;
  if(!this.activeBatch&&this.batchRecord?.terminal)return;
  try{
   const data=await getJSON('/api/batches/'+encodeURIComponent(id));
   if(epoch!==this.epoch||this.stopped&&this.cycle>0)return;
   const terminal=data.state!=='running';
   this.batchRecord={id,terminal};this.showingBatch=true;
   this.progressView.render(data,{id,cancelRequested:this.batchCancelRequested});
   if(terminal)this.batchCancelRequested=false;
   this.notify();
  }catch(error){
   if(epoch===this.epoch)this.progressView.error('連続生成の進捗を取得できません。自動で再確認します。');
  }
 }
 async cancelBatch(){
  const id=this.activeBatch;if(!id||this.batchCancelRequested)return;
  this.batchCancelRequested=true;
  const stop=this.batchView.root.querySelector('[data-batch-stop]');stop.disabled=true;stop.textContent='停止処理中…';
  try{await getJSON('/api/batches/'+encodeURIComponent(id)+'/cancel',{method:'POST',headers:{'X-Requested-With':'LLMPC'}});await this.refreshBatch(this.epoch);}
  catch(error){this.batchCancelRequested=false;stop.disabled=false;stop.textContent='連続生成を停止';this.batchView.root.querySelector('[data-batch-detail]').textContent='停止要求を送信できませんでした。再試行してください。';}
 }
 setMode(execute,batch,hasImages){const label=!execute?'Prompt・ワークフローを作成':batch?'連続生成を開始':hasImages?'画像を解析して生成':'指示から生成';if(this.actionLabel!==label){this.actionLabel=label;this.sync();}}
 setLocalBusy(value,kind='loading'){this.busyKind=kind;this.localBusy=value;if(value&&!this.activeBatch&&this.batchView){this.batchView.root.hidden=true;this.showingBatch=false;this.batchRecord=null;}this.sync();}
 markBatch(id){this.batchCancelRequested=false;this.epoch++;this.activeBatch=id;this.checking=false;this.error=false;this.sync();}
 async refresh(){
  if(this.pending)return this.pending;
  const epoch=this.epoch;
  this.pending=(async()=>{
   try{
    const data=await getJSON('/api/generation-state');
    if(epoch===this.epoch){this.activeBatch=data.active_batch;this.error=false;this.checking=false;this.sync();if(this.batchView)await this.refreshBatch(epoch);}
    return !this.error;
   }catch{
    if(epoch===this.epoch){this.error=true;this.checking=false;this.sync();}
    return false;
   }
  })();
  try{return await this.pending;}finally{this.pending=null;}
 }
 start(){
  if(!this.stopped)return;this.stopped=false;const cycle=++this.cycle;
  const poll=async()=>{await this.refresh();if(!this.stopped&&cycle===this.cycle)this.timer=setTimeout(poll,2000);};
  poll();
 }
 stop(){this.stopped=true;this.cycle++;clearTimeout(this.timer);}
}
