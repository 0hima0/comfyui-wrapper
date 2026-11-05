initializeModelSettings();
initializeLoraNotes();
initializeRecommendations();
initializeLoraManager();
/* Compose page components; business logic lives in the feature modules. */
const workspaceState = new WorkspaceState();
let workspaceReady = false;
let activeJob = null;
let reuseSource = null;
const generationGate = new GenerationGate($('submit'), $('generation-availability'), $('active-batch-link'), {root:$('batch-progress-summary')});
const progressView = new JobProgressView($('job-progress'));
const referenceEditor = new ReferenceEditor({
 input: $('image'), drop: $('drop'), list: $('reference-list'), count: $('reference-count'),
 message: $('reference-status'), maxImages: Number($('image').dataset.maxImages), onChange: referencesChanged
});
initializeResultView();
const generationActions = initializeGenerationActions();
const monitor = job => generationActions.monitor(job);

const executionControls = new ExecutionControls({
 gate:generationGate, progress:progressView, bar:document.querySelector('.floating-runbar'),
 elements:$, hasImages:()=>referenceEditor.entries.length>0
});

$('use-wd').addEventListener('change', () => {
 $('wd-settings').querySelector('input').disabled = !$('use-wd').checked;
});
function toggleAdditionalPrompts(){
 $('prompt-only').checked = !$('execute').checked;
 if(typeof syncExecutionChrome==='function'&&typeof referenceEditor!=='undefined')syncExecutionChrome();
 for (const input of $('additional-prompts').querySelectorAll('textarea')) input.disabled = false;
}
$('execute').addEventListener('change', toggleAdditionalPrompts);
toggleAdditionalPrompts();

for (const id of ['positive', 'negative']) $(id).addEventListener('input', () => {markWorkspaceEdited();saveWorkspace();});
$('form').addEventListener('input', () => {markWorkspaceEdited();saveWorkspace();});
$('form').addEventListener('change', () => {markWorkspaceEdited();refreshPersonState();syncExecutionChrome();queueMicrotask(saveWorkspace);});
window.addEventListener('pagehide', () => {saveWorkspace(); generationGate.stop();});
window.addEventListener('pageshow', () => generationGate.start());
window.addEventListener('focus', () => generationGate.refresh());
document.addEventListener('visibilitychange', () => {if (!document.hidden) generationGate.refresh();});
document.addEventListener('click', async event => {
 const link = event.target.closest('a[href]');
 if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || link.target || link.hasAttribute('download')) return;
 const url = new URL(link.href, window.location.href);
 const internal = ['/', '/gallery', '/loras', '/batches'].includes(url.pathname) || /^\/batch\/[a-f0-9]{32}\/?$/.test(url.pathname);
 if (url.origin !== window.location.origin || !internal) return;
 event.preventDefault();
 await saveWorkspace();
 window.location.assign(url.href);
});

generationGate.start();
initializeWorkspace().catch(() => {
 $('restored-note').textContent = '画面を読み込めませんでした。再読み込みしてください。';
 generationGate.setLocalBusy(false);
});

$('prompt-only').addEventListener('change',()=>{
 $('execute').checked=!$('prompt-only').checked;
 $('execute').dispatchEvent(new Event('change'));
 saveWorkspace();
});
function syncExecutionChrome(){executionControls.refreshMode();}
$('expand-run-modes').addEventListener('click',()=>{const bar=document.querySelector('.floating-runbar'),expanded=bar.classList.toggle('modes-expanded');$('expand-run-modes').setAttribute('aria-expanded',String(expanded));});
function focusRunStatus(){executionControls.focusStatus();}

initializeInstructionPresets();
