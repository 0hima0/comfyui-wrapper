/** Lightweight index plus an LRU of selected records; legacy API responses remain supported. */
let loraIndex = {};
let loraRegistry = {};
let registryReady = Promise.resolve(true);
const loraDetails = new Map();
let loraCatalogEpoch = 0;

function cacheLoraRecord(name, row) {
 loraDetails.delete(name);
 loraDetails.set(name, Promise.resolve(row));
 if (row) loraRegistry[name] = row;
 else delete loraRegistry[name];
 while (loraDetails.size > 4) {
  const old = loraDetails.keys().next().value;
  loraDetails.delete(old);
  delete loraRegistry[old];
 }
}

async function loadLoraDetail(name) {
 if (!name) return null;
 if (loraDetails.has(name)) {
  const pending = loraDetails.get(name);
  loraDetails.delete(name);
  loraDetails.set(name, pending);
  return pending;
 }
 const epoch = loraCatalogEpoch;
 const pending = getJSON('/api/lora-triggers?name=' + encodeURIComponent(name)).then(data => {
  const row = data.records[name] || null;
  if (epoch !== loraCatalogEpoch) return null;
  if (loraDetails.get(name) !== pending) return loraRegistry[name] || null;
  cacheLoraRecord(name, row);
  return row;
 }).catch(error => {
  if (loraDetails.get(name) === pending) loraDetails.delete(name);
  throw error;
 });
 loraDetails.set(name, pending);
 while (loraDetails.size > 4) {
  const old = loraDetails.keys().next().value;
  loraDetails.delete(old);
  delete loraRegistry[old];
 }
 return pending;
}

function replaceLoraIndex(records) {
 ++loraCatalogEpoch;
 loraIndex = records;
 loraDetails.clear();
 loraRegistry = {};
}

async function refreshRegistry() {
 if (typeof updateLoraNotesState === 'function') updateLoraNotesState('loading');
 try {
  const epoch = ++loraCatalogEpoch;
  const data = await getJSON('/api/lora-triggers?summary=1');
  if (epoch !== loraCatalogEpoch) return false;
  replaceLoraIndex(data.records);
  await Promise.all([0,1,2].map(i => loadLoraDetail($('lora-' + i)?.value)));
  if (typeof updateLoraNotesState === 'function') updateLoraNotesState('ready');
  return true;
 } catch (error) {
  if (typeof updateLoraNotesState === 'function') updateLoraNotesState('error');
  $('lora-hint').textContent = 'LoRA登録情報を取得できませんでした：' + error.message;
  return false;
 }
}

async function fillLoraTrigger(index) {
 const select = $('lora-' + index), input = $('lora-' + index + '-trigger');
 const name = select.value;
 input.value = '';
 if (!name) return;
 try {
  await registryReady;
  const row = await loadLoraDetail(name);
  if (select.value === name && input.value === '') input.value = row?.trigger || '';
  if (typeof renderLoraNotes === 'function') renderLoraNotes();
 } catch {
  if (typeof updateLoraNotesState === 'function') updateLoraNotesState('error');
 }
}
