"""Real-page integration tests with synthetic upstream models and images."""
import io
import os
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from werkzeug.serving import make_server, WSGIRequestHandler
from comfyui_wrapper.webui import create_app

ROOT = Path(__file__).resolve().parents[2]


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


@unittest.skipUnless(os.environ.get('WRAPPER_BROWSER_TESTS') == '1',
                     'Use tools/dev/run_tests.py --browser-only to run Chromium tests')
class GenerationBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch()
        except Exception:
            cls.playwright.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'tests')
        self.root = Path(self.temp.name)
        self.patches = ExitStack()
        self.entered, self.release = threading.Event(), threading.Event()
        self.release.set()
        self.patches.enter_context(patch('comfyui_wrapper.models.model_catalog.ModelCatalog.checkpoints',
            side_effect=lambda target: dict(names=['AnimagineXL_v31.safetensors'] if target == 'animagine' else [],
                                           source='comfyui', warning='', default='AnimagineXL_v31.safetensors')))
        info = dict(LoraLoader=dict(input=dict(required=dict(lora_name=[['sdxl/sample.safetensors']]))),
                    KSampler=dict(input=dict(required=dict(sampler_name=[['euler_ancestral']],
                                                           scheduler=[['normal']]))))
        self.patches.enter_context(patch('comfyui_wrapper.integrations.comfy_client.api', return_value=info))
        self.patches.enter_context(patch('comfyui_wrapper.system.preflight.check', return_value=dict(ok=True, checks=[])))
        def analyze(*args, **kwargs):
            self.entered.set()
            if not self.release.wait(15):
                raise AssertionError('test analysis did not resume')
            return dict(positive='park bench', negative='text', summary_ja='公園', uncertainties_ja='')
        self.patches.enter_context(patch('comfyui_wrapper.analysis.generate.analyze', side_effect=analyze))
        self.patches.enter_context(patch('comfyui_wrapper.integrations.comfy_client.execute',
                                        return_value=[dict(filename='synthetic.png')]))
        image = io.BytesIO()
        Image.new('RGB', (32, 48), 'blue').save(image, 'PNG')
        self.png = image.getvalue()
        self.patches.enter_context(patch('comfyui_wrapper.integrations.comfy_client.fetch_image', return_value=self.png))
        self.app = create_app(self.root)
        self.server = make_server('127.0.0.1', 0, self.app, threaded=True, request_handler=QuietHandler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.context = self.browser.new_context(viewport=dict(width=1440, height=1000))
        self.page = self.context.new_page()
        self.page.set_default_timeout(8000)
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.posts = []
        self.page.on('request', lambda request: self.posts.append(request.url)
                     if request.method == 'POST' and request.url.endswith('/api/jobs') else None)

    def tearDown(self):
        self.release.set()
        self.context.close()
        deadline = time.monotonic() + 10
        while self.app.extensions['generation_lock'].locked() and time.monotonic() < deadline:
            time.sleep(.01)
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(3)
        self.patches.close()
        self.temp.cleanup()

    def open_generation(self):
        self.page.goto(self.url)
        self.page.wait_for_function('workspaceReady && !document.getElementById("submit").disabled')
        self.assertEqual(self.page.locator('#generation-model option').count(), 1)
        self.assertEqual(self.page.locator('#lora-0 option').count(), 2)

    def complete_generation(self):
        self.open_generation()
        self.page.locator('[name=instruction]').fill('公園のベンチ')
        with self.page.expect_response(lambda response: response.url.endswith('/api/jobs')
                                       and response.request.method == 'POST') as accepted:
            self.page.locator('#submit').click()
        job = accepted.value.json()['job_id']
        self.page.wait_for_function('!document.getElementById("submit").disabled && document.querySelector("#generated-images img")')
        return job

    def test_stalled_instruction_save_returns_controls_without_resending(self):
        self.open_generation()
        self.page.locator('#field-instruction').fill('保存する指示')
        self.page.locator('#instruction-name').fill('timeout test')
        self.page.evaluate('''() => {
            const originalJSON=getJSON,originalFetch=fetch;
            window.stalledPosts=0;
            getJSON=(url,options={})=>originalJSON(url,{...options,timeoutMs:20});
            window.fetch=(url,options)=>{
                if(url==='/api/instruction-presets'&&options?.method==='POST'){
                    stalledPosts++;return new Promise(()=>{});
                }
                return originalFetch(url,options);
            };
        }''')
        self.page.locator('#save-instruction').click()
        self.page.wait_for_function('document.getElementById("instruction-save-status").textContent.includes("待機期限")')
        self.assertFalse(self.page.locator('#save-instruction').is_disabled())
        self.assertIn('処理済みの可能性',self.page.locator('#instruction-save-status').inner_text())
        self.assertEqual(self.page.evaluate('stalledPosts'),1)
        self.assertEqual(self.errors,[])

    def test_lost_submission_response_reuses_receipt_without_second_generation(self):
        self.open_generation()
        self.page.locator('#field-instruction').fill('受付応答を失った場合')
        self.page.evaluate('''() => {
            const original=fetch;window.receiptIds=[];
            window.fetch=async(url,options)=>{
                if(url==='/api/jobs'){
                    receiptIds.push(options.headers['X-Request-ID']);
                    const response=await original(url,options);
                    if(receiptIds.length===1)return new Response('invalid JSON',{status:202});
                    return response;
                }
                return original(url,options);
            };
        }''')
        self.page.locator('#submit').click()
        self.page.wait_for_function('!document.getElementById("submit").disabled && document.getElementById("status").textContent.includes("処理済みの可能性")')
        self.assertEqual(self.page.evaluate('receiptIds.length'),1)
        self.page.locator('#submit').click()
        self.page.wait_for_selector('#generated-images img')
        ids=self.page.evaluate('receiptIds')
        self.assertEqual(len(ids),2)
        self.assertEqual(ids[0],ids[1])
        self.assertEqual(len(self.app.extensions['app_services'].history.latest()),1)
        self.assertIsNone(self.page.evaluate('sessionStorage.getItem("llmpc-pending-submission")'))
        self.assertEqual(self.errors,[])

    def test_lora_prompt_copy_preserves_text_and_insecure_http_fallback(self):
        prompt='日本語の推奨\nsoft light, '+('長文 '*2000)
        self.app.extensions['app_services'].lora_store.save('sdxl/sample.safetensors','token','','memo',recommended_prompt=prompt)
        self.open_generation()
        self.page.locator('#lora-0').select_option('sdxl/sample.safetensors')
        self.page.wait_for_function('!document.getElementById("lora-0-copy-prompt").disabled')
        self.page.evaluate('Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:async text=>window.copiedPrompt=text}})')
        self.page.locator('#lora-0-copy-prompt').click()
        self.assertEqual(self.page.evaluate('copiedPrompt'),prompt)
        self.assertEqual(self.page.locator('[name=additional_positive]').input_value(),'')
        # A routed HTTP origin behaves like a LAN hostname while all traffic stays local.
        self.context.route('http://wrapper.test/**',lambda route:route.fulfill(response=self.context.request.get(route.request.url.replace('http://wrapper.test',self.url))))
        self.page.goto('http://wrapper.test/')
        self.page.wait_for_function('workspaceReady')
        self.assertFalse(self.page.evaluate('isSecureContext'))
        self.page.locator('#lora-0').select_option('sdxl/sample.safetensors')
        self.page.wait_for_function('!document.getElementById("lora-0-copy-prompt").disabled')
        self.page.evaluate('document.execCommand=()=>false')
        self.page.locator('#lora-0-copy-prompt').click()
        self.assertEqual(self.page.evaluate('window.getSelection().toString()'),prompt)
        self.assertIn('Ctrl+C',self.page.locator('#lora-0-copy-status').inner_text())
        self.assertEqual(self.errors,[])

    def test_manager_does_not_render_a_stale_detail_response(self):
        self.open_generation();self.page.locator('#open-lora-manager').click()
        self.page.wait_for_function('managedName && !document.getElementById("refresh-managed-loras").disabled')
        self.page.evaluate('''() => {
            const original=getJSON;
            replaceLoraIndex({});window.detailReplies={};
            getJSON=(url,...args)=>url.startsWith('/api/lora-triggers?name=')
              ?new Promise(resolve=>detailReplies[decodeURIComponent(url.split('name=')[1])]=resolve):original(url,...args);
            const select=document.getElementById('managed-lora');
            select.add(new Option('second','sdxl/second'));
            select.value='sdxl/sample.safetensors';readManagedRecord();
            select.value='sdxl/second';readManagedRecord();
        }''')
        self.page.evaluate("detailReplies['sdxl/second']({records:{'sdxl/second':{note:'new detail',tags:[]}}})")
        self.page.wait_for_function('managedName==="sdxl/second"')
        self.page.evaluate("detailReplies['sdxl/sample.safetensors']({records:{'sdxl/sample.safetensors':{note:'stale detail',tags:[]}}})")
        self.assertEqual(self.page.locator('#managed-note').input_value(),'new detail')
        self.assertEqual(self.errors,[])

    def test_interrupted_job_can_be_checked_and_imported_from_results(self):
        from comfyui_wrapper.analysis import generate
        job=self.complete_generation()
        runner=self.app.extensions['app_services'].runner
        folder=self.root/job;graph=generate.read_json(folder/'workflow_api.json')
        prompt='saved-browser-prompt'
        report=generate.read_json(folder/'analysis.json');report['prompt_id']=prompt;generate.write_json(folder/'analysis.json',report)
        record=runner.history.get(job);record.update(state='error',prompt_id=prompt,images=[],output_files=[],message='追跡中断')
        runner.history.save(job,record)
        node=next(key for key,value in graph.items() if value['class_type']=='SaveImage')
        history={prompt:dict(prompt=[1,prompt,graph],status=dict(completed=True,status_str='success'),outputs={node:dict(images=[dict(filename='recovered.png')])})}
        self.page.reload();self.page.wait_for_selector('#job-recovery button')
        with patch('comfyui_wrapper.generation.job_recovery.comfy_client.api',return_value=history):
            self.page.get_by_role('button',name='ComfyUIの状態を再確認',exact=True).click()
            self.page.get_by_role('button',name='完成画像を取り込む',exact=True).wait_for(state='visible')
            self.page.get_by_role('button',name='完成画像を取り込む',exact=True).click()
            self.page.wait_for_function('document.getElementById("job-recovery").children.length===0')
        self.assertEqual(runner.history.get(job)['images'],['image_0.png'])
        self.assertEqual(self.errors,[])

    def test_manager_refresh_locks_fields_and_retains_draft_on_failure(self):
        self.open_generation()
        self.page.locator('#open-lora-manager').click()
        self.page.wait_for_function('managedName && !document.getElementById("refresh-managed-loras").disabled')
        fields = ['managed-trigger', 'managed-note', 'managed-tags', 'managed-recommended-prompt']
        for field in fields:
            self.page.locator('#' + field).fill('draft ' + field)
        self.page.on('dialog', lambda dialog: dialog.accept())
        self.page.evaluate('''() => {
            window.originalJSON=getJSON;
            getJSON=(url,...args)=>url==='/api/generation-options'
              ?new Promise((resolve,reject)=>{window.failOptions=reject;}) : originalJSON(url,...args);
        }''')
        self.page.locator('#refresh-managed-loras').click()
        for field in fields:
            self.assertTrue(self.page.locator('#' + field).is_disabled())
        self.page.evaluate("failOptions(Error('offline'))")
        self.page.wait_for_function('!document.getElementById("refresh-managed-loras").disabled')
        for field in fields:
            self.assertEqual(self.page.locator('#' + field).input_value(), 'draft ' + field)
            self.assertFalse(self.page.locator('#' + field).is_disabled())
        self.assertIn('未保存', self.page.locator('#manager-save-state').inner_text())
        self.assertIn('入力を保持', self.page.locator('#manager-status').inner_text())
        self.assertEqual(self.errors, [])

    def test_manager_ignores_response_after_close_and_reopen(self):
        self.open_generation()
        self.page.locator('#open-lora-manager').click()
        self.page.wait_for_function('managedName && !document.getElementById("refresh-managed-loras").disabled')
        self.page.evaluate('''() => {
            window.originalJSON=getJSON;window.optionReplies=[];
            getJSON=(url,...args)=>url==='/api/generation-options'
              ?new Promise(resolve=>optionReplies.push(resolve)) : originalJSON(url,...args);
        }''')
        self.page.locator('#refresh-managed-loras').click()
        self.page.wait_for_function('optionReplies.length===1')
        self.page.locator('#close-lora-manager').click()
        self.page.locator('#open-lora-manager').click()
        self.page.wait_for_function('optionReplies.length===2')
        self.page.evaluate("optionReplies[1]({loras:['sdxl/sample.safetensors'],warnings:[]})")
        self.page.wait_for_function('!document.getElementById("refresh-managed-loras").disabled')
        self.page.locator('#managed-note').fill('new draft')
        self.page.evaluate("optionReplies[0]({loras:[],warnings:[]})")
        self.assertEqual(self.page.locator('#managed-note').input_value(), 'new draft')
        self.assertIn('未保存', self.page.locator('#manager-save-state').inner_text())
        self.assertEqual(self.errors, [])

    def test_zip_failure_warning_and_retry_on_real_page(self):
        from comfyui_wrapper.generation import job_archive
        with patch.object(job_archive, 'build', side_effect=OSError('disk failed')):
            job = self.complete_generation()
        self.assertEqual(self.page.locator('#downloads a[download="results.zip"]').count(), 0)
        self.assertEqual(self.page.locator('#downloads a[download="image_0.png"]').count(), 1)
        self.assertIn('個別の成果物は保存', self.page.locator('#downloads').inner_text())
        with patch.object(job_archive, 'build', side_effect=OSError('retry failed')):
            self.page.get_by_role('button', name='ZIPを再作成', exact=True).click()
            self.page.wait_for_function('document.querySelector("#downloads button") && !document.querySelector("#downloads button").disabled')
        self.assertEqual(self.page.locator('#downloads a[download="results.zip"]').count(), 0)
        self.page.get_by_role('button', name='ZIPを再作成', exact=True).click()
        self.page.wait_for_selector('#downloads a[download="results.zip"]')
        self.assertEqual(self.errors, [])

    def test_real_page_initialization_and_reference_restore_after_navigation(self):
        self.open_generation()
        self.page.locator('[name=instruction]').fill('入力を保持する')
        self.page.locator('[name=cfg]').fill('6.5')
        self.page.locator('#image').set_input_files(dict(name='reference.png', mimeType='image/png', buffer=self.png))
        self.page.evaluate('saveWorkspace()')
        self.page.locator('a[data-sidebar-page=gallery]').click()
        self.page.wait_for_url('**/gallery')
        self.page.locator('a[data-sidebar-page=generate]').click()
        self.page.wait_for_url(self.url + '/')
        self.page.wait_for_function('workspaceReady && !document.getElementById("submit").disabled')
        self.assertEqual(self.page.locator('[name=instruction]').input_value(), '入力を保持する')
        self.assertEqual(self.page.locator('[name=cfg]').input_value(), '6.5')
        self.assertEqual(self.page.evaluate('referenceEditor.entries.filter(row=>!!row.file).length'), 1)
        self.assertEqual(self.errors, [])

    def test_click_submission_and_inflight_navigation_keep_state(self):
        self.open_generation()
        self.release.clear()
        self.page.locator('[name=instruction]').fill('二人が公園で話す')
        self.page.locator('[name=seed]').fill('42')
        self.page.locator('[name=seed]').press('Enter')
        self.page.wait_for_timeout(100)
        self.assertEqual(self.posts, [])
        self.page.locator('#submit').click()
        self.page.wait_for_function('generationGate.busyKind==="running"')
        self.assertTrue(self.entered.wait(3))
        self.assertTrue(self.page.locator('#submit').is_disabled())
        self.assertTrue(self.page.locator('#reuse-analysis').is_disabled())
        self.assertTrue(self.page.locator('#prompt-only').is_disabled())
        self.page.locator('a[data-sidebar-page=gallery]').click()
        self.page.wait_for_url('**/gallery')
        self.page.locator('a[data-sidebar-page=generate]').click()
        self.page.wait_for_url(self.url + '/')
        self.page.wait_for_function('typeof workspaceReady!=="undefined" && workspaceReady && generationGate.busyKind==="running"')
        self.assertEqual(self.page.locator('[name=instruction]').input_value(), '二人が公園で話す')
        self.release.set()
        self.page.wait_for_function('!document.getElementById("submit").disabled && document.querySelector("#generated-images img")')
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.app.extensions['image_jobs'], {})
        self.assertEqual(self.errors, [])

    def test_gallery_restore_for_reference_free_generation_and_responsive_controls(self):
        job = self.complete_generation()
        self.page.goto(self.url + '/gallery')
        self.page.evaluate('sessionStorage.clear()')
        self.page.goto(self.url + '/?restore=' + job)
        self.page.wait_for_function('workspaceReady && !document.getElementById("submit").disabled && !location.search')
        self.assertEqual(self.page.locator('[name=instruction]').input_value(), '公園のベンチ')
        self.assertIn('履歴の設定を復元しました', self.page.locator('#restored-note').inner_text())
        self.assertEqual(self.page.locator('#generated-images img').count(), 1)
        for width in (1440, 1024, 768, 390):
            with self.subTest(width=width):
                self.page.set_viewport_size(dict(width=width, height=1000))
                self.page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 2)
                button = self.page.locator('#submit').bounding_box()
                self.assertGreaterEqual(button['x'], 0)
                self.assertLessEqual(button['x'] + button['width'], width + 1)
        self.page.set_viewport_size(dict(width=1440, height=1000))
        self.page.evaluate('document.documentElement.style.fontSize="200%"')
        self.page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        offset = self.page.evaluate('parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--runbar-offset"))')
        bar = self.page.locator('.floating-runbar').bounding_box()
        self.assertGreaterEqual(offset, bar['y'] + bar['height'])
        self.assertEqual(self.errors, [])

    def test_setting_tooltips_hover_keyboard_and_click_without_changing_settings(self):
        self.open_generation()
        self.assertEqual(self.page.locator('details.setting-help, .setting-brief').count(), 0)
        self.assertEqual(self.page.locator('.help-trigger').count(), 34)
        self.assertEqual(self.page.locator('.setting-tooltip:visible').count(), 0)
        self.assertEqual(self.page.locator('label .help-trigger').count(), 0)
        trigger = self.page.locator('[data-tooltip="help-threshold"]')
        tip = self.page.locator('#help-threshold')
        trigger.hover()
        self.page.wait_for_function('!document.getElementById("help-threshold").hidden')
        self.assertIn('低くするとタグが増え', tip.inner_text())
        tip.hover()
        self.page.wait_for_timeout(220)
        self.assertTrue(tip.is_visible())
        self.page.mouse.move(1, 1)
        self.page.wait_for_function('document.getElementById("help-threshold").hidden')
        trigger.focus()
        self.assertTrue(tip.is_visible())
        trigger.press('Escape')
        self.assertTrue(tip.is_hidden())
        trigger.press('Tab')
        self.assertTrue(tip.is_hidden())
        trigger.click()
        self.assertTrue(tip.is_visible())
        self.page.mouse.move(1, 1)
        self.page.wait_for_timeout(220)
        self.assertTrue(tip.is_visible())
        self.page.locator('[name=cfg]').click()
        self.assertTrue(tip.is_hidden())
        quality = self.page.locator('#quality-tags')
        was_checked = quality.is_checked()
        self.page.locator('[data-tooltip="help-use_quality_tags"]').click()
        self.assertEqual(quality.is_checked(), was_checked)
        self.assertEqual(self.posts, [])
        self.page.keyboard.press('Escape')
        # LoRA help is created after page initialization and uses the same behavior.
        lora = self.page.locator('[data-tooltip="help-lora-2-scope"]')
        lora.hover()
        self.assertTrue(self.page.locator('#help-lora-2-scope').is_visible())
        self.page.mouse.move(1, 1)
        self.page.wait_for_function('document.getElementById("help-lora-2-scope").hidden')
        self.assertEqual(self.errors, [])

    def test_setting_tooltips_fit_small_viewport_and_support_touch(self):
        context = self.browser.new_context(viewport=dict(width=390, height=844), has_touch=True, is_mobile=True)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            page.goto(self.url)
            page.wait_for_function('workspaceReady && !document.getElementById("submit").disabled')
            trigger = page.locator('[data-tooltip="help-lora-2-scope"]')
            trigger.tap()
            tip = page.locator('#help-lora-2-scope')
            self.assertTrue(tip.is_visible())
            box = tip.bounding_box()
            self.assertGreaterEqual(box['x'], 11)
            self.assertLessEqual(box['x'] + box['width'], 379)
            self.assertGreaterEqual(box['y'], 11)
            self.assertLessEqual(box['y'] + box['height'], 833)
            trigger.tap()
            self.assertTrue(tip.is_hidden())
            # Help remains reachable for disabled controls such as WD threshold.
            trigger = page.locator('[data-tooltip="help-threshold"]')
            self.assertTrue(page.locator('[name=threshold]').is_disabled())
            trigger.tap()
            self.assertTrue(page.locator('#help-threshold').is_visible())
            page.locator('h1').tap()
            self.assertTrue(page.locator('#help-threshold').is_hidden())
            self.assertEqual(errors, [])
        finally:
            context.close()

    def test_lora_manager_uses_available_width_and_restores_generation_spacing(self):
        uploaded = self.app.test_client().post('/api/lora-samples',
            data=dict(name='sdxl/sample.safetensors',
                      images=[(io.BytesIO(self.png), 'sample-'+str(index)+'.png') for index in range(6)]),
            headers={'X-Requested-With': 'LLMPC'})
        self.assertEqual(uploaded.status_code, 201)
        self.open_generation()
        self.page.locator('#open-lora-manager').click()
        self.page.wait_for_function('!document.getElementById("lora-manager").hidden && document.querySelectorAll("#managed-samples .lora-sample-preview").length===6')
        self.assertFalse(self.page.evaluate('document.body.classList.contains("generation-page")'))
        for width in (1920, 1440, 1280, 1024, 768, 390):
            with self.subTest(width=width):
                self.page.set_viewport_size(dict(width=width, height=1000))
                self.page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                card = self.page.locator('#lora-manager').bounding_box()
                metrics = self.page.locator('main').evaluate('(node)=>({width:node.getBoundingClientRect().width,left:parseFloat(getComputedStyle(node).paddingLeft),right:parseFloat(getComputedStyle(node).paddingRight)})')
                self.assertAlmostEqual(card['width'], metrics['width']-metrics['left']-metrics['right'], delta=2)
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width+2)
                if width >= 1280:
                    tree = self.page.locator('.managed-tree-panel').bounding_box()
                    form = self.page.locator('#lora-manager-form').bounding_box()
                    samples = self.page.locator('.lora-sample-section').bounding_box()
                    self.assertLess(tree['x'], form['x'])
                    self.assertLess(form['x'], samples['x'])
                    self.assertAlmostEqual(form['y'], samples['y'], delta=2)
                    self.assertGreaterEqual(self.page.locator('.lora-sample-preview').first.bounding_box()['width'], 180)
                if width == 1920:
                    self.assertGreater(card['width'], 1400)
        self.page.set_viewport_size(dict(width=1440, height=1000))
        self.page.goto(self.url + '/loras')
        self.page.wait_for_function('!document.getElementById("lora-manager").hidden && !document.getElementById("refresh-managed-loras").disabled')
        self.assertFalse(self.page.evaluate('document.body.classList.contains("generation-page")'))
        self.assertEqual(self.page.locator('#managed-samples .lora-sample-preview').count(), 6)
        self.page.locator('#close-lora-manager').click()
        self.assertTrue(self.page.locator('#workspace').is_visible())
        self.assertTrue(self.page.evaluate('document.body.classList.contains("generation-page")'))
        self.assertEqual(self.errors, [])

    def test_progress_is_only_in_floating_controls_and_results_stay_compact(self):
        sampling_started, finish_sampling = threading.Event(), threading.Event()
        self.addCleanup(finish_sampling.set)
        def sampling(url, graph, workflow, submitted, on_status, **kwargs):
            submitted('synthetic-prompt')
            kwargs['on_progress'](dict(stage='generate', detail='sampling', current=12, total=28))
            sampling_started.set()
            if not finish_sampling.wait(15):
                raise AssertionError('sampler was not released')
            return [dict(filename='synthetic.png')]
        with patch('comfyui_wrapper.integrations.comfy_client.execute', side_effect=sampling):
            self.open_generation()
            self.assertLess(self.page.locator('#generation-results').bounding_box()['height'], 200)
            self.assertEqual(self.page.locator('#generation-results .job-progress, #run-progress-summary').count(), 0)
            self.assertEqual(self.page.locator('.floating-runbar #job-progress').count(), 1)
            self.assertTrue(self.page.locator('#status').is_hidden())
            self.page.locator('[name=instruction]').fill('公園で話している二人')
            self.page.locator('#submit').click()
            self.assertTrue(sampling_started.wait(3))
            self.page.wait_for_function('document.getElementById("progress-bar").value===12')
            self.assertEqual(self.page.locator('.floating-runbar progress:visible').count(), 1)
            self.assertEqual(self.page.locator('#progress-bar').get_attribute('max'), '28')
            self.assertIn('12 / 28', self.page.locator('#progress-label').inner_text())
            self.assertIn('画像生成', self.page.locator('#progress-state').inner_text())
            self.assertIn('経過', self.page.locator('#progress-elapsed').inner_text())
            self.assertTrue(self.page.locator('#status').is_hidden())
            self.assertTrue(self.page.locator('#empty').is_visible())
            self.assertTrue(self.page.locator('#cancel-job').is_visible())
            self.page.set_viewport_size(dict(width=390, height=844))
            self.page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 392)
            bar = self.page.locator('.floating-runbar').bounding_box()
            self.assertGreaterEqual(bar['x'], 0)
            self.assertLessEqual(bar['x']+bar['width'], 391)
            finish_sampling.set()
            self.page.wait_for_function('!document.getElementById("submit").disabled && document.querySelector("#generated-images img")')
        self.assertEqual(self.page.locator('.result-jump').inner_text(), '結果を見る')
        self.assertEqual(self.page.locator('#progress-state').inner_text(), '完了')
        self.assertTrue(self.page.locator('#progress-stages').is_hidden())
        self.assertTrue(self.page.locator('#progress-bar').is_hidden())
        self.assertLess(self.page.locator('.floating-runbar').bounding_box()['height'],bar['height'])
        self.assertTrue(self.page.locator('.execution-mode').first.is_hidden())
        self.page.locator('#expand-run-modes').click()
        self.assertTrue(self.page.locator('.execution-mode').first.is_visible())
        self.page.locator('#expand-run-modes').click()
        self.assertTrue(self.page.locator('#result').is_visible())
        self.assertTrue(self.page.locator('#status').is_hidden())
        self.assertEqual(self.errors, [])

    def test_batch_progress_replaces_single_progress_in_floating_controls(self):
        self.complete_generation()
        batch_id = 'f'*32
        state = dict(active_batch=batch_id)
        batch = dict(state='running', current=2, count=3, completed=1,
                     created_at='2026-10-26T00:00:00+00:00', message='連続生成中',
                     active_job=dict(progress=dict(stage='generate', detail='sampling')))
        self.page.route('**/api/generation-state', lambda route: route.fulfill(json=state))
        self.page.route('**/api/batches/'+batch_id, lambda route: route.fulfill(json=batch))
        self.page.evaluate('generationGate.refresh()')
        self.assertTrue(self.page.locator('#job-progress').is_hidden())
        self.assertTrue(self.page.locator('#batch-progress-summary').is_visible())
        self.assertEqual(self.page.locator('.floating-runbar progress:visible').count(), 1)
        self.assertIn('2 / 3回目', self.page.locator('[data-batch-stage]').inner_text())
        self.assertEqual(self.page.locator('[data-batch-progress]').get_attribute('value'), '1')
        self.assertTrue(self.page.locator('.result-jump').is_hidden())
        state['active_batch'] = None
        batch.update(state='review', completed=3, active_job=None)
        self.page.evaluate('generationGate.refresh()')
        self.assertTrue(self.page.locator('#job-progress').is_hidden())
        self.assertIn('選別待ち', self.page.locator('[data-batch-stage]').inner_text())
        self.assertTrue(self.page.locator('[data-batch-stop]').is_hidden())
        self.assertEqual(self.page.locator('[data-batch-review]').get_attribute('href'), '/batch/'+batch_id)
        self.page.locator('#submit').click()
        self.page.wait_for_function('!document.getElementById("submit").disabled && !document.getElementById("job-progress").hidden')
        self.assertTrue(self.page.locator('#batch-progress-summary').is_hidden())
        self.assertEqual(self.page.locator('#progress-state').inner_text(), '完了')
        self.assertEqual(self.errors, [])

    def save_gallery_examples(self, count=6, batch_id=None):
        services = self.app.extensions['app_services']
        jobs = []
        for index in range(count):
            job = ('b' if batch_id else 'a') + format(index, '031x')
            folder = self.root/job
            folder.mkdir(exist_ok=True)
            (folder/'image_0.png').write_bytes(self.png)
            record = dict(created_at='2026-10-26T00:'+str(index).zfill(2)+':00+00:00',
                state='done', artifacts_ready=True, images=['image_0.png'],
                output_files=[dict(webui_filename='image_0.png',comfy_filename='output_'+str(index)+'.png')],
                settings=dict(checkpoint='AnimagineXL_v31.safetensors',target='animagine',profile='animagine31',
                    seed=index,width=512,height=512,instruction='公園',input_image=None,loras=[]),
                generation_settings=dict(steps=28,cfg=7),result=dict(positive='park',negative='text',summary_ja='公園'))
            if batch_id:
                record.update(batch_id=batch_id,temporary=True,batch_index=index+1)
            services.history.save(job,record)
            jobs.append(job)
        return jobs

    def test_gallery_can_compare_five_images_and_reject_sixth(self):
        self.save_gallery_examples()
        self.page.goto(self.url+'/gallery')
        self.page.wait_for_function('document.querySelectorAll(".gallery-select input").length===6')
        choices = self.page.locator('.gallery-select input')
        choices.nth(0).check()
        self.assertTrue(self.page.locator('#open-comparison').is_disabled())
        for index in range(1,5):
            choices.nth(index).check()
        self.assertTrue(choices.nth(5).is_disabled())
        self.assertIn('5 / 5枚',self.page.locator('#compare-count').inner_text())
        self.page.locator('#open-comparison').click()
        self.page.wait_for_function('document.querySelectorAll("#comparison-table thead th").length===6')
        self.assertEqual(self.page.locator('#comparison-table thead img').count(),5)
        self.assertGreaterEqual(self.page.locator('#comparison-table').bounding_box()['width'],1270)
        self.page.set_viewport_size(dict(width=390,height=844))
        scroll = self.page.locator('.comparison-scroll').evaluate('(node)=>({client:node.clientWidth,scroll:node.scrollWidth})')
        self.assertGreater(scroll['scroll'],scroll['client'])
        self.page.locator('#close-comparison').click()
        choices.nth(0).uncheck()
        self.assertFalse(choices.nth(5).is_disabled())
        choices.nth(5).check()
        self.assertIn('5 / 5枚',self.page.locator('#compare-count').inner_text())
        self.assertEqual(self.errors,[])

    def test_batch_catalog_is_a_folder_and_review_progress_stays_top_right(self):
        services = self.app.extensions['app_services']
        batch_id = 'c'*32
        jobs = self.save_gallery_examples(3,batch_id)
        current = 'd'*32
        services.history.save(current,dict(created_at='2026-10-26T00:04:00+00:00',state='running',
            progress=dict(stage='generate',current=12,total=28,detail='sampling'),temporary=True,batch_id=batch_id))
        batch = dict(state='running',created_at='2026-10-26T00:00:00+00:00',count=4,completed=3,current=4,
            current_job=current,job_ids=jobs+[current],checkpoint='AnimagineXL_v31.safetensors',
            plan=dict(ranges=[dict(field='strength_model',lora=0,start=.3,end=.9)]),message='連続生成中')
        services.batches.save(batch_id,batch)
        self.page.goto(self.url+'/batches')
        folder = self.page.locator('.batch-folder')
        self.assertEqual(folder.count(),1)
        self.assertIn('生成セット',folder.inner_text())
        self.assertEqual(folder.locator('.batch-preview img').count(),3)
        self.assertEqual(folder.locator('.gallery-card').count(),0)
        folder.locator('input[name=name]').fill('LoRA強度の比較')
        folder.get_by_role('button',name='名前を保存').click()
        self.page.wait_for_function('document.querySelector("[data-batch-name]").textContent==="LoRA強度の比較"')
        self.page.reload()
        self.assertEqual(self.page.locator('[data-batch-name]').inner_text(),'LoRA強度の比較')
        folder.locator('a.download').click()
        self.page.wait_for_url(self.url+'/batch/'+batch_id)
        self.page.wait_for_function('document.querySelector("[data-batch-stage]").textContent.includes("4 / 4回目")')
        self.assertEqual(self.page.locator('.floating-runbar #batch-status').count(),1)
        self.assertEqual(self.page.locator('.batch-review #batch-status').count(),0)
        self.assertIn('12 / 28',self.page.locator('[data-batch-steps]').inner_text())
        self.assertEqual(self.page.locator('[data-batch-progress]').get_attribute('value'),'3')
        before = self.page.locator('#batch-progress').bounding_box()
        self.page.evaluate('window.scrollTo(0,800)')
        after = self.page.locator('#batch-progress').bounding_box()
        self.assertAlmostEqual(before['y'],after['y'],delta=1)
        self.page.set_viewport_size(dict(width=390,height=844))
        self.page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        box = self.page.locator('#batch-progress').bounding_box()
        self.assertGreaterEqual(box['x'],0)
        self.assertLessEqual(box['x']+box['width'],391)
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),392)
        choices = self.page.locator('.gallery-select input')
        choices.nth(0).check()
        choices.nth(1).check()
        self.page.evaluate('window.scrollTo(0,900)')
        progress_box = self.page.locator('#batch-progress').bounding_box()
        toolbar_box = self.page.locator('.gallery-selection-toolbar').bounding_box()
        self.assertGreaterEqual(toolbar_box['y'],progress_box['y']+progress_box['height'])
        self.page.locator('#open-comparison').click()
        self.page.wait_for_function('document.getElementById("comparison-viewer").open')
        self.page.locator('#close-comparison').click()
        batch.update(state='review',completed=4,finished_at='2026-10-26T00:05:00+00:00')
        services.batches.save(batch_id,batch)
        services.history.save(current,dict(created_at='2026-10-26T00:04:00+00:00',state='done'))
        self.page.wait_for_function('document.getElementById("batch-stop").hidden && !document.getElementById("batch-finalize").disabled')
        self.assertIn('選別待ち',self.page.locator('[data-batch-stage]').inner_text())
        self.assertTrue(self.page.locator('[data-batch-progress]').is_hidden())
        self.assertLess(self.page.locator('#batch-progress').bounding_box()['height'],before['height'])
        self.page.locator('.gallery-keep input').first.check()
        self.assertIn('保存 1枚・削除 2枚',self.page.locator('#batch-finalize').inner_text())
        self.page.locator('#batch-finalize').click()
        self.assertIn('保存 1枚・削除 2枚',self.page.locator('#batch-confirm-save').inner_text())
        self.page.locator('#batch-confirm-cancel').click()
        self.page.locator('.gallery-keep input').first.uncheck()
        self.assertIn('すべて破棄',self.page.locator('#batch-finalize').inner_text())
        self.assertEqual(self.errors,[])

    def test_delete_highlights_all_outputs_of_same_run(self):
        jobs=self.save_gallery_examples(2)
        services=self.app.extensions['app_services']
        record=services.history.get(jobs[0])
        record['images'].append('second.png')
        (self.root/jobs[0]/'second.png').write_bytes((self.root/jobs[0]/'image_0.png').read_bytes())
        services.history.save(jobs[0],record)
        self.page.goto(self.url+'/gallery')
        self.page.wait_for_selector('.gallery-delete-select input')
        group=self.page.locator('.gallery-card[data-job-id="'+jobs[0]+'"]')
        group.first.locator('.gallery-delete-select input').check()
        self.assertEqual(self.page.locator('.delete-chosen').count(),2)
        group.first.locator('.gallery-delete-select input').uncheck()
        self.assertEqual(self.page.locator('.delete-chosen').count(),0)
        group.first.locator('.gallery-delete').click()
        self.assertEqual(self.page.locator('.delete-preview').count(),2)
        self.assertIn('画像2枚',self.page.locator('#delete-gallery-description').inner_text())
        self.page.locator('#cancel-gallery-delete').click()
        self.page.wait_for_function('document.querySelectorAll(".delete-preview").length===0')
        self.assertEqual(self.errors,[])

    def test_context_help_changes_with_references(self):
        self.open_generation()
        self.assertIn('画像なし',self.page.locator('#generation-context-hint').inner_text())
        self.assertTrue(self.page.locator('#wd-conflict-hint').is_hidden())
        self.page.locator('#image').set_input_files(dict(name='reference.png',mimeType='image/png',buffer=self.png))
        self.assertIn('参考画像 1枚',self.page.locator('#generation-context-hint').inner_text())
        self.assertIn('Ollama',self.page.locator('#generation-context-hint').inner_text())
        self.assertTrue(self.page.locator('#person-lora-hint').is_hidden())
        self.assertEqual(self.errors,[])

    def test_random_batch_seed_option_and_draft_restore(self):
        self.open_generation()
        self.page.locator('[name=instruction]').fill('a park bench')
        self.page.locator('#batch-mode').check()
        self.page.locator('#batch-seed-mode').select_option('random')
        self.page.locator('#batch-count').fill('2')
        self.page.wait_for_timeout(600)
        self.page.reload()
        self.page.wait_for_function('document.querySelector("#batch-seed-mode").value==="random"')
        with self.page.expect_request(lambda r: '/api/jobs' in r.url and r.method=='POST') as sent:
            self.page.locator('#submit').click()
        self.assertIn('"seed_mode":"random"',sent.value.post_data)
        self.page.wait_for_url('**/batch/*')
        self.page.wait_for_function('document.querySelectorAll(".gallery-card").length===2')
        self.assertEqual(self.errors,[])

    def test_matrix_generation_inputs_and_review_grid(self):
        self.open_generation()
        self.page.locator('[name=instruction]').fill('a park bench')
        self.page.locator('#batch-mode').check()
        self.page.locator('#batch-layout').select_option('matrix')
        for key in ['cfg','steps']:
            self.page.locator('#batch-vary-'+key).check()
            self.page.locator('#batch-'+key+'-points').fill('2')
        self.assertEqual(self.page.locator('#batch-count').input_value(),'4')
        self.page.locator('#submit').click()
        self.page.wait_for_url('**/batch/*')
        self.page.wait_for_function('document.querySelectorAll(".matrix-gallery .gallery-card").length===4')
        self.assertEqual(self.page.locator('[data-matrix-cell]').count(),4)
        self.assertIn('CFG = 4 ／ Steps = 20',self.page.locator('.matrix-cell-heading').all_text_contents())
        cells=self.page.locator('[data-matrix-cell]').evaluate_all('(nodes)=>nodes.map(n=>({order:n.style.order,x:n.getBoundingClientRect().x,y:n.getBoundingClientRect().y}))')
        ordered=sorted(cells,key=lambda v:int(v['order']))
        self.assertAlmostEqual(ordered[0]['y'],ordered[1]['y'],delta=1)
        self.assertGreater(ordered[2]['y'],ordered[0]['y'])
        self.page.set_viewport_size(dict(width=390,height=844))
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),392)
        sizes=self.page.locator('.matrix-gallery').evaluate('(n)=>({width:n.clientWidth,scroll:n.scrollWidth})')
        self.assertGreater(sizes['scroll'],sizes['width'])
        self.assertEqual(self.errors,[])

    def test_gallery_notes_labels_and_server_search(self):
        self.save_gallery_examples(3)
        self.page.goto(self.url+'/gallery')
        self.page.wait_for_selector('.gallery-card')
        self.page.get_by_role('button',name='メモ・分類',exact=True).first.click()
        self.page.locator('#annotation-note').fill('服装が良い・採用候補')
        self.page.locator('#annotation-labels').fill('衣装, 候補')
        self.page.locator('#annotation-save').click()
        self.page.wait_for_function('!document.getElementById("annotation-dialog").open')
        self.assertIn('採用候補',self.page.locator('.image-note').inner_text())
        self.page.locator('#gallery-search [name=label]').fill('衣装')
        self.page.locator('#gallery-search button[type=submit]').click()
        self.page.wait_for_function('document.querySelectorAll(".gallery-card").length===1')
        self.page.reload()
        self.page.wait_for_selector('.image-note')
        self.assertEqual(self.page.locator('#gallery-search [name=label]').input_value(),'衣装')
        self.assertIn('採用候補',self.page.locator('.image-note').inner_text())
        self.page.locator('#clear-gallery-search').click()
        self.page.wait_for_function('document.querySelectorAll(".gallery-card").length===3')
        self.page.locator('#gallery-search [name=q]').fill('該当しない検索')
        self.page.locator('#gallery-search button[type=submit]').click()
        self.page.wait_for_function('!galleryBusy && document.querySelectorAll(".gallery-card").length===0')
        self.assertEqual(self.errors,[])

    def test_model_and_lora_recommendations_are_explicit(self):
        self.open_generation()
        self.page.locator('[name=cfg]').fill('7')
        self.page.locator('[name=steps]').fill('34')
        self.page.locator('[name=additional_negative]').fill('watermark')
        self.page.locator('#save-model-recommendation').click()
        self.page.wait_for_function('!document.getElementById("apply-model-recommendation").disabled')
        self.page.locator('[name=cfg]').fill('3')
        self.assertEqual(self.page.locator('[name=cfg]').input_value(),'3')
        self.page.locator('#apply-model-recommendation').click()
        self.assertEqual(self.page.locator('[name=cfg]').input_value(),'7')
        self.assertEqual(self.page.locator('[name=steps]').input_value(),'34')
        self.page.locator('#open-lora-manager').click()
        self.page.wait_for_function('!document.getElementById("save-lora-recommendation").disabled')
        self.page.locator('#recommended-model').fill('0.55')
        self.page.locator('#recommended-clip').fill('0.45')
        self.page.locator('#save-lora-recommendation').click()
        self.page.wait_for_function('document.getElementById("lora-recommendation-status").textContent.includes("保存済み")')
        self.page.locator('#close-lora-manager').click()
        self.page.locator('#lora-0').select_option('sdxl/sample.safetensors')
        self.page.locator('#apply-lora-recommendation-0').wait_for(state='visible')
        self.assertEqual(self.page.locator('#lora-0-model').input_value(),'0.7')
        self.page.locator('#apply-lora-recommendation-0').click()
        self.assertEqual(self.page.locator('#lora-0-model').input_value(),'0.55')
        self.assertEqual(self.page.locator('#lora-0-clip').input_value(),'0.45')
        self.page.reload()
        self.page.wait_for_function('workspaceReady')
        self.assertEqual(self.page.locator('#lora-0-model').input_value(),'0.55')
        self.page.locator('#delete-model-recommendation').click()
        self.page.wait_for_function('document.getElementById("apply-model-recommendation").disabled')
        self.assertEqual(self.page.locator('[name=cfg]').input_value(),'7')
        self.assertEqual(self.errors,[])

    def test_analysis_model_can_be_edited_in_system_settings(self):
        import json
        from comfyui_wrapper.settings.app_config import DEFAULTS
        from comfyui_wrapper.settings.config_editor import ConfigEditor
        path=self.root/'synthetic-settings.json';path.write_text(json.dumps(DEFAULTS),encoding='utf-8')
        self.app.extensions['config_editor']=ConfigEditor(path)
        self.page.goto(self.url+'/system')
        self.page.locator('#tab-settings').click()
        model=self.page.locator('#app-settings-form [name=model]')
        model.wait_for(state='visible');self.assertTrue(model.is_enabled())
        model.fill('gemma3:4b')
        self.page.locator('#app-settings-review').click()
        self.page.wait_for_function('document.getElementById("app-settings-dialog").open')
        self.assertIn('gemma3:4b',self.page.locator('#app-settings-diff').inner_text())
        self.page.locator('#app-settings-save').click()
        self.page.wait_for_function('document.getElementById("app-settings-status").textContent.includes("保存しました")')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['model'],'gemma3:4b')
        self.assertEqual(self.app.extensions['app_services'].runtime.analysis_model,'qwen3-vl:8b-instruct')
        # Reloading the page reads saved settings without applying them to the running service.
        self.page.reload();self.page.locator('#tab-settings').click()
        self.page.wait_for_function('document.querySelector("#app-settings-form [name=model]")?.value==="gemma3:4b"')
        self.assertEqual(self.errors,[])

    def test_gallery_retention_can_be_saved_without_changing_running_policy(self):
        import json
        from comfyui_wrapper.settings.app_config import DEFAULTS
        from comfyui_wrapper.settings.config_editor import ConfigEditor
        path=self.root/'synthetic-retention.json';path.write_text(json.dumps(DEFAULTS),encoding='utf-8')
        self.app.extensions['config_editor']=ConfigEditor(path)
        self.page.goto(self.url+'/system');self.page.locator('#tab-settings').click()
        field=self.page.locator('#app-settings-form [name=gallery_retention_days]')
        field.wait_for(state='attached')
        field.evaluate('(node)=>{for(let parent=node.parentElement;parent;parent=parent.parentElement)if(parent.tagName==="DETAILS")parent.open=true;}')
        self.assertEqual(field.input_value(),'10')
        self.assertEqual(field.get_attribute('min'),'0')
        field.fill('0')
        self.page.locator('#app-settings-review').click()
        self.page.wait_for_function('document.getElementById("app-settings-dialog").open')
        self.assertIn('ギャラリー保持日数',self.page.locator('#app-settings-diff').inner_text())
        self.page.locator('#app-settings-save').click()
        self.page.wait_for_function('document.getElementById("app-settings-status").textContent.includes("保存しました")')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['gallery_retention_days'],0)
        self.assertEqual(self.app.extensions['gallery_cleanup'].retention_days,10)
        self.page.goto(self.url+'/gallery')
        self.assertIn('10日',self.page.locator('main').inner_text())
        self.assertEqual(self.errors,[])

    def test_named_instruction_save_load_update_delete_without_generation(self):
        self.open_generation()
        self.page.locator('[name=cfg]').fill('6.5')
        self.page.locator('#field-instruction').fill('公園で並んで座る。')
        self.page.locator('#instruction-name').fill('ベンチの二人')
        self.page.locator('#save-instruction').click()
        self.page.wait_for_function('document.getElementById("instruction-save-status").textContent.includes("保存しました")')
        key=self.page.locator('#saved-instruction').input_value()
        self.page.locator('#field-instruction').fill('編集中の別の指示')
        self.page.once('dialog',lambda dialog:dialog.dismiss())
        self.page.locator('#load-instruction').click()
        self.assertEqual(self.page.locator('#field-instruction').input_value(),'編集中の別の指示')
        self.page.once('dialog',lambda dialog:dialog.accept())
        self.page.locator('#load-instruction').click()
        self.assertEqual(self.page.locator('#field-instruction').input_value(),'公園で並んで座る。')
        self.assertEqual(self.page.locator('[name=cfg]').input_value(),'6.5')
        self.page.reload();self.page.wait_for_function('workspaceReady')
        self.page.locator('#saved-instruction').select_option(key)
        self.page.locator('#field-instruction').fill('夜の公園で話す。')
        self.page.locator('#instruction-name').fill('夜のベンチ')
        self.page.locator('#update-instruction').evaluate('(n)=>n.closest("details").open=true')
        self.page.once('dialog',lambda dialog:dialog.accept())
        self.page.locator('#update-instruction').click()
        self.page.wait_for_function('document.querySelector("#saved-instruction option:checked").textContent==="夜のベンチ"')
        self.page.once('dialog',lambda dialog:dialog.accept())
        self.page.locator('#delete-instruction').click()
        self.page.wait_for_function('document.querySelectorAll("#saved-instruction option").length===1')
        self.assertEqual(self.page.locator('#field-instruction').input_value(),'夜の公園で話す。')
        self.assertEqual(self.posts,[])
        self.assertEqual(self.errors,[])

    def test_selected_lora_notes_are_visible_and_refresh_without_prompt_changes(self):
        store=self.app.extensions['app_services'].lora_store
        note='推奨：屋外で使用。\n<img src=x onerror=alert(1)> はメモの文字列。'
        store.save('sdxl/sample.safetensors','sample_trigger','',note)
        self.open_generation()
        self.assertTrue(self.page.locator('#lora-0-note-box').is_hidden())
        self.page.locator('#lora-0').select_option('sdxl/sample.safetensors')
        self.page.wait_for_function('document.getElementById("lora-0-note").textContent.includes("推奨")')
        self.assertEqual(self.page.locator('#lora-0-note').inner_text(),note)
        self.assertEqual(self.page.locator('#lora-0-note img').count(),0)
        self.assertEqual(self.page.locator('#lora-0-trigger').input_value(),'sample_trigger')
        self.assertEqual(self.page.locator('[name=additional_positive]').input_value(),'')
        self.page.locator('#lora-1').select_option('sdxl/sample.safetensors')
        self.assertEqual(self.page.locator('#lora-1-note').inner_text(),note)
        self.page.locator('#open-lora-manager').click()
        self.page.wait_for_function('!document.getElementById("save-managed-lora").disabled')
        self.page.locator('#managed-note').fill('MODEL強度は0.6を目安にする。')
        self.page.locator('#managed-recommended-prompt').fill('soft light, <b>outdoor</b>')
        self.page.locator('#save-managed-lora').click()
        self.page.wait_for_function('document.getElementById("manager-status").textContent.includes("保存しました")')
        self.page.locator('#close-lora-manager').click()
        self.assertEqual(self.page.locator('#lora-0-note').inner_text(),'MODEL強度は0.6を目安にする。')
        self.assertEqual(self.page.locator('#lora-1-note').inner_text(),'MODEL強度は0.6を目安にする。')
        self.assertEqual(self.page.locator('#lora-0-recommended-prompt').inner_text(),'soft light, <b>outdoor</b>')
        self.assertEqual(self.page.locator('#lora-0-recommended-prompt b').count(),0)
        self.assertEqual(self.page.locator('[name=additional_positive]').input_value(),'')
        self.page.reload();self.page.wait_for_function('workspaceReady')
        self.assertEqual(self.page.locator('#lora-0-note').inner_text(),'MODEL強度は0.6を目安にする。')
        store.save('sdxl/sample.safetensors','sample_trigger','','')
        self.page.locator('#refresh-loras').click()
        self.page.wait_for_function('document.getElementById("lora-0-note").textContent.includes("未登録")')
        self.page.locator('#lora-0').select_option('')
        self.assertTrue(self.page.locator('#lora-0-note-box').is_hidden())
        self.assertEqual(self.posts,[])
        self.assertEqual(self.errors,[])

    def test_model_folder_bindings_can_be_managed_in_settings(self):
        import json
        from comfyui_wrapper.settings.app_config import DEFAULTS
        from comfyui_wrapper.settings.config_editor import ConfigEditor
        path=self.root/'synthetic-settings.json';path.write_text(json.dumps(DEFAULTS),encoding='utf-8');self.app.extensions['config_editor']=ConfigEditor(path)
        self.page.goto(self.url+'/system');self.page.locator('#tab-settings').click()
        self.page.locator('#add-lora-binding').click()
        row=self.page.locator('[data-lora-binding]').first
        row.locator('[data-binding-field=model]').fill('AnimagineXL_v31.safetensors')
        row.locator('[data-binding-field=folder]').fill('my-model/characters')
        self.page.locator('#add-lora-binding').click()
        row=self.page.locator('[data-lora-binding]').nth(1)
        row.locator('[data-binding-field=model]').fill('AnimagineXL_v31.safetensors')
        row.locator('[data-binding-field=folder]').fill('shared/styles')
        self.page.locator('#app-settings-review').click()
        self.page.wait_for_function('document.getElementById("app-settings-dialog").open')
        self.assertIn('my-model/characters',self.page.locator('#app-settings-diff').inner_text())
        self.page.locator('#app-settings-save').click()
        self.page.wait_for_function('document.getElementById("app-settings-status").textContent.includes("保存しました")')
        expected={'AnimagineXL_v31.safetensors':['my-model/characters','shared/styles']}
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['checkpoint_lora_folders'],expected)
        self.page.reload();self.page.locator('#tab-settings').click()
        self.page.wait_for_function('document.querySelectorAll("[data-lora-binding]").length===2')
        self.assertEqual(self.page.locator('[data-binding-field=folder]').first.input_value(),'my-model/characters')
        self.page.set_viewport_size(dict(width=390,height=844))
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),392)
        self.assertEqual(self.errors,[])

    def test_generation_filters_loras_by_explicit_folder_binding(self):
        from dataclasses import replace
        services=self.app.extensions['app_services']
        runtime=replace(services.runtime,checkpoint_lora_folders={'AnimagineXL_v31.safetensors':['my-model']})
        services.runtime=runtime;services.catalog.runtime=runtime;services.runner.runtime=runtime
        info=dict(LoraLoader=dict(input=dict(required=dict(lora_name=[['my-model/nested/a.safetensors','my-model2/wrong.safetensors','sdxl/sample.safetensors']]))),KSampler=dict(input=dict(required=dict(sampler_name=[['euler_ancestral']],scheduler=[['normal']]))))
        with patch('comfyui_wrapper.integrations.comfy_client.api',return_value=info):
            self.open_generation()
            self.assertEqual(self.page.locator('#lora-0 option').all_text_contents(),['使用しない','my-model/nested/a.safetensors'])
            self.page.locator('#lora-0').select_option('my-model/nested/a.safetensors')
            self.assertIn('モデル別フォルダー対応',self.page.locator('#lora-hint').inner_text())
            self.page.reload();self.page.wait_for_function('workspaceReady')
            self.assertEqual(self.page.locator('#lora-0').input_value(),'my-model/nested/a.safetensors')
            self.assertEqual(self.errors,[])

    def test_lora_management_tags_filter_tree_and_do_not_change_prompts(self):
        store=self.app.extensions['app_services'].lora_store
        store.save('sdxl/sample.safetensors','sample_trigger','','memo',tags=['人物','衣装'])
        store.save('sdxl/not-installed.safetensors','','','',tags=['一覧に出さない'])
        self.open_generation()
        self.page.locator('#open-lora-manager').click()
        self.page.wait_for_function('!document.getElementById("save-managed-lora").disabled')
        self.assertEqual(self.page.locator('#managed-tags').input_value(),'人物, 衣装')
        self.assertNotIn('一覧に出さない',self.page.locator('#managed-tag-filter').inner_text())
        self.page.locator('#managed-tag-filter').select_option('tag:人物')
        self.assertEqual(self.page.locator('.managed-tree-file').count(),1)
        self.page.locator('#managed-tag-filter').select_option('untagged:')
        self.assertEqual(self.page.locator('.managed-tree-file').count(),0)
        self.assertIn('絞り込み対象外',self.page.locator('#managed-filter-status').inner_text())
        self.assertEqual(self.page.locator('#managed-trigger').input_value(),'sample_trigger')
        self.page.locator('#managed-tags').fill('画風, 夜景')
        self.page.locator('#save-managed-lora').click()
        self.page.wait_for_function('document.getElementById("manager-status").textContent.includes("保存しました")')
        self.page.locator('#clear-managed-tag-filter').click()
        self.page.locator('#managed-tag-filter').select_option('tag:夜景')
        self.assertEqual(self.page.locator('.managed-tree-file').count(),1)
        self.page.locator('#close-lora-manager').click()
        self.page.locator('#lora-0').select_option('sdxl/sample.safetensors')
        self.assertEqual(self.page.locator('#lora-0-trigger').input_value(),'sample_trigger')
        self.assertNotIn('夜景',self.page.evaluate('JSON.stringify(loraValues())'))
        self.page.reload();self.page.wait_for_function('workspaceReady')
        self.page.locator('#open-lora-manager').click()
        self.page.wait_for_function('document.getElementById("managed-tags").value==="画風, 夜景"')
        self.assertEqual(self.posts,[]);self.assertEqual(self.errors,[])
