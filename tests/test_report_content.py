"""Report content contracts: factual background, local resume evidence, richer role practice."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch, PropertyMock
_test_data = tempfile.TemporaryDirectory(prefix='offeros-report-tests-')
os.environ['OFFEROS_DATA_DIR'] = _test_data.name
os.environ['LLM_MODE'] = 'mock'
from fastapi.testclient import TestClient
from server.main import app
from server.demo_resume import DEMO_RESUME_PROFILE, DEMO_RESUME_TEXT
from server.interview_preparation import enrich_interview_preparation
from server.agents.action_agent import _normalize_report, mock_report
from server.agents.research_agent import research_company
from server.llm import llm


class ReportContentTests(unittest.TestCase):
    def test_resume_questions_are_bound_to_actual_projects_and_source_rows(self):
        report = enrich_interview_preparation({}, DEMO_RESUME_PROFILE, {'core_requirements':['用户研究、SQL数据分析、RAG设计']})
        prep = report['interview_preparation']
        self.assertEqual(len(prep['resume_questions']), 6)
        self.assertIn('客户门户 2.0', prep['resume_questions'][0]['question'])
        self.assertIn('AI 知识检索助手原型', prep['resume_questions'][-1]['question'])
        for question in prep['resume_questions']:
            self.assertIn(question['evidence'], DEMO_RESUME_TEXT)
            self.assertTrue(question['evidence_id'])
            self.assertTrue(question['line_start'])
            self.assertGreaterEqual(len(question['answer_points']), 3)
            self.assertEqual(len(question['followups']), 2)
        self.assertGreaterEqual(len(prep['role_questions']), 3)

    def test_missing_resume_does_not_invent_experience_questions(self):
        prep = enrich_interview_preparation({}, {}, {})['interview_preparation']
        self.assertEqual(prep['resume_questions'], [])
        self.assertEqual(prep['role_questions'], [])

    def test_role_answer_points_survive_normalization_and_local_binding(self):
        jd={'core_requirements':['RAG应用设计']}
        question={'category':'职位侧','question':'何时应采用RAG？','requirement':'RAG应用设计','answer_points':['先定义任务','比较检索与生成','建立评测和兜底'],'knowledge_points':['召回与重排'],'followups':['知识更新怎么办？']}
        fallback=mock_report({'score':70,'level':'稳'},DEMO_RESUME_PROFILE,jd)
        normalized=_normalize_report({'interview':[question]},fallback,{'score':70,'level':'稳'})
        enriched=enrich_interview_preparation(normalized,DEMO_RESUME_PROFILE,jd)
        actual=enriched['interview_preparation']['role_questions'][0]
        self.assertEqual(actual['answer_points'],question['answer_points'])
        self.assertEqual(actual['knowledge_points'],question['knowledge_points'])
        self.assertEqual(actual['source'],'model_jd')

    def test_native_company_search_does_not_send_candidate_data(self):
        payload={'company':'示例公开公司','role':'产品经理','candidate':DEMO_RESUME_PROFILE,'raw_text':DEMO_RESUME_TEXT}
        result={'output':{'search_info':{'search_results':[{'url':'https://company.test/about'}]}}}
        with patch.object(type(llm),'enabled',new_callable=PropertyMock,return_value=True),patch.object(llm,'_post',return_value=result) as post:
            refs,meta=llm.search_company(payload)
        body=post.call_args.args[1]
        self.assertTrue(body['parameters']['search_options']['forced_search'])
        self.assertEqual(len(refs),1)
        self.assertTrue(meta['used'])
        self.assertNotIn('林知夏',json.dumps(body,ensure_ascii=False))
        self.assertNotIn('云帆协作',json.dumps(body,ensure_ascii=False))
        self.assertNotIn('"role":',body['input']['messages'][1]['content'])

    def test_short_model_output_is_supplemented_and_unsupported_numeric_claims_removed(self):
        jd={'core_requirements':['AI RAG设计','SQL数据分析','用户研究','企业SaaS规划','PRD交付','流程优化','业务复盘']}
        question={'category':'职位侧','question':'平台方案如何设计？','answer_points':['数据失真率超过40%','资源占用率必须90%','不能忽略异常流程']}
        prep=enrich_interview_preparation({'interview':[question]},DEMO_RESUME_PROFILE,jd)['interview_preparation']
        self.assertEqual(len(prep['role_questions']),6)
        self.assertNotIn('40%',str(prep['role_questions']))
        self.assertTrue(all(q['source']=='local_jd' for q in prep['role_questions']))

    def test_background_drops_invalid_citations_and_outdated_recent_events(self):
        refs=[{'title':'公司官方介绍','url':'https://company.test/about','snippet':'主营业务为企业软件。'}]
        response={'company_background':[
            {'topic':'主营业务与客户','conclusion':'企业软件服务商','source_ids':[1],'evidence_quotes':[{'source_id':1,'quote':'企业软件服务商公开介绍'}]},
            {'topic':'融资与经营','conclusion':'没有证据的估值','source_ids':[99]},
            {'topic':'近期业务动作','conclusion':'旧事件','source_ids':[1],'event_date':'2020-01-01'},
            {'topic':'近期业务动作','conclusion':'没有明确日期','source_ids':[1]}]}
        with patch.object(llm,'search_company',return_value=(refs,{'used':True})),patch('server.agents.research_agent.fetch_public_page',return_value=('<main>企业软件服务商公开介绍</main>','https://company.test/about')),patch.object(llm,'complete_json',return_value=(response,{'used':True})):
            result,meta=research_company('示例公开公司','产品经理')
        self.assertEqual(len(result['company_background']),1)
        self.assertEqual(result['company_background'][0]['source_ids'],[1])
        self.assertNotIn('excerpt',result['sources'][0])
        self.assertTrue(meta['used'])

    def test_no_sources_or_fictional_company_never_generate_factual_research(self):
        with patch.object(llm,'search_company',return_value=([],{'used':False})),patch.object(llm,'complete_json') as summarize:
            result,_=research_company('示例公开公司')
            fictional,_=research_company('虚构公司')
        self.assertEqual(result['company_background'],[])
        self.assertEqual(fictional['status'],'demo')
        summarize.assert_not_called()

    def test_company_numbers_must_appear_in_the_cited_original(self):
        refs=[{'url':'https://company.test/about','title':'官方公司介绍'}]
        quote='公司于2018年上市，主营企业软件服务。'
        response={'company_background':[{'topic':'融资与经营','conclusion':'公司于2020年上市。','source_ids':[1],'evidence_quotes':[{'source_id':1,'quote':quote}]}]}
        with patch.object(llm,'search_company',return_value=(refs,{'used':True})),patch('server.agents.research_agent.fetch_public_page',return_value=('<main>'+quote+'</main>','https://company.test/about')),patch.object(llm,'complete_json',return_value=(response,{'used':True})):
            result,_=research_company('公开公司')
        self.assertNotIn('2020',str(result['company_background']))
        self.assertEqual(result['company_background'][0]['conclusion'],quote)
        self.assertEqual(result['company_background'][0]['kind'],'原文摘录')


class ReportAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=TestClient(app);cls.client=cls.context.__enter__()
        demo=cls.client.post('/api/auth/demo').json()
        cls.headers={'X-Auth-Token':demo['token']}

    @classmethod
    def tearDownClass(cls): cls.context.__exit__(None,None,None)

    def test_background_is_owned_persisted_and_not_overwritten_by_report_progress(self):
        from server.routers.matches import _set_report_status
        research={'research_version':5,'status':'done','company_background':[{'conclusion':'公开背景','source_ids':[1]}],'sources':[{'id':1,'url':'https://company.test/about'}]}
        original=self.client.get('/api/match/runs/m_demo_enterprise',headers=self.headers).json()
        with patch('server.routers.matches.research_company',return_value=(research,{'used':True})) as call:
            denied=self.client.post('/api/match/research',headers=self.headers,json={'company':'公开公司','match_id':'missing'})
            self.assertEqual(denied.status_code,404)
            call.assert_not_called()
            response=self.client.post('/api/match/research',headers=self.headers,json={'company':'任意输入','match_id':'m_demo_enterprise'})
        self.assertEqual(response.status_code,200)
        self.assertIn('虚构',call.call_args.args[0])
        _set_report_status('m_demo_enterprise','done',llm_meta={'action':{'used':True}})
        saved=self.client.get('/api/match/runs/m_demo_enterprise',headers=self.headers).json()
        self.assertEqual(saved['research']['company_background'][0]['conclusion'],'公开背景')
        self.assertEqual(len(saved['report']['interview_preparation']['resume_questions']),6)
        self.assertEqual(saved['judge']['score'],original['judge']['score'])
        with patch('server.routers.matches.research_company') as repeated:
            again=self.client.post('/api/match/research',headers=self.headers,json={'company':'公开公司','match_id':'m_demo_enterprise'})
        self.assertTrue(again.json()['llm']['cached'])
        repeated.assert_not_called()


if __name__=='__main__': unittest.main()
