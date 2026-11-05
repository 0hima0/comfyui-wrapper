/** Keep per-tab form values and selected files when navigating between pages. */
class WorkspaceState {
 constructor(){this.key='llmpc-workspace-v1';this.fileKey=sessionStorage.getItem('llmpc-workspace-files');if(!this.fileKey){this.fileKey=crypto.randomUUID?.()||(Date.now().toString(36)+Math.random().toString(36).slice(2));sessionStorage.setItem('llmpc-workspace-files',this.fileKey);}this.lastFiles=null;this.pending=Promise.resolve();}
 database(){
  if(!this.db)this.db=new Promise((resolve,reject)=>{const request=indexedDB.open('llmpc-workspace',1);request.onupgradeneeded=()=>request.result.createObjectStore('references');request.onsuccess=()=>{const db=request.result;const tx=db.transaction('references','readwrite');const cursor=tx.objectStore('references').openCursor();cursor.onsuccess=()=>{const row=cursor.result;if(row){if(!row.value.savedAt||Date.now()-row.value.savedAt>86400000)row.delete();row.continue();}};resolve(db);};request.onerror=()=>reject(request.error);request.onblocked=()=>reject(Error('一時保存が別の画面で使用されています。'));});
  return this.db;
 }
 async files(){const db=await this.database();return new Promise((resolve,reject)=>{const tx=db.transaction('references','readonly');const request=tx.objectStore('references').get(this.fileKey);request.onsuccess=()=>resolve(request.result&&Date.now()-request.result.savedAt<=86400000?request.result.files:[]);request.onerror=()=>reject(request.error);});}
 read(){try{return JSON.parse(sessionStorage.getItem(this.key)||'null');}catch{return null;}}
 save(snapshot,entries){
  // Text is synchronous so even an immediate page navigation retains the latest keystroke.
  sessionStorage.setItem(this.key,JSON.stringify(snapshot));
  const files=entries.filter(row=>row.file).map(row=>({id:row.id,filename:row.filename,file:row.file}));
  if(this.lastFiles&&files.length===this.lastFiles.length&&files.every((row,i)=>row.id===this.lastFiles[i].id&&row.file===this.lastFiles[i].file))return this.pending;
  this.lastFiles=files;
  this.pending=this.pending.catch(()=>{}).then(async()=>{const db=await this.database();await new Promise((resolve,reject)=>{const tx=db.transaction('references','readwrite');tx.objectStore('references').put({savedAt:Date.now(),files},this.fileKey);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||Error('参考画像の一時保存に失敗しました。'));});}).catch(error=>{this.lastFiles=null;throw error;});
  return this.pending;
 }
}
