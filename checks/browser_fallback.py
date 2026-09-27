"""Exercise the production v2 retry loop against a controlled browser fixture.

Run under Xvfb: python -m checks.browser_fallback
Add --live-openrouter to use the configured paid API for one synthetic grid.
This checks the integration, not real CAPTCHA solving accuracy.
"""
import argparse
import asyncio
import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from PIL import Image
from common.vision import LocalFirstClassifier, OpenRouterVision, VisionError
from recaptcha import solve


MAIN = """<!doctype html><textarea id="g-recaptcha-response"></textarea>
<iframe title="reCAPTCHA" src="/anchor" style="height:60px"></iframe>
<iframe id="challenge" title="recaptcha challenge" src="/bframe"
  style="display:none;width:400px;height:430px"></iframe>
<script>window.checks=0;window.verifies=0;</script>"""
ANCHOR = """<button id="recaptcha-anchor" onclick="
parent.checks++;if(parent.checks>1){
parent.document.querySelector('#challenge').style.display='none';
throw Error('Checkbox clicked again')}
if(parent.location.search==='?direct'){
this.className='recaptcha-checkbox-checked';
parent.document.querySelector('textarea').value='fixture-accepted';
}else{parent.document.querySelector('#challenge').style.display='block'}">Start</button>"""
GRID = """<style>table{border-collapse:collapse}td{width:100px;height:100px;
border:4px solid white;background:blue}td[data-i='0'],td[data-i='4'],td[data-i='8']
{background:red}.selected{outline:3px solid black;outline-offset:-5px}</style>
<div class="rc-imageselect-desc">Select all <strong>red squares</strong></div>
<table>""" + "".join("<tr>" + "".join(
    f'<td role="button" data-i="{r*3+c}" onclick="this.classList.toggle(\'selected\')"></td>'
    for c in range(3)) + "</tr>" for r in range(3)) + """</table>
<button id="recaptcha-verify-button" onclick="
parent.verifies++;
const indices=[...document.querySelectorAll('.selected')].map(e=>+e.dataset.i);
if(JSON.stringify(indices)==='[0,4,8]' && parent.checks===1){
parent.document.querySelector('textarea').value='fixture-accepted';
parent.document.querySelector('#challenge').style.display='none';
}else{document.querySelectorAll('.selected').forEach(e=>e.classList.remove('selected'))}
">Verify</button>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = ANCHOR if self.path == '/anchor' else GRID if self.path == '/bframe' else MAIN
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


class Local:
    def __init__(self, succeeds=False):
        self.calls = 0
        self.succeeds = succeeds

    def classify(self, image, target):
        self.calls += 1
        if not self.succeeds:
            return False
        tile = Image.open(io.BytesIO(base64.b64decode(image))).convert('RGB')
        r, g, b = tile.getpixel((tile.width//2, tile.height//2))
        return r > 200 and b < 50


class Remote:
    provider = 'openrouter-fixture'

    def __init__(self, live=False, fails=False):
        self.client = OpenRouterVision() if live else None
        self.calls = 0
        self.fails = fails

    def classify_grid(self, image, target, n):
        self.calls += 1
        if self.fails:
            raise VisionError('OpenRouter returned HTTP 429')
        return self.client.classify_grid(image, target, n) if self.client else [0, 4, 8]


async def run_case(base, name, local, remote, direct=False, expected=True):
    plan = LocalFirstClassifier(local, remote)
    with patch.object(solve, '_build_v2_page', return_value=MAIN), patch.object(solve, '_get_keypool', return_value=plan):
        result = await solve.solve_recaptcha_v2(
            'fixture-sitekey', base + '/test' + ('?direct' if direct else ''), max_attempts=2)
    accepted = result.get('token') == 'fixture-accepted'
    assert accepted == expected, (name, result.get('error'))
    assert local.calls == (0 if direct else 9), (name, local.calls)
    assert remote.calls == (0 if direct or local.succeeds else 1), (name, remote.calls)
    assert result.get('attempts', 2) == (1 if direct or local.succeeds else 2)
    print(json.dumps({'case': name, 'accepted': accepted, 'local_tile_calls': local.calls,
                      'remote_grid_calls': remote.calls, 'elapsed': result['elapsed']}), flush=True)


async def main(live):
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        await run_case(base, 'local-rejected-remote-accepted', Local(), Remote(live=live))
        await run_case(base, 'local-accepted-no-remote', Local(succeeds=True), Remote())
        await run_case(base, 'browser-cleared-no-classifier', Local(), Remote(), direct=True)
        await run_case(base, 'remote-error-bounded-failure', Local(), Remote(fails=True), expected=False)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live-openrouter', action='store_true')
    asyncio.run(main(parser.parse_args().live_openrouter))
