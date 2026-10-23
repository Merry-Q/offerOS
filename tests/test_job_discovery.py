"""Privacy, provenance, verification, scoring and owner-bound handoff contracts."""
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import PropertyMock, patch

_data = tempfile.TemporaryDirectory(prefix="offeros-discovery-tests-")
os.environ["OFFEROS_DATA_DIR"] = _data.name
os.environ["LLM_MODE"] = "mock"

from fastapi.testclient import TestClient
from server.main import app
from server.db import dumps, get_db, utc_now
from server.config import settings
from server.job_discovery import discover, linked_job_candidates, quick_score, source_candidates, verify_job
from server.llm import llm
from server.privacy import model_signals
from server.public_fetch import fetch_public_page, public_target
from server.resume_evidence import attach_resume_evidence
from server.agents.judge_agent import judge_match
from server.agents.action_agent import build_action_report

RAW = """张隐私 | 产品经理
邮箱：private@example.test
手机号：13800138000
教育经历
隐私大学，本科，2018—2022
工作经历
隐私软件公司，产品经理，2022.07—2025.06
负责需求分析与用户研究，使用 SQL。
项目经历
秘密门户
需求梳理与 SQL 数据分析。
专业技能
SQL、需求分析、用户研究
"""
PROFILE = attach_resume_evidence({}, RAW)
JD = ("岗位职责：产品经理负责用户研究、需求分析，使用 SQL 分析客户反馈，制定产品计划。"
      "任职要求：本科及以上学历，2年产品经验，能够完成需求分析，熟悉 SQL，要求 Python。") * 3


def page(**overrides):
    data = {"@context": "https://schema.org", "@type": "JobPosting", "title": "产品经理",
        "hiringOrganization": {"name": "测试招聘公司"}, "description": JD,
        "jobLocation": {"address": {"addressLocality": "上海"}}, "validThrough": "2099-12-31"}
    data.update(overrides)
    return '<html><script type="application/ld+json">' + json.dumps(data, ensure_ascii=False) + '</script><main>' + JD + '</main></html>'


def job():
    return {"id": "found_test", "company": "测试招聘公司", "title": "产品经理", "city": "上海", "recruitment_type": "未注明",
        "graduate_cohort": "未注明", "category": "产品经理", "jd_text": JD, "url": "https://jobs.example.test/123",
        "checked_at": utc_now(), "open_evidence": "测试期限", "source_host": "jobs.example.test"}


