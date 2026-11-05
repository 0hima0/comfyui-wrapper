const batchTargets=[{key:'cfg',label:'CFG',field:'cfg',start:4,end:7}, {key:'steps',label:'Steps',field:'steps',start:20,end:32},{key:'threshold',label:'WD Taggerのしきい値',field:'threshold',start:.35,end:.55},
 ...[0,1,2].flatMap(slot=>['model','clip'].map(kind=>({key:'lora-'+slot+'-'+kind,label:'LoRA '+(slot+1)+' '+kind.toUpperCase()+'強度',field:'strength_'+kind,slot,start:.5,end:.9})))];
for(const target of batchTargets){
 const row=document.createElement('tr'),labelCell=document.createElement('td'),label=document.createElement('label'),check=document.createElement('input');
 check.type='checkbox';check.id='batch-vary-'+target.key;check.name=check.id;label.append(check,document.createTextNode(' '+target.label));labelCell.append(label);row.append(labelCell);
 for(const side of ['start','end','points']){const cell=document.createElement('td'),input=document.createElement('input');input.type='number';input.step=side==='points'||target.field==='steps'?'1':'0.01';input.min=side==='points'?2:target.field==='steps'?1:target.field==='strength_model'||target.field==='strength_clip'?-2:0;input.max=side==='points'?20:target.field==='steps'?10000:target.field==='cfg'?100:target.field==='threshold'?1:2;input.value=side==='points'?3:target[side];input.addEventListener('input',syncBatchOptions);input.id='batch-'+target.key+'-'+side;input.name=input.id;input.setAttribute('aria-label',target.label+'の'+(side==='start'?'開始値':side==='end'?'終了値':'点数'));cell.append(input);row.append(cell);}
 $('batch-ranges').append(row);
 check.addEventListener('change',syncBatchOptions);
}
function syncBatchOptions(){
 const enabled=$('batch-mode').checked;$('batch-settings-panel').hidden=!enabled;$('batch-fields').hidden=!enabled;$('batch-count').disabled=!enabled;
 const matrix=$('batch-layout').value==='matrix';$('batch-count').readOnly=matrix;
 const axes=batchTargets.filter(t=>$('batch-vary-'+t.key).checked);
 const count=axes.reduce((n,t)=>n*Number($('batch-'+t.key+'-points').value),1);
 if(matrix)$('batch-count').value=axes.length?count:0;
 $('batch-plan-summary').textContent=matrix?(axes.length+'軸・合計 '+(axes.length?count:0)+'枚。最大2軸・20枚まで。同一シードで比較します。'):'指定回数で各項目を同時に変化させます。';
 for(const target of batchTargets){const points=$('batch-'+target.key+'-points');points.disabled=!enabled||!matrix||!$('batch-vary-'+target.key).checked;points.required=enabled&&matrix&&$('batch-vary-'+target.key).checked;const checked=$('batch-vary-'+target.key).checked;
  for(const side of ['start','end']){const input=$('batch-'+target.key+'-'+side);input.disabled=!enabled||!checked;input.required=enabled&&checked;}
 }
}
function batchPlan(){
 if(!$('batch-mode').checked)return null;
 if(!$('execute').checked)throw Error('連続生成では「ComfyUIで画像も生成する」をオンにしてください。');
 const values=loraValues(),slots=[0,1,2].filter(i=>$('lora-'+i).value);
 const ranges=batchTargets.filter(t=>$('batch-vary-'+t.key).checked).map(t=>{
  const range={field:t.field,start:Number($('batch-'+t.key+'-start').value),end:Number($('batch-'+t.key+'-end').value)};
  if(t.slot!==undefined){range.lora=slots.indexOf(t.slot);if(range.lora<0||!values[range.lora])throw Error('変更対象のLoRA '+(t.slot+1)+'を選択してください。');}
  if(t.field==='threshold'&&!$('use-wd').checked)throw Error('しきい値を変える場合はWD Taggerをオンにしてください。');
  return range;
 });
 if(!ranges.length)throw Error('連続生成で変更する項目を選んでください。');
 const matrix=$('batch-layout').value==='matrix';
 if(matrix){if(ranges.length>2)throw Error('条件マトリクスは最大2軸です。');const targets=batchTargets.filter(t=>$('batch-vary-'+t.key).checked);ranges.forEach((r,i)=>r.points=Number($('batch-'+targets[i].key+'-points').value));if(ranges.some(r=>!Number.isInteger(r.points)||r.points<2)||ranges.reduce((n,r)=>n*r.points,1)>20)throw Error('各軸は2点以上、合計20枚以内にしてください。');}
 return {count:Number($('batch-count').value),ranges,mode:matrix?'matrix':'linear'};
}
$('batch-layout').addEventListener('change',syncBatchOptions);
$('batch-mode').addEventListener('change',syncBatchOptions);syncBatchOptions();
