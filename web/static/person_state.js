/* Preserve the requested option and report whether it can apply. */
function personPreservationState(count,requested,family){
 if(!requested)return 'オフ：人物維持は適用しません。';
 if(count<2)return '未適用：参考画像を2枚以上追加すると利用できます（現在'+count+'枚）。';
 if(!['sd15','sdxl','illustrious'].includes(family))return '未適用：対応するSD1.5・SDXL・Illustriousのモデルを選択してください。';
 return '人物維持を使用：'+count+'枚を人物別に扱います。必要なノード・モデルは実行前に確認します。';
}
function refreshPersonState(entries=null){
 const control=$('preserve-people'),node=$('person-preservation-state');
 if(!control||!node)return;
 const entry=availableModels[Number($('generation-model').value)],count=(entries||referenceEditor.entries).length;
 control.disabled=count<2||!['sd15','sdxl','illustrious'].includes(entry?.family);
 node.textContent=personPreservationState(count,control.checked,entry?.family);
 const hint=$('generation-context-hint');if(hint)hint.textContent=count?'参考画像 '+count+'枚を使用します。'+($('use-wd').checked?'WDタグ抽出を併用します。':'画像の特徴はOllamaで解析します。'):'画像なし：指示または追加Positive Promptを入力してください。画像解析・WDタグ抽出・人物維持は省略します。';
 const loraHint=$('person-lora-hint');if(loraHint)loraHint.hidden=control.disabled||!control.checked;
 const conflict=$('wd-conflict-hint');if(conflict)conflict.hidden=!count||!$('use-wd').checked;
}
