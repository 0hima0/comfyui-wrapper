/** Selected-record details and a copy action that preserves the original text. */
let loraNotesState = 'loading';
let loraNotesRequest = 0;

function renderLoraNotes() {
 for (let index=0; index<3; index++) {
  const name=$('lora-'+index).value;
  const row=loraRegistry[name];
  if(name&&!loraDetails.has(name)&&loraNotesState!=='error') {
   loadLoraDetail(name).then(()=>{if($('lora-'+index).value===name)renderLoraNotes();})
    .catch(()=>{loraNotesState='error';renderLoraNotes();});
  }
  const box=$('lora-'+index+'-note-box');
  if(!box)continue;
  box.hidden=!name;
  $('lora-'+index+'-note').textContent=!name?'':loraNotesState==='error'
   ?'登録メモを取得できません。一覧を更新して再試行してください。'
   :row?.note||(loraNotesState==='loading'?'登録メモを読み込んでいます…':'このLoRAのメモは未登録です。');
  const prompt=$('lora-'+index+'-recommended-prompt');
  prompt.textContent=row?.recommended_prompt||'';
  $('lora-'+index+'-copy-prompt').disabled=!row?.recommended_prompt;
 }
}

async function updateLoraNotesState(state) {
 loraNotesState=state;
 renderLoraNotes();
 if(state!=='ready')return;
 const requestId=++loraNotesRequest;
 try {
  await Promise.all([0,1,2].map(i=>loadLoraDetail($('lora-'+i).value)));
  if(requestId===loraNotesRequest)renderLoraNotes();
 } catch {
  if(requestId===loraNotesRequest){loraNotesState='error';renderLoraNotes();}
 }
}

async function copyLoraPrompt(index) {
 const prompt=$('lora-'+index+'-recommended-prompt');
 const message=$('lora-'+index+'-copy-status');
 const text=prompt.textContent;
 try {
  if(!navigator.clipboard||!window.isSecureContext)throw Error('clipboard unavailable');
  await navigator.clipboard.writeText(text);
  message.textContent='コピーしました。';
 } catch {
  const selection=window.getSelection();
  const range=document.createRange();range.selectNodeContents(prompt);
  selection.removeAllRanges();selection.addRange(range);
  let copied=false;
  try{copied=document.execCommand('copy');}catch{}
  message.textContent=copied?'コピーしました。':'文字列を選択しました。Ctrl+Cなどでコピーしてください。';
 }
}

function initializeLoraNotes() {
 for(let index=0; index<3; index++) {
  const box=document.createElement('section');
  box.id='lora-'+index+'-note-box';box.className='lora-saved-note';box.hidden=true;
  box.setAttribute('aria-label','LoRA '+(index+1)+'の登録メモ');
  const title=document.createElement('strong');title.textContent='登録メモ（参照用）';
  const note=document.createElement('p');note.id='lora-'+index+'-note';note.setAttribute('role','status');
  const promptTitle=document.createElement('strong');promptTitle.textContent='推奨プロンプト（参照・コピー用）';
  const prompt=document.createElement('p');prompt.id='lora-'+index+'-recommended-prompt';
  const copy=document.createElement('button');copy.id='lora-'+index+'-copy-prompt';copy.type='button';
  copy.className='secondary';copy.textContent='推奨プロンプトをコピー';copy.disabled=true;
  copy.addEventListener('click',()=>copyLoraPrompt(index));
  const message=document.createElement('p');message.id='lora-'+index+'-copy-status';message.setAttribute('role','status');
  box.append(title,note,promptTitle,prompt,copy,message);
  $('lora-'+index).closest('.lora-row').append(box);
 }
}