class PipelineTests(unittest.TestCase):
    def test_candidate_prompts_contain_only_fixed_tags(self):
        signals = model_signals(PROFILE)
        self.assertIn("SQL", signals["skills"])
        self.assertEqual(set(signals), {"roles", "skills", "degree", "experience_bucket"})
        bodies = []
        def post(body, timeout):
            bodies.append(body)
            return {"choices": [{"message": {"content": "{}"}}]}
        with patch.object(type(llm), "enabled", new_callable=PropertyMock, return_value=True), patch.object(llm, "_post_chat", side_effect=post):
            judge, _ = judge_match({"title": "产品经理", "must_haves": ["SQL"]}, PROFILE)
            build_action_report(judge, PROFILE, {"title": "产品经理", "must_haves": ["SQL"]})
        outgoing = json.dumps(bodies, ensure_ascii=False)
        for secret in ("张隐私", "private@example.test", "13800138000", "隐私大学", "隐私软件公司", "秘密门户", "2022.07", "resume_sections"):
            self.assertNotIn(secret, outgoing)
        self.assertEqual(len(bodies), 4)

    def test_search_uses_native_sources_and_scrubs_candidate(self):
        result = {"output": {"choices": [{"message": {"content": '{"jobs":[]}'}}], "search_info": {"search_results": [{"url": "https://example.test/job"}]}}}
        with patch.object(type(llm), "enabled", new_callable=PropertyMock, return_value=True), patch.object(llm, "_post", return_value=result) as post:
            data, _ = llm.search_jobs({"candidate": PROFILE})
        body = post.call_args.args[1]
        self.assertTrue(body["parameters"]["search_options"]["forced_search"])
        self.assertEqual(data["sources"][0]["url"], "https://example.test/job")
        self.assertNotIn("张隐私", str(body))
        self.assertNotIn("秘密门户", str(body))

    def test_vendor_error_body_cannot_echo_private_text(self):
        import io
        from urllib.error import HTTPError
        failure = HTTPError("https://model.test", 400, "secret echoed", {}, io.BytesIO(RAW.encode()))
        with patch.object(type(llm), "enabled", new_callable=PropertyMock, return_value=True), patch.object(llm, "_post_chat", side_effect=failure):
            data, meta = llm.complete_json("JSON", '{"candidate":{}}', {})
        self.assertFalse(meta["used"])
        self.assertIn("400", meta["reason"])
        self.assertNotIn("张隐私", json.dumps(meta, ensure_ascii=False))
        self.assertNotIn("private@example.test", str(meta))

    def test_uploaded_image_never_leaves_for_cloud_ocr(self):
        with TestClient(app) as client, patch.object(llm, "_post") as post:
            owner = client.post('/api/auth/demo').json()
            response = client.post('/api/match/extract-jd-image', headers={'X-Auth-Token': owner['token']},
                files={'file': ('private.png', b'private-image', 'image/png')})
        post.assert_not_called()
        self.assertEqual(response.status_code, 410)
        self.assertIn('云端识图已关闭', response.json()['detail'])

    def test_manual_url_import_uses_same_pinned_fetcher(self):
        from server.agents.url_jd_agent import fetch_page_text
        with patch("server.public_fetch.fetch_public_page", return_value=("<main>" + JD + "</main>", "https://jobs.test/123")) as fetch:
            text, meta = fetch_page_text("https://jobs.test/123")
        fetch.assert_called_once()
        self.assertIn("SQL", text)
        self.assertEqual(meta["via"], "public-ip-pinned")

    def test_unparsed_jd_does_not_invent_mandatory_requirements(self):
        from server.agents.jd_agent import mock_jd_profile
        profile = mock_jd_profile("测试职位\n与业务团队协作。")
        self.assertEqual(profile["must_haves"], [])
        self.assertNotIn("具备相关岗位经验", str(profile))
        self.assertNotIn("能独立推进核心任务", str(profile))

    def test_changed_jd_interpretation_cannot_reuse_previous_judgment(self):
        import uuid
        from server.db import init_db
        from server.routers.matches import _resolve_judge
        init_db()
        resume_id = "cv_cache_" + uuid.uuid4().hex
        judgments = [({"score": 70, "level": "稳"}, {"used": True}), ({"score": 40, "level": "不建议投"}, {"used": True})]
        with patch("server.routers.matches.judge_match", side_effect=judgments) as judge:
            first, _ = _resolve_judge(resume_id, JD, {"must_haves": ["SQL"]}, PROFILE)
            changed, _ = _resolve_judge(resume_id, JD, {"must_haves": ["Python"]}, PROFILE)
            repeated, meta = _resolve_judge(resume_id, JD, {"must_haves": ["Python"]}, PROFILE)
        self.assertEqual(first["score"], 70)
        self.assertEqual(changed["score"], 40)
        self.assertEqual(repeated["score"], 40)
        self.assertTrue(meta["cached"])
        self.assertEqual(judge.call_count, 2)

    def test_urls_without_search_citations_are_not_fetched(self):
        result = {"jobs": [{"url": "https://invented.test/job"}, {"url": "https://actual.test/job#fragment"}], "sources": [{"url": "https://actual.test/job"}]}
        self.assertEqual(source_candidates(result), ["https://actual.test/job"])

    def test_larger_citation_pool_merges_tracking_aliases(self):
        urls = [f"https://jobs.test/job/{i}.shtml" for i in range(30)]
        refs = [{"url": url} for url in urls] + [{"url": urls[0]+"?utm_source=search"}]
        candidates = source_candidates({"sources": refs, "jobs": [{"url": "https://invented.test/1"}]})
        self.assertEqual(len(candidates), 24)
        self.assertNotIn("https://invented.test/1", candidates)
        self.assertEqual(sum("/0.shtml" in url for url in candidates), 1)

    def test_backfills_real_detail_links_when_some_jobs_already_passed(self):
        initial, directory = "https://jobs.test/job/1.shtml", "https://jobs.test/search"
        details = [f"https://jobs.test/job/{i}.shtml" for i in range(2, 5)]
        def verify(url):
            if url == directory:
                raise ValueError("这是多个职位的列表页")
            item = job(); item.update(url=url, company="招聘公司"+url.rsplit("/", 1)[-1])
            return item
        snapshots = []
        with patch.object(settings, "discovery_limit", 4), patch.object(settings, "discovery_search_rounds", 2), \
                patch.object(llm, "search_jobs", return_value=({"sources": [{"url": initial}, {"url": directory}]}, {})), \
                patch("server.job_discovery.verify_job", side_effect=verify), \
                patch("server.job_discovery.linked_job_candidates", return_value=details) as links:
            items, rejected, meta = discover(PROFILE, {"city": "上海"}, lambda _: None,
                snapshot=lambda rows, stats: snapshots.append((list(rows), dict(stats))))
        self.assertEqual(len(items), 4)
        self.assertEqual(links.call_args.args[0], directory)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(meta["stats"]["detail_count"], 3)
        self.assertEqual(meta["stats"]["stop_reason"], "target_reached")
        self.assertTrue(any(rows and stats["verified"] < 4 for rows, stats in snapshots))
        for item in items:
            self.assertEqual(item["search_source_url"], initial if item["url"] == initial else directory)

    def test_additional_scopes_survive_partial_search_failure_and_preserve_privacy(self):
        calls = []
        def search(payload):
            calls.append(payload)
            scope = payload["search_plan"]["label"]
            if scope == "企业招聘系统":
                raise RuntimeError("该路搜索暂不可用")
            return {"sources": [{"url": "https://jobs.test/"+scope}]}, {"used": True}
        def verify(url):
            item = job(); item.update(url=url, company=url.rsplit("/", 1)[-1])
            return item
        with patch.object(settings, "discovery_limit", 3), patch.object(settings, "discovery_search_rounds", 6), \
                patch.object(llm, "search_jobs", side_effect=search), patch("server.job_discovery.verify_job", side_effect=verify), \
                patch("server.job_discovery.linked_job_candidates", return_value=[]):
            items, _, meta = discover(PROFILE, {"city": "上海"}, lambda _: None)
        self.assertEqual(len(items), 3)
        self.assertEqual(len(calls), 4)
        self.assertEqual(meta["stats"]["search_failed"], 1)
        self.assertEqual(meta["stats"]["search_completed"], 4)
        self.assertTrue(any(call["exclude_urls"] for call in calls))
        for secret in ("张隐私", "private@example.test", "隐私大学", "秘密门户", "2022.07"):
            self.assertNotIn(secret, json.dumps(calls, ensure_ascii=False))
        self.assertTrue(all(call["filters"] == {"city": "上海"} for call in calls))

    def test_candidate_budget_and_filters_are_not_relaxed_to_fill_results(self):
        urls = [f"https://jobs.test/{i}" for i in range(30)]
        def verify(url):
            item = job(); item.update(url=url, company=url, city="上海" if url.endswith("/0") else "北京")
            return item
        with patch.object(settings, "discovery_limit", 4), patch.object(settings, "discovery_candidate_limit", 4), \
                patch.object(llm, "search_jobs", return_value=({"sources": [{"url": url} for url in urls]}, {})) as search, \
                patch("server.job_discovery.verify_job", side_effect=verify) as fetch, \
                patch("server.job_discovery.linked_job_candidates") as links:
            items, rejected, meta = discover(PROFILE, {"city": "上海"}, lambda _: None)
        self.assertEqual(len(items), 1)
        self.assertEqual(len(rejected), 3)
        self.assertEqual(fetch.call_count, 4)
        self.assertEqual(search.call_count, 2)
        links.assert_not_called()
        self.assertEqual(meta["stats"]["stop_reason"], "candidate_budget")

    def test_private_urls_and_sensitive_query_rejected(self):
        for url in ("http://127.0.0.1/", "http://169.254.169.254/", "https://user:pass@public.test/", "file:///secret", "https://public.test:8443/", "https://public.test/?token=secret"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                public_target(url)

    def test_redirect_to_private_network_is_rejected(self):
        class Response:
            status = 302
            def getheader(self, key, default=None):
                return "http://127.0.0.1/admin" if key == "Location" else default
        class Connection:
            def __init__(self, *args): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return Response()
            def close(self): pass
        def dns(host, port, **kwargs):
            return [(2, 1, 6, "", ("127.0.0.1" if host == "127.0.0.1" else "8.8.8.8", port))]
        with patch("server.public_fetch.socket.getaddrinfo", side_effect=dns), patch("server.public_fetch._PinnedHTTP", Connection), self.assertRaises(ValueError):
            fetch_public_page("https://public.test/jobs/123")

    def test_verified_job_does_not_guess_missing_metadata(self):
        with patch("server.job_discovery.fetch_public_page", return_value=(page(), "https://example.test/job")):
            item = verify_job("https://example.test/job")
        self.assertEqual(item["graduate_cohort"], "未注明")
        self.assertEqual(item["recruitment_type"], "未注明")
        self.assertEqual(item["city"], "上海")
        self.assertIn("有效期", item["open_evidence"])

    def test_one_hop_uses_only_actual_same_site_detail_anchors(self):
        markup = '<a href="/job/123.shtml">产品经理</a><a href="https://evil.test/job/2.shtml">产品经理</a><a href="/salary/123">产品经理</a><a href="/job/456.shtml">软件工程师</a>'
        with patch("server.job_discovery.fetch_public_page", return_value=(markup, "https://jobs.test/search")):
            self.assertEqual(linked_job_candidates("https://jobs.test/search", ["产品经理"]), ["https://jobs.test/job/123.shtml"])

    def test_detail_expansion_reads_more_anchors_and_structured_posting_urls(self):
        markup = ''.join(f'<a href="/job/{i}.shtml">产品经理</a>' for i in range(7))
        markup += page(url="https://jobs.test/jobdesc.html?postId=99")
        with patch("server.job_discovery.fetch_public_page", return_value=(markup, "https://jobs.test/search")):
            urls = linked_job_candidates("https://jobs.test/search", ["产品经理"])
        self.assertEqual(len(urls), 8)
        self.assertIn("https://jobs.test/jobdesc.html?postId=99", urls)

    def test_contact_entry_requires_recent_exact_publication_date(self):
        from datetime import datetime, timezone
        content = page(validThrough=None, datePosted=datetime.now(timezone.utc).isoformat()) + '<button>聊一聊</button>'
        with patch("server.job_discovery.fetch_public_page", return_value=(content, "https://jobs.test/123")):
            item = verify_job("https://jobs.test/123")
        self.assertIn("可联系招聘方", item["open_evidence"])
        stale = page(validThrough=None, datePosted="2020-01-01") + '<button>聊一聊</button>'
        with patch("server.job_discovery.fetch_public_page", return_value=(stale, "https://jobs.test/123")), self.assertRaises(ValueError):
            verify_job("https://jobs.test/123")

    def test_recommended_job_apply_button_does_not_prove_main_job_is_open(self):
        content = page(validThrough=None) + '<h2>推荐职位</h2><a href="/other">立即申请</a>'
        with patch("server.job_discovery.fetch_public_page", return_value=(content, "https://jobs.test/123")), self.assertRaises(ValueError):
            verify_job("https://jobs.test/123")

    def test_closed_expired_thin_or_unconfirmed_jobs_are_rejected(self):
        for content in (page(validThrough="2020-01-01"), page() + "职位已关闭", "<html>请登录并完成验证码</html>", page(validThrough=None), page(hiringOrganization={})):
            with self.subTest(content=content[:50]), patch("server.job_discovery.fetch_public_page", return_value=(content, "https://example.test/job")), self.assertRaises(ValueError):
                verify_job("https://example.test/job")

    def test_quick_score_missing_skills_and_hard_gates(self):
        score = quick_score(job(), PROFILE)
        self.assertIn("Python", score["missing_tags"])
        self.assertIn("SQL", score["matched_tags"])
        gated = job(); gated["jd_text"] = "任职要求：博士学历，SQL，5年工作经验"
        score = quick_score(gated, PROFILE)
        self.assertLessEqual(score["score"], 49)
        self.assertEqual(len(score["gate_warnings"]), 2)

    def test_history_excludes_tracking_urls_redirects_and_updated_mirrors(self):
        previous = [{**job(), 'company': f'公司{i}', 'url': f'https://jobs.test/{i}'} for i in range(60)]
        urls = ['https://jobs.test/0?utm_source=again', 'https://redirect.test/old', 'https://mirror.test/old', 'https://jobs.test/new']
        def verify(url):
            item = {**job(), 'url': url, 'company': '新的招聘公司'}
            if 'redirect' in url: item.update(url=previous[1]['url'])
            if 'mirror' in url: item.update(company=previous[2]['company'], jd_text=JD+' 更新职责')
            return item
        with patch.object(llm, 'search_jobs', return_value=({'sources': [{'url': u} for u in urls]}, {})) as search, patch('server.job_discovery.verify_job', side_effect=verify) as verifier, patch('server.job_discovery.linked_job_candidates', return_value=[]):
            items, _, meta = discover(PROFILE, {}, lambda _: None, previous_jobs=previous)
        self.assertEqual([item['url'] for item in items], ['https://jobs.test/new'])
        self.assertEqual(meta['stats']['history_excluded'], 3)
        self.assertEqual(meta['stats']['previous_jobs'], 60)
        self.assertNotIn(urls[0], [c.args[0] for c in verifier.call_args_list])
        self.assertTrue(all(len(c.args[0]['exclude_urls']) <= 48 for c in search.call_args_list))
        self.assertIn(previous[-1]['url'], search.call_args_list[0].args[0]['exclude_urls'])

    def test_no_new_jobs_does_not_recycle_historical_results(self):
        with patch.object(llm, 'search_jobs', return_value=({'sources': [{'url': job()['url']}]}, {})), patch('server.job_discovery.verify_job') as verify, patch('server.job_discovery.linked_job_candidates', return_value=[]):
            items, rejected, meta = discover(PROFILE, {}, lambda _: None, previous_jobs=[job()])
        self.assertEqual(items, [])
        self.assertEqual(rejected, [])
        verify.assert_not_called()
        self.assertEqual(meta['stats']['history_excluded'], 1)

    def test_parallel_verification_dedup_and_descending_scores(self):
        urls = ["https://example.test/1", "https://example.test/2", "https://example.test/3", "https://example.test/4", "https://mirror.test/5"]
        def verify(url):
            if url.endswith("4"): raise ValueError("职位已关闭")
            item = job()
            item["url"] = urls[0] if url.endswith("3") else url
            if url.endswith("2"): item.update(title="前端工程师", jd_text="任职要求：React、Vue、TypeScript。")
            return item
        with patch.object(llm, "search_jobs", return_value=({"sources": [{"url": u} for u in urls]}, {"used": True})), patch("server.job_discovery.verify_job", side_effect=verify), patch("server.job_discovery.linked_job_candidates", return_value=[]):
            items, rejected, meta = discover(PROFILE, {}, lambda _: None)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "产品经理")
        self.assertEqual(len(rejected), 1)
        self.assertEqual(meta["stats"]["duplicates"], 2)


class DiscoveryAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(app)
        cls.client = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls): cls.context.__exit__(None, None, None)

    def workspace(self):
        demo = self.client.post("/api/auth/demo").json()
        return self.client.post("/api/auth/workspace", headers={"X-Auth-Token": demo["token"]}, json={"clone_resume_id": "cv_demo_linzhixia"}).json()

    def test_product_admin_entrypoints_and_linked_assets_still_load(self):
        from html.parser import HTMLParser
        class Assets(HTMLParser):
            def __init__(self): super().__init__(); self.paths = set()
            def handle_starttag(self, tag, attrs):
                data = dict(attrs)
                value = data.get('src') if tag == 'script' else data.get('href') if tag == 'link' else ''
                if value and value.startswith('/static/'): self.paths.add(value)
        for path in ('/', '/admin', '/admin/login', '/admin/register'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            assets = Assets(); assets.feed(response.text)
            for asset in assets.paths: self.assertEqual(self.client.get(asset).status_code, 200, asset)
        for path in ('/login', '/register'):
            response = self.client.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers['location'], '/')
        owner = self.workspace()
        health = self.client.get('/api/health', headers={'X-Auth-Token': owner['token']}).json()
        self.assertFalse(health['vision_ready'])
        self.assertEqual(health['input_pipeline_version'], 'public-jd-v1')

    def wait_run(self, run_id, headers):
        for _ in range(100):
            run = self.client.get('/api/discovery/runs/'+run_id, headers=headers).json()
            if run['status'] != 'running': return run
            time.sleep(.02)
        self.fail('search did not finish')

    def test_history_pages_preserve_results_and_scope_exclusion_to_resume_owner(self):
        owner, other = self.workspace(), self.workspace()
        headers = {'X-Auth-Token': owner['token']}
        received = []
        def pipeline(profile, filters, progress, snapshot, previous_jobs):
            received.append(previous_jobs)
            item = {**job(), 'company': '新公司'+str(len(received)), 'url': 'https://jobs.test/'+str(len(received))}
            return [item], [], {'stats': {'verified': 1}}
        with patch.object(type(llm), 'enabled', new_callable=PropertyMock, return_value=True), patch('server.routers.discovery.discover', side_effect=pipeline):
            first_id = self.client.post('/api/discovery/search', headers=headers, json={'resume_id': owner['resume_id']}).json()['id']
            first = self.wait_run(first_id, headers)
            second_id = self.client.post('/api/discovery/search', headers=headers, json={'resume_id': owner['resume_id'], 'city': '上海'}).json()['id']
            second = self.wait_run(second_id, headers)
            history = self.client.get('/api/discovery/runs', headers=headers, params={'resume_id': owner['resume_id']}).json()['items']
            self.assertEqual([r['id'] for r in history], [first_id, second_id])
            self.assertEqual([r['page'] for r in history], [1, 2])
            self.assertEqual([r['item_count'] for r in history], [1, 1])
            self.assertNotIn('items', history[0])  # History returns metadata, never full JDs.
            self.assertEqual(self.client.get('/api/discovery/runs/'+first_id, headers=headers).json(), first)
            self.assertNotEqual(first['items'][0]['url'], second['items'][0]['url'])
            self.assertEqual(received[0], [])
            self.assertEqual(received[1][0]['url'], first['items'][0]['url'])
            # Another resume in the same workspace starts with no exclusions.
            with get_db() as conn:
                saved = dict(conn.execute('SELECT * FROM resumes WHERE id=?', (owner['resume_id'],)).fetchone())
                saved['id'] = 'cv_history_other_'+first_id
                columns = list(saved)
                conn.execute(f"INSERT INTO resumes({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", [saved[c] for c in columns])
            different_id = self.client.post('/api/discovery/search', headers=headers, json={'resume_id': saved['id']}).json()['id']
            self.wait_run(different_id, headers)
            self.assertEqual(received[2], [])
            other_headers = {'X-Auth-Token': other['token']}
            other_id = self.client.post('/api/discovery/search', headers=other_headers, json={'resume_id': other['resume_id']}).json()['id']
            self.wait_run(other_id, other_headers)
            self.assertEqual(received[3], [])
        self.assertEqual(self.client.get('/api/discovery/runs', headers=other_headers, params={'resume_id': owner['resume_id']}).status_code, 404)
        # A job from the first page still hands off the first page's stored JD.
        with patch('server.routers.discovery.verify_job', return_value={**job(), 'company': first['items'][0]['company']}), patch('server.routers.discovery._run_match_core', return_value={'match_id': 'm_old_page'}) as core:
            response = self.client.post(f"/api/discovery/runs/{first_id}/items/{first['items'][0]['id']}/analyze", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(core.call_args.kwargs['resume_id'], owner['resume_id'])

    def test_isolated_search_and_verified_long_report_handoff(self):
        owner, other = self.workspace(), self.workspace()
        self.assertNotEqual(owner["resume_id"], other["resume_id"])
        headers = {"X-Auth-Token": owner["token"]}
        other_headers = {"X-Auth-Token": other["token"]}
        with patch.object(type(llm), "enabled", new_callable=PropertyMock, return_value=True), patch("server.routers.discovery.discover", return_value=([job()], [], {"used": True})):
            response = self.client.post("/api/discovery/search", headers=headers, json={"resume_id": owner["resume_id"]})
            self.assertEqual(response.status_code, 200, response.text)
            run_id = response.json()["id"]
            for _ in range(50):
                run = self.client.get("/api/discovery/runs/" + run_id, headers=headers).json()
                if run["status"] != "running": break
                time.sleep(.02)
        self.assertEqual(run["status"], "done")
        self.assertNotIn("jd_text", run["items"][0])
        self.assertEqual(self.client.get("/api/discovery/runs/"+run_id, headers=other_headers).status_code, 404)
        path = f'/api/discovery/runs/{run_id}/items/{run["items"][0]["id"]}/analyze'
        self.assertEqual(self.client.post(path, headers=other_headers).status_code, 404)
        with patch("server.routers.discovery.verify_job", side_effect=ValueError("职位已关闭")), patch("server.routers.discovery._run_match_core") as core:
            self.assertEqual(self.client.post(path, headers=headers).status_code, 409)
            core.assert_not_called()
        current = job(); current["jd_text"] = JD + " 最新要求"
        with patch("server.routers.discovery.verify_job", return_value=current), patch("server.routers.discovery._run_match_core", return_value={"match_id": "m_test"}) as core:
            result = self.client.post(path, headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(core.call_args.kwargs["jd_text"], current["jd_text"])
        self.assertEqual(core.call_args.kwargs["resume_id"], owner["resume_id"])
        self.assertTrue(core.call_args.kwargs["auto_report"])

    def test_failed_search_keeps_visible_jobs_and_excludes_them_next_time(self):
        owner = self.workspace()
        headers = {'X-Auth-Token': owner['token']}
        def interrupted(profile, filters, progress, snapshot, previous_jobs):
            snapshot([job()], {'checked': 1, 'verified': 1})
            raise RuntimeError('搜索中断')
        with patch.object(type(llm), 'enabled', new_callable=PropertyMock, return_value=True):
            with patch('server.routers.discovery.discover', side_effect=interrupted):
                first_id = self.client.post('/api/discovery/search', headers=headers, json={'resume_id': owner['resume_id']}).json()['id']
                first = self.wait_run(first_id, headers)
            self.assertEqual(first['status'], 'failed')
            self.assertEqual(len(first['items']), 1)
            with patch('server.routers.discovery.discover', return_value=([], [], {})) as pipeline:
                next_id = self.client.post('/api/discovery/search', headers=headers, json={'resume_id': owner['resume_id']}).json()['id']
                self.wait_run(next_id, headers)
            self.assertEqual(pipeline.call_args.kwargs['previous_jobs'][0]['url'], job()['url'])
        self.assertEqual(self.client.get('/api/discovery/runs/'+first_id, headers=headers).json(), first)

    def test_shared_demo_cannot_store_private_search_or_upload(self):
        demo = self.client.post("/api/auth/demo").json()
        headers = {"X-Auth-Token": demo["token"]}
        self.assertEqual(self.client.post("/api/discovery/search", headers=headers, json={"resume_id":"cv_demo_linzhixia"}).status_code, 409)
        self.assertEqual(self.client.post("/api/resumes/upload", headers=headers, files={"file":("private.txt",RAW.encode(),"text/plain")}).status_code, 409)

    def test_more_than_six_results_are_preserved_by_the_api(self):
        owner = self.workspace()
        headers = {"X-Auth-Token": owner["token"]}
        jobs = [{**job(), "url": f"https://jobs.test/{i}", "company": f"招聘公司{i}"} for i in range(20)]
        with patch.object(type(llm), "enabled", new_callable=PropertyMock, return_value=True), \
                patch("server.routers.discovery.discover", return_value=(jobs, [], {"stats": {"checked": 20, "verified": 20}})):
            response = self.client.post("/api/discovery/search", headers=headers, json={"resume_id": owner["resume_id"]})
            self.assertEqual(response.status_code, 200)
            for _ in range(50):
                run = self.client.get("/api/discovery/runs/"+response.json()["id"], headers=headers).json()
                if run["status"] != "running": break
                time.sleep(.02)
        self.assertEqual(len(run["items"]), 20)
        self.assertEqual(len({item["id"] for item in run["items"]}), 20)
        self.assertEqual(run["stats"]["checked"], 20)

    def test_partial_results_keep_stable_ids_and_do_not_leak_jd(self):
        owner = self.workspace()
        headers = {"X-Auth-Token": owner["token"]}
        ready, release = threading.Event(), threading.Event()
        def pipeline(profile, filters, progress, snapshot, previous_jobs=None):
            progress("verifying")
            snapshot([job()], {"checked": 1, "verified": 1})
            ready.set()
            release.wait(5)
            return [job()], [], {"stats": {"checked": 1, "verified": 1}}
        try:
            with patch.object(type(llm), "enabled", new_callable=PropertyMock, return_value=True), \
                    patch("server.routers.discovery.discover", side_effect=pipeline):
                response = self.client.post("/api/discovery/search", headers=headers, json={"resume_id": owner["resume_id"]})
                run_id = response.json()["id"]
                self.assertTrue(ready.wait(3))
                partial = self.client.get("/api/discovery/runs/"+run_id, headers=headers).json()
                self.assertEqual(partial["status"], "running")
                self.assertNotIn("jd_text", partial["items"][0])
                item_id = partial["items"][0]["id"]
                path = f'/api/discovery/runs/{run_id}/items/{item_id}/analyze'
                self.assertEqual(self.client.post(path, headers=headers).status_code, 409)
                release.set()
                for _ in range(50):
                    final = self.client.get("/api/discovery/runs/"+run_id, headers=headers).json()
                    if final["status"] != "running": break
                    time.sleep(.02)
            self.assertEqual(final["status"], "done")
            self.assertEqual(final["items"][0]["id"], item_id)
        finally:
            release.set()


if __name__ == "__main__": unittest.main()
