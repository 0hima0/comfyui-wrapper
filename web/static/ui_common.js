const $=id=>document.getElementById(id);
function status(text,error=false){$('status').textContent=text;$('status').hidden=!text;$('status').classList.toggle('error',error);}
async function getJSON(url, options = {}) {
 const {timeoutMs, ...request} = options;
 const writing = !['GET', 'HEAD'].includes((request.method || 'GET').toUpperCase());
 const limit = timeoutMs ?? (url === '/api/jobs' ? 120000 : writing ? 30000 : 15000);
 const controller = new AbortController();
 const forwardAbort = () => controller.abort();
 request.signal?.addEventListener('abort', forwardAbort, {once:true});
 if (request.signal?.aborted) controller.abort();
 let timer;
 try {
  return await Promise.race([
   (async () => {
    const response = await fetch(url, {...request, signal:controller.signal});
    let data;
    try { data = await response.json(); }
    catch { throw Error('サーバーの応答を読み取れませんでした。'); }
    if (!response.ok) {
     const error = Error(data.error || 'リクエストに失敗しました。');
     error.httpStatus = response.status;
     throw error;
    }
    return data;
   })(),
   new Promise((_, reject) => {
    timer = setTimeout(() => {
     reject(Error('通信の待機期限を超えました。'));
     controller.abort();
    }, limit);
   })
  ]);
 } catch (error) {
  if (writing && !error.httpStatus) {
   error.outcomeUnknown = true;
   error.message += ' サーバー側では処理済みの可能性があります。一覧や実行状態を再確認してください。自動再送はしません。';
  }
  throw error;
 } finally {
  clearTimeout(timer);
  request.signal?.removeEventListener('abort', forwardAbort);
 }
}
