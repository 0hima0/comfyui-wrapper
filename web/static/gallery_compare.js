/** Compare saved execution records, using actual sampler settings where available. */
const MAX_GALLERY_COMPARISON=5;
function comparisonCanonical(value){
 if(value===undefined||value===null)return 'null';
 if(Array.isArray(value))return '['+value.map(comparisonCanonical).join(',')+']';
 if(typeof value==='object')return '{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+comparisonCanonical(value[key])).join(',')+'}';
 return JSON.stringify(value);
}
function comparisonValue(value){if(value===undefined||value===null)return '—';if(value==='')return '（空欄）';if(Array.isArray(value)&&value.length===0)return 'なし';if(typeof value==='boolean')return value?'オン':'オフ';return typeof value==='object'?JSON.stringify(value,null,2):String(value);}
function comparisonRows(record){
 const s=record.settings||{},g=record.generation_settings||{},effective=s.generation_effective||{};
 const generation=key=>g[key]??effective[key];
 const refs=s.input_images||(s.input_image?[s.input_image]:null);
 const loras=s.loras?.map(row=>({name:row.name,strength_model:row.strength_model,strength_clip:row.strength_clip,trigger:row.trigger,scope:row.scope}));
 return [
  ['生成モデル',s.checkpoint],['モデルの種類',s.model_family?.family_label],['設定プロファイル',s.profile],['ワークフロー方式',s.target],
  ['幅（px）',s.width],['高さ（px）',s.height],['シード',s.seed],['Steps',generation('steps')],['CFG',generation('cfg')],
  ['サンプラー',generation('sampler_name')],['スケジューラー',generation('scheduler')],['Denoise',generation('denoise')],
  ['CLIP skip',s.clip_skip],['品質タグを追加',s.use_quality_tags],['画像生成を実行',s.execute],['人物・服装の維持',s.preserve_people],
  ['解析モデル',s.analysis_model],['WD Tagger',s.use_wd],['タグのしきい値',s.threshold],['レーティングタグ',s.rating],
  ['変更したい内容',s.instruction],['追加Positive',s.additional_positive],['追加Negative',s.additional_negative],
  ['LoRA（名前・強度・トリガー・適用先）',loras],['LoRAの実際の適用先',s.lora_assignments],
  ['参考画像（名前・使う要素・サイズ）',refs],['人物維持用モデル',s.person_models],
  ['最終Positive',record.result?.positive],['最終Negative',record.result?.negative],
 ];
}
class GalleryComparison {
 constructor(){
  this.selected=new Map();this.controls=new Map();this.busy=false;this.displayedItems=null;this.single=false;
  $('open-comparison').addEventListener('click',()=>this.open());
  $('reload-comparison').addEventListener('click',()=>this.open(this.displayedItems));
  $('clear-comparison').addEventListener('click',()=>{this.selected.clear();this.sync();});
  $('close-comparison').addEventListener('click',()=>$('comparison-viewer').close());
  $('comparison-differences').addEventListener('change',()=>this.filter());
 }
 key(item){return item.job_id+'/'+item.filename;}
 register(item,card,body){
  const label=document.createElement('label');label.className='gallery-select';
  const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.setAttribute('aria-label',(item.comfy_filename||item.filename)+'を比較に追加');
  const text=document.createElement('span');text.textContent='比較に追加';label.append(checkbox,text);body.append(label);
  const key=this.key(item);this.controls.set(key,{checkbox,card});
  checkbox.addEventListener('change',()=>{if(checkbox.checked){if(this.selected.size>=MAX_GALLERY_COMPARISON){checkbox.checked=false;return;}this.selected.set(key,item);}else this.selected.delete(key);this.sync();});
  this.sync();
 }
 sync(){
  for(const [key,{checkbox,card}] of this.controls){const selected=this.selected.has(key);checkbox.checked=selected;checkbox.disabled=this.busy||(!selected&&this.selected.size>=MAX_GALLERY_COMPARISON);card.classList.toggle('compare-chosen',selected);}
  const count=this.selected.size;$('compare-count').closest?.('.compare-bar')?.classList.toggle('has-selection',count>0);$('compare-count').textContent='比較する画像：'+count+' / '+MAX_GALLERY_COMPARISON+'枚';
  $('compare-selection-status').textContent=count===MAX_GALLERY_COMPARISON?MAX_GALLERY_COMPARISON+'枚を選択中です。別の画像を選ぶには選択を解除してください。':count>=2?'「設定を比較」で生成時の設定を横並びで確認できます。':'各画像の「比較に追加」で2〜5枚を選択してください。';
  $('open-comparison').disabled=this.busy||count<2;$('clear-comparison').disabled=this.busy||count===0;$('reload-comparison').disabled=this.busy;
  $('compare-selected').replaceChildren();
  for(const [key,item] of this.selected){const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent=(item.comfy_filename||item.filename)+' ×';button.setAttribute('aria-label',(item.comfy_filename||item.filename)+'の比較選択を解除');button.disabled=this.busy;button.addEventListener('click',()=>{this.selected.delete(key);this.sync();});$('compare-selected').append(button);}
 }
 async open(requested=null){
  const items=requested||[...this.selected.values()];
  if(this.busy||items.length<1||items.length>MAX_GALLERY_COMPARISON||(!requested&&items.length<2))return;
  this.displayedItems=items;this.single=items.length===1;this.busy=true;this.sync();
  $('comparison-title').textContent=this.single?'画像の詳細':'生成時の設定を比較';
  const downloads=$('comparison-downloads');
  if(downloads){downloads.replaceChildren();if(this.single&&items[0].settings_url){const link=document.createElement('a');link.href=items[0].settings_url;link.className='download secondary';link.textContent='設定JSON';downloads.append(link);}}
  $('comparison-filter').hidden=this.single;
  $('reload-comparison').textContent=this.single?'設定を更新':'比較を更新';
  $('comparison-viewer').classList.toggle('single-settings',this.single);
  const dialog=$('comparison-viewer');if(!dialog.open)dialog.showModal();
  $('comparison-table').replaceChildren();$('comparison-status').textContent='生成時の設定を読み込んでいます…';
  try{
   const ids=[...new Set(items.map(item=>item.job_id))];
   const records=await Promise.all(ids.map(id=>getJSON('/api/history/'+encodeURIComponent(id))));
   const byId=new Map(ids.map((id,index)=>[id,records[index]]));
   this.render(items,items.map(item=>byId.get(item.job_id)));
  }catch(error){$('comparison-status').textContent='生成時の設定を取得できませんでした。'+error.message+' 「'+(this.single?'設定を更新':'比較を更新')+'」で再試行できます。';}
  finally{this.busy=false;this.sync();}
 }
 render(items,records){
  this.single=items.length===1;
  const table=$('comparison-table');table.replaceChildren();
  table.style?.setProperty('--comparison-min-width',(170+items.length*220)+'px');
  const caption=document.createElement('caption');caption.textContent=this.single?'この画像を生成したときの設定です。未記録の値は「—」です。':items.length+'枚の生成時設定。色付きの行は値が異なる項目です。未記録の値は「—」です。';table.append(caption);
  const head=document.createElement('thead'),header=document.createElement('tr'),corner=document.createElement('th');corner.scope='col';corner.textContent='設定項目';header.append(corner);
  for(const item of items){
   const th=document.createElement('th');th.scope='col';const img=document.createElement('img');img.src=item.thumbnail_url||item.image_url;img.alt=item.comfy_filename||item.filename;
   const name=document.createElement('strong');name.textContent=item.comfy_filename||item.filename;
   const time=document.createElement('p');time.className='hint';time.textContent=galleryTime(item.created_at);
   const link=document.createElement('a');link.className='download secondary';link.href=item.restore_url;link.textContent='この設定を使う';th.append(img,name,time,link);header.append(th);
  }
  head.append(header);table.append(head);
  const body=document.createElement('tbody'),columns=records.map(comparisonRows);
  columns[0].forEach(([label],index)=>{
   const values=columns.map(column=>column[index][1]);const different=new Set(values.map(comparisonCanonical)).size>1;
   const row=document.createElement('tr');row.dataset.different=String(different);const heading=document.createElement('th');heading.scope='row';heading.textContent=label+(different?'（差異あり）':'');row.append(heading);
   for(const value of values){const cell=document.createElement('td');cell.textContent=comparisonValue(value);row.append(cell);}body.append(row);
  });
  table.append(body);this.filter();
 }
 filter(){
  const rows=[...$('comparison-table').querySelectorAll('tbody tr')];let differences=0;
  for(const row of rows){const different=row.dataset.different==='true';if(different)differences++;row.hidden=!this.single&&$('comparison-differences').checked&&!different;}
  if(rows.length)$('comparison-status').textContent=this.single?rows.length+'項目を表示しています。':differences+'項目に違いがあります。'+($('comparison-differences').checked&&differences===0?' 比較対象の設定は同じです。':'');
 }
}
