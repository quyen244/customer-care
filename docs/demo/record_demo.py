"""Record the end-to-end showcase video of the running stack (see README, section Demo video)."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import Page, sync_playwright

SLIDES = (Path(__file__).parent / "slides.html").resolve().as_uri()
MB, AF, N8N, MAIL, CRM = ("http://localhost:3000", "http://localhost:8088", "http://localhost:5680",
                          "http://localhost:8025", "http://localhost:8001")
W, H = 1920, 1080

OVERLAY_JS = """
(() => {
  const install = () => {
    if (document.getElementById('__demo_caption') || !document.body) return;
    const style = document.createElement('style');
    style.textContent = `
      #__demo_caption { position: fixed; left: 50%; bottom: 44px; transform: translateX(-50%);
        z-index: 2147483647; max-width: 1500px; padding: 18px 30px; border-radius: 16px;
        background: rgba(11,18,32,.92); color: #fff; font: 600 28px/1.35 Inter, "Segoe UI", sans-serif;
        box-shadow: 0 12px 40px rgba(0,0,0,.35); display: none; align-items: center; gap: 18px; }
      #__demo_caption .step { font-size: 20px; font-weight: 700; color: #0b1220; background: #4f8cff;
        padding: 6px 14px; border-radius: 999px; white-space: nowrap; }
      #__demo_cursor { position: fixed; z-index: 2147483647; width: 26px; height: 26px; margin: -13px 0 0 -13px;
        border-radius: 50%; background: rgba(79,140,255,.35); border: 3px solid #4f8cff; pointer-events: none;
        transition: transform .12s ease; left: -100px; top: -100px; }
      #__demo_cursor.down { transform: scale(.7); background: rgba(79,140,255,.7); }`;
    document.head.appendChild(style);
    const cap = document.createElement('div'); cap.id = '__demo_caption';
    cap.innerHTML = '<span class="step"></span><span class="text"></span>';
    const cur = document.createElement('div'); cur.id = '__demo_cursor';
    document.body.append(cap, cur);
    window.__caption = (step, text) => {
      cap.querySelector('.step').textContent = step; cap.querySelector('.text').textContent = text;
      cap.style.display = text ? 'flex' : 'none';
    };
    document.addEventListener('mousemove', (e) => { cur.style.left = e.clientX + 'px'; cur.style.top = e.clientY + 'px'; }, true);
    document.addEventListener('mousedown', () => cur.classList.add('down'), true);
    document.addEventListener('mouseup', () => cur.classList.remove('down'), true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install); else install();
  setInterval(install, 500);
})();
"""


class Demo:
    def __init__(self, page: Page):
        self.pg = page
        self.x, self.y = W // 2, H // 2

    def caption(self, step: str, text: str) -> None:
        for _ in range(20):
            if self.pg.evaluate("typeof window.__caption === 'function'"):
                self.pg.evaluate("([s, t]) => window.__caption(s, t)", [step, text])
                return
            self.pg.wait_for_timeout(100)

    def move(self, x: float, y: float, steps: int = 28) -> None:
        self.pg.mouse.move(x, y, steps=steps)
        self.x, self.y = x, y

    def click(self, locator, pause: int = 600) -> None:
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        self.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        self.pg.wait_for_timeout(250)
        self.pg.mouse.down(); self.pg.mouse.up()
        self.pg.wait_for_timeout(pause)

    def wheel(self, total: int, x: float = W * 0.6, y: float = H * 0.55, step: int = 60) -> None:
        self.move(x, y, steps=10)
        for _ in range(abs(total) // step):
            self.pg.mouse.wheel(0, step if total > 0 else -step)
            self.pg.wait_for_timeout(22)

    def hold(self, ms: int) -> None:
        self.pg.wait_for_timeout(ms)


METABASE_READY = """() => document.querySelectorAll('[data-testid=dashcard]').length > 0
    && document.querySelectorAll('[data-testid=loading-indicator]').length === 0
    && !document.body.innerText.includes('Loading...')"""


def wait_metabase(pg: Page, timeout_s: int = 90) -> None:
    """Block until cards have rendered and stayed rendered for 2s (queries start a beat after cards mount)."""
    deadline, stable = time.time() + timeout_s, 0
    while time.time() < deadline and stable < 4:
        stable = stable + 1 if pg.evaluate(METABASE_READY) else 0
        pg.wait_for_timeout(500)
    pg.wait_for_timeout(500)


def show_api_response(pg: Page, url: str, headers: dict) -> None:
    """Render the live API response as a readable request/response view (Chrome's raw JSON view is tiny)."""
    body = pg.request.get(url, headers=headers).json()
    pg.evaluate(
        """([url, json]) => {
            document.body.innerHTML = '';
            document.body.style.cssText = 'margin:0;background:#0b1220;color:#e8eefc;font:22px/1.5 Consolas,monospace;padding:48px 64px';
            const req = document.createElement('div');
            req.style.cssText = 'color:#37c47d;font-weight:700;margin-bottom:24px';
            req.textContent = 'GET ' + url + '    X-API-Key: ********';
            const pre = document.createElement('pre');
            pre.style.cssText = 'margin:0;white-space:pre-wrap;color:#cfe0ff';
            pre.textContent = JSON.stringify(json, null, 2);
            document.body.append(req, pre);
        }""", [url.replace(CRM, ""), body])


def show_run_graph(d: "Demo") -> None:
    pg = d.pg
    pg.get_by_role("button", name="Show Graph (Press g)").first.wait_for(state="visible", timeout=20000)
    for name in ("Show Graph (Press g)", "Expand all task groups", "Collapse Details Panel"):
        btn = pg.get_by_role("button", name=name)
        if btn.count() and btn.first.is_visible():
            d.click(btn.first, 1000)
    fit = pg.locator(".react-flow__controls-fitview")
    if fit.count():
        d.click(fit.first, 1200)


def login_state(browser, path: Path) -> None:
    ctx = browser.new_context(viewport={"width": W, "height": H})
    ctx.set_default_navigation_timeout(90000)
    pg = ctx.new_page()
    pg.goto(f"{MB}/auth/login", wait_until="domcontentloaded")
    pg.fill("input[name=username]", "admin@example.com"); pg.fill("input[name=password]", "Metabase-dev-1")
    pg.click("button[type=submit]"); pg.wait_for_url("**/dashboard/**", timeout=60000)
    for dash in pg.request.get(f"{MB}/api/dashboard/").json():  # warm Metabase caches off camera
        if dash["name"].startswith("Customer Care") and not dash.get("archived"):
            pg.goto(f"{MB}/dashboard/{dash['id']}", wait_until="domcontentloaded")
            wait_metabase(pg)
    pg.goto(f"{AF}/"); pg.wait_for_timeout(2000)
    if pg.locator("input[name=username]").count():
        pg.fill("input[name=username]", "admin"); pg.fill("input[name=password]", "admin")
        pg.keyboard.press("Enter"); pg.wait_for_timeout(3000)
    pg.goto(f"{N8N}/signin"); pg.wait_for_timeout(2500)
    if pg.locator("input[type=email]").count():
        pg.fill("input[type=email]", "admin@example.com"); pg.fill("input[type=password]", "N8n-demo-pw1")
        pg.keyboard.press("Enter"); pg.wait_for_timeout(3000)
    ctx.storage_state(path=str(path))
    ctx.close()


def dashboard_id(browser, state: Path, name: str) -> int:
    ctx = browser.new_context(storage_state=str(state))
    res = ctx.request.get(f"{MB}/api/dashboard/")
    ids = [d["id"] for d in res.json() if d["name"] == name and not d.get("archived")]
    ctx.close()
    return max(ids)


def run(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    state = out / "_state.json"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        login_state(browser, state)
        sla_id = dashboard_id(browser, state, "Customer Care - SLA Operations")
        dq_id = dashboard_id(browser, state, "Customer Care - Data Quality & Alerts")

        ctx = browser.new_context(viewport={"width": W, "height": H}, storage_state=str(state),
                                  record_video_dir=str(out), record_video_size={"width": W, "height": H},
                                  timezone_id="UTC", locale="en-US")
        ctx.set_default_navigation_timeout(90000)
        ctx.set_default_timeout(30000)
        ctx.add_init_script(OVERLAY_JS)
        pg = ctx.new_page()
        d = Demo(pg)
        t0 = time.time()
        marks = {}

        # 1. intro + architecture
        pg.goto(f"{SLIDES}#title"); d.hold(5500)
        marks["architecture"] = time.time() - t0
        pg.goto(f"{SLIDES}#arch"); d.hold(9000)

        # 2. source system: CRM API
        marks["sources"] = time.time() - t0
        api_url = f"{CRM}/api/v1/customers?updated_since=2026-09-01T00:00:00Z&page=1&page_size=1"
        pg.goto(f"{CRM}/health"); show_api_response(pg, api_url, {"X-API-Key": "local-dev-crm-key"})
        d.hold(500)
        d.caption("1 / 7  Sources", "Mock CRM REST API: API key, pagination and updated_since for incremental pulls")
        d.hold(5500)

        # 3. Airflow: trigger a real pipeline run
        marks["airflow"] = time.time() - t0
        pg.goto(f"{AF}/dags/customer_care_pipeline"); d.hold(2500)
        d.caption("2 / 7  Orchestration", "Airflow runs the pipeline hourly. Let's trigger a run right now")
        d.hold(2500)
        d.click(pg.get_by_role("button", name="Trigger Dag").first, 900)
        d.click(pg.locator("[role=dialog] button", has_text="Trigger").last, 1500)
        pg.wait_for_url("**/runs/**", timeout=30000)
        run_url = pg.url
        run_id = run_url.rsplit("/runs/", 1)[1]
        show_run_graph(d)
        d.caption("2 / 7  Orchestration", "Ingest 5 sources in parallel, data-quality gate, then dbt staging and marts, each gated by tests")
        d.hold(9000)

        # 4. data quality dashboard while the run progresses
        marks["data_quality"] = time.time() - t0
        pg.goto(f"{MB}/dashboard/{dq_id}"); wait_metabase(pg); d.hold(800)
        d.caption("3 / 7  Data quality", "Every bad row is quarantined with a reason: nulls, duplicates, bad timestamps, invalid status")
        d.move(420, 460); d.hold(4500)
        d.move(1300, 900)
        d.caption("3 / 7  Data quality", "Per-file audit trail: rows read, loaded, rejected and duplicated")
        d.hold(4500)

        # 5. SLA operations dashboard
        marks["dashboard"] = time.time() - t0
        pg.goto(f"{MB}/dashboard/{sla_id}"); wait_metabase(pg); d.hold(800)
        got_it = pg.get_by_role("button", name="Got it")
        if got_it.count():
            d.click(got_it.first, 400)
        toggle = pg.locator("[data-testid=sidebar-toggle]")
        if pg.locator("[data-testid=main-navbar-root]").first.is_visible() and toggle.count():
            d.click(toggle.first, 900)
        d.caption("4 / 7  SLA dashboard", "Live KPIs for Customer Care managers: volume, backlog, SLA compliance, response times, CSAT")
        d.move(700, 330); d.hold(2500); d.move(1300, 330); d.hold(3000)
        d.caption("4 / 7  SLA dashboard", "Trends expose Monday peaks, weekend dips and the days SLA fell below the 90% target")
        d.wheel(560); d.hold(4500)
        d.caption("4 / 7  SLA dashboard", "Breakdowns by category, priority and channel show where the team is failing")
        d.wheel(620); d.hold(4000)
        d.wheel(640); d.caption("4 / 7  SLA dashboard", "Agent productivity: resolved per active day, first response, SLA % and CSAT per agent")
        d.hold(4500)
        d.wheel(-1900); d.hold(900)
        d.caption("4 / 7  SLA dashboard", "Filters for date, category, channel, priority and agent. Let's look at urgent tickets only")
        d.click(pg.locator("[data-testid=parameter-widget]", has_text="Priority").first, 600)
        urgent = pg.get_by_text("Urgent", exact=True).last
        urgent.wait_for(state="visible", timeout=30000)
        d.click(urgent, 500)
        d.click(pg.get_by_role("button", name="Add filter").first, 800)
        wait_metabase(pg)
        d.move(1000, 330); d.hold(3500)

        # 6. back to Airflow: the same run, finished
        marks["airflow_done"] = time.time() - t0
        tok = ctx.request.post(f"{AF}/auth/token", data={"username": "admin", "password": "admin"}).json()["access_token"]
        state_ = None
        for _ in range(150):
            state_ = ctx.request.get(f"{AF}/api/v2/dags/customer_care_pipeline/dagRuns/{quote(run_id, safe='')}",
                                     headers={"Authorization": f"Bearer {tok}"}).json()["state"]
            if state_ in ("success", "failed"):
                break
            pg.wait_for_timeout(2000)
        if state_ != "success":
            raise RuntimeError(f"pipeline run {run_id} ended {state_}; not recording a false 'all green' scene")
        pg.wait_for_timeout(4000)  # let the UI's task states catch up with the API
        pg.goto(run_url); d.hold(1500)
        show_run_graph(d)
        d.caption("5 / 7  Orchestration", "The run finished: every task green, retries and failure alerts built in")
        d.hold(5000)

        # 7. n8n alert workflow + execution
        marks["n8n"] = time.time() - t0
        pg.goto(f"{N8N}/workflow/ccSlaAlerts0001"); d.hold(3500)
        d.caption("6 / 7  Alerting", "n8n checks SLA every 15 min and after each pipeline run: compliance, backlog, urgent breaches")
        d.move(460, 560); d.hold(2000); d.move(880, 560); d.hold(2000); d.move(1520, 560); d.hold(2000)
        d.click(pg.get_by_text("Executions", exact=True).first, 3000)
        d.caption("6 / 7  Alerting", "Our run just triggered it. With the demo target raised to 95%, compliance breached it, so it alerted")
        d.hold(4500)

        # 8. the email
        marks["email"] = time.time() - t0
        pg.goto(f"{MAIL}/"); d.hold(2500)
        d.caption("7 / 7  Alert email", "The Customer Care manager receives an actionable alert with the numbers behind it")
        d.hold(1500)
        d.click(pg.locator("a.message, .message").first, 3000)
        d.hold(5500)

        # 9. outro
        marks["outro"] = time.time() - t0
        pg.goto(f"{SLIDES}#outro"); d.hold(8000)

        video = Path(pg.video.path())
        ctx.close()
        browser.close()
    (out / "chapters.json").write_text(json.dumps({k: round(v, 1) for k, v in marks.items()}, indent=2))
    state.unlink(missing_ok=True)
    return video


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent / "raw"))
    print(run(Path(ap.parse_args().out)))
