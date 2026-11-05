/** Recommendations are suggestions: applying them is always an explicit action. */
const recommendationRequest=(kind,name,method='GET',values=null)=>getJSON('/api/recommendations'+(method==='GET'?'?'+new URLSearchParams({kind,name}):''),method==='GET'?undefined:{method,headers:{'Content-Type':'application/json','X-Requested-With':'LLMPC'},body:JSON.stringify({kind,name,values})});
let modelRecommendation=null,modelRecommendationEpoch=0;
async function refreshModelRecommendation(){
 const name=$('checkpoint').value,epoch=++modelRecommendationEpoch;modelRecommendation=null;
 $('apply-model-recommendation').disabled=true;$('delete-model-recommendation').disabled=true;
 if(!name)return;
 try{const data=await recommendationRequest('model',name);if(epoch!==modelRecommendationEpoch||name!==$('checkpoint').value)return;modelRecommendation=data.values;$('model-recommendation-status').textContent=data.values?'登録済み：Steps '+data.values.steps+' / CFG '+data.values.cfg+'。適用するまで現在値は変わりません。':'推奨設定は未登録です。';$('apply-model-recommendation').disabled=!data.values;$('delete-model-recommendation').disabled=!data.values;}
 catch(error){if(epoch===modelRecommendationEpoch)$('model-recommendation-status').textContent=error.message;}
}
$('save-model-recommendation').addEventListener('click',async()=>{
 const name=$('checkpoint').value;if(!name)return;const form=$('form');
 const values={steps:Number(form.elements.namedItem('steps').value),cfg:Number(form.elements.namedItem('cfg').value),sampler_name:$('sampler').value,scheduler:$('scheduler').value,clip_skip:Number($('clip-skip').value),negative:form.elements.namedItem('additional_negative').value};
 try{await recommendationRequest('model',name,'PUT',values);await refreshModelRecommendation();}catch(error){$('model-recommendation-status').textContent=error.message;}
});
$('apply-model-recommendation').addEventListener('click',()=>{
 const v=modelRecommendation;if(!v)return;const form=$('form');form.elements.namedItem('steps').value=v.steps;form.elements.namedItem('cfg').value=v.cfg;selectValue($('sampler'),v.sampler_name);selectValue($('scheduler'),v.scheduler);$('clip-skip').value=v.clip_skip;form.elements.namedItem('additional_negative').value=v.negative;$('restored-generation').value='{}';form.dispatchEvent(new Event('input',{bubbles:true}));$('model-recommendation-status').textContent='推奨設定を適用しました。';
});
$('delete-model-recommendation').addEventListener('click',async()=>{try{await recommendationRequest('model',$('checkpoint').value,'DELETE');await refreshModelRecommendation();}catch(error){$('model-recommendation-status').textContent=error.message;}});
let managedRecommendationEpoch=0;
async function refreshManagedRecommendation(){
 const epoch=++managedRecommendationEpoch,name=managedName;
 for(const id of ['save-lora-recommendation','delete-lora-recommendation','recommended-model','recommended-clip'])$(id).disabled=true;
 if(!name)return;
 try{const data=await recommendationRequest('lora',name);if(epoch!==managedRecommendationEpoch||name!==managedName)return;$('recommended-model').value=data.values?.strength_model??.7;$('recommended-clip').value=data.values?.strength_clip??.7;$('lora-recommendation-status').textContent=data.values?'推奨強度は保存済みです。':'未登録です。配布元の推奨強度を入力してください。';for(const id of ['save-lora-recommendation','recommended-model','recommended-clip'])$(id).disabled=false;$('delete-lora-recommendation').disabled=!data.values;}
 catch(error){if(epoch===managedRecommendationEpoch)$('lora-recommendation-status').textContent=error.message;}
}
for(const action of ['save','delete'])$(action+'-lora-recommendation').addEventListener('click',async()=>{
 const name=managedName;if(!name)return;const button=$(action+'-lora-recommendation');button.disabled=true;
 try{await recommendationRequest('lora',name,action==='save'?'PUT':'DELETE',{strength_model:Number($('recommended-model').value),strength_clip:Number($('recommended-clip').value)});await refreshManagedRecommendation();for(let i=0;i<3;i++)refreshLoraRecommendation(i,true);}
 catch(error){$('lora-recommendation-status').textContent=error.message;button.disabled=false;}
});
const loraRecommendationEpoch=[0,0,0],lastRecommendedNames=[null,null,null];
async function refreshLoraRecommendation(index,force=false){
 if(!force&&lastRecommendedNames[index]===$('lora-'+index).value)return;lastRecommendedNames[index]=$('lora-'+index).value;
 const name=$('lora-'+index).value,epoch=++loraRecommendationEpoch[index],button=$('apply-lora-recommendation-'+index);button.hidden=true;
 if(!name)return;
 try{const data=await recommendationRequest('lora',name);if(epoch!==loraRecommendationEpoch[index]||name!==$('lora-'+index).value)return;if(data.values){button.hidden=false;button.textContent='推奨値を適用（MODEL '+data.values.strength_model+' / CLIP '+data.values.strength_clip+'）';button.onclick=()=>{if(name!==$('lora-'+index).value)return;$('lora-'+index+'-model').value=data.values.strength_model;$('lora-'+index+'-clip').value=data.values.strength_clip;$('form').dispatchEvent(new Event('input',{bubbles:true}));};}}
 catch(error){button.hidden=false;button.textContent='推奨値の取得を再試行';button.onclick=()=>refreshLoraRecommendation(index,true);}
}
function initializeRecommendations(){
for(let index=0;index<3;index++){const button=document.createElement('button');button.id='apply-lora-recommendation-'+index;button.type='button';button.className='secondary';button.hidden=true;$('lora-'+index).closest('.lora-row').append(button);}
window.addEventListener('pageshow',()=>{refreshModelRecommendation();for(let i=0;i<3;i++)refreshLoraRecommendation(i,true);});

}
