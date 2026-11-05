"""Run independent analysis tasks once each, with one request per Ollama server."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from comfyui_wrapper.infrastructure import job_control


def run(tasks, endpoints, progress):
    """Return results in task order, even when requests complete out of order."""
    started=time.monotonic()
    parent=job_control.current()
    count=min(len(endpoints),len(tasks))
    controls=[job_control.JobControl() for _ in range(count)]
    results=[None]*len(tasks)
    records=[None]*len(tasks)
    lock=threading.Lock()
    next_task=0
    completed=0
    errors=[]
    finished=threading.Event()

    def stop_all():
        for control in controls:control.event.set()

    def watch_cancel():
        while not finished.wait(.05):
            if parent is not None and parent.event.is_set():
                stop_all();return

    def worker(worker_index):
        nonlocal next_task,completed
        job_control.local.control=controls[worker_index]
        endpoint=endpoints[worker_index]
        try:
            while True:
                with lock:
                    if errors or next_task>=len(tasks):return
                    index=next_task;next_task+=1
                job_control.check()
                label,call=tasks[index]
                progress(f'{label}を解析しています…（解析先{worker_index+1}）')
                task_start=time.monotonic()
                value=call(endpoint)
                job_control.check()
                with lock:
                    results[index]=value
                    records[index]=dict(task=label,ollama_url=endpoint,
                                        seconds=round(time.monotonic()-task_start,3))
                    completed+=1
                    done_count=completed
                progress(f'画像解析 {done_count} / {len(tasks)}件完了')
        except Exception as error:
            with lock:
                if not errors:errors.append(error)
            stop_all()
        finally:
            job_control.local.control=None

    if parent is not None:parent.check()
    watcher=threading.Thread(target=watch_cancel,daemon=True)
    watcher.start()
    try:
        with ThreadPoolExecutor(max_workers=count,thread_name_prefix='ollama-analysis') as pool:
            futures=[pool.submit(worker,index) for index in range(count)]
            for future in futures:future.result()
        if parent is not None:parent.check()
        if errors:raise errors[0]
        return results,dict(mode='parallel' if count>1 else 'serial',
                            endpoints=endpoints,wall_seconds=round(time.monotonic()-started,3),tasks=records)
    finally:
        finished.set()
        watcher.join(timeout=1)
