/* In-page completion feedback; no browser notification permission is needed. */
let completionNoticeTimer;
function showCompletionNotice(){
 const notice=document.getElementById('completion-notice');
 if(!notice)return;
 clearTimeout(completionNoticeTimer);
 notice.hidden=false;
 notice.querySelector('[role="status"]').textContent='画像生成が完了しました。';
 completionNoticeTimer=setTimeout(()=>{notice.hidden=true;},10000);
}
document.getElementById('close-completion-notice')?.addEventListener('click',()=>{
 clearTimeout(completionNoticeTimer);
 document.getElementById('completion-notice').hidden=true;
});