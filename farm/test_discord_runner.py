"""No network/bot startup: routing/protocol/cancellation contracts around hybrid."""
import ast
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest import mock
from farm import discord_runner as D, runner as C
from farm.hybrid import runner as H
from farm.protocol import parse_progress, status_text


def job(**kwargs):
    return dict(dict(id='fixture',worker='eseid-main',hero='mage',spec='fire',pool='mixed',targets=5,
                     fire_backend='hybrid',top=100,start=0,end=0,admission_policy='bare-top10',search_schema=2),**kwargs)


class DiscordRouteTest(unittest.TestCase):
    def setUp(self):
        self.job=job();self.box={'stop':False};self.ticks=[];self.calls=[]
        self.stack=__import__('contextlib').ExitStack();self.addCleanup(self.stack.close)
        def patch(target,**kw):return self.stack.enter_context(mock.patch(target,**kw))
        self.locked=patch('farm.hybrid.runner.cpu_locked',return_value=False)
        self.support=patch('farm.hybrid.runner.registry.gpu_engine_for',return_value=True)
        self.detect=patch('farm.hybrid.runner.detect',return_value=NS(gpu=True,kind='dml',name='RX fixture',reason=''))
        self.prep=patch('farm.hybrid.runner.prep_check',return_value={'parity':True})
        self.fight=patch('farm.hybrid.runner.fight_check',return_value={'ok':True})
        patch('farm.catalog.load',return_value=(object(),{}))
        self.cpu=patch('farm.runner.run_job',side_effect=self.run_backend)
    def run_backend(self,j,b,t,eval_fn=None):
        self.calls.append((j,b,eval_fn));t('worker\nпосчитано 2 · осталось 3');return {'done':True,'stopped':b['stop'],'path':'fixture'}
    def run_route(self):return D.run_job(self.job,self.box,self.ticks.append)
    def test_bot_imports_adapter(self):
        tree=ast.parse((Path(__file__).parent/'bot.py').read_text(encoding='utf8'))
        self.assertTrue(any(isinstance(n,ast.ImportFrom) and n.module=='farm.discord_runner' and any(a.name=='run_job' for a in n.names) for n in ast.walk(tree)))
    def test_supported_discord_worker_routes_hybrid_and_keeps_identity(self):
        from farm.hybrid.engine import eval_span
        got=self.run_route();j,b,ev=self.calls[-1]
        self.assertIs(ev,eval_span);self.assertIs(b,self.box);self.assertEqual(j['worker'],'eseid-main')
        self.assertEqual(j['admission_policy'],'bare-top10');self.assertEqual(j['search_schema'],2)
        self.assertTrue(j['hybrid']['gpu_fights']);self.assertEqual(got['path'],'fixture')
        self.assertEqual(self.job,job());self.assertEqual(parse_progress(self.ticks[-1]),(2,3))
        self.assertIn('CPU scheduling + GPU scoring',self.ticks[-1]);self.assertTrue(all(isinstance(t,str) for t in self.ticks))
    def test_other_discord_nickname_also_hybrid(self):
        self.job['worker']='eseid-notebook';self.run_route();self.assertIsNotNone(self.calls[-1][2])
    def test_cancellation_box_and_stopped_result_preserved(self):
        self.box['stop']=True;self.assertTrue(self.run_route()['stopped']);self.assertIs(self.calls[-1][1],self.box)
    def assert_cpu(self,reason):
        self.run_route();j,b,ev=self.calls[-1];self.assertIsNone(ev)
        self.assertFalse(j['hybrid']['gpu_fights']);self.assertIn(reason,self.ticks[-1]);self.assertIn('Backend: CPU',self.ticks[-1])
    def test_no_gpu_reason_not_silent(self):
        self.detect.return_value=NS(gpu=False,kind='cpu',name='cpu',reason='torch_directml unavailable')
        self.assert_cpu('torch_directml unavailable');self.prep.assert_not_called()
    def test_explicit_device_detection_error_is_labeled_cpu(self):
        self.detect.side_effect=RuntimeError('device unavailable');self.assert_cpu('device detection failed')
    def test_unsupported_does_not_detect_or_prep(self):
        self.support.return_value=False;self.assert_cpu('no supported hybrid fight engine');self.detect.assert_not_called()
    def test_locked_does_not_detect_or_prep(self):
        self.locked.return_value=True;self.assert_cpu('locked to CPU');self.detect.assert_not_called()
    def test_prep_parity_failure(self):
        self.prep.return_value={'parity':False};self.assert_cpu('item-stat parity failed');self.fight.assert_not_called()
    def test_prep_exception_fails_closed(self):
        self.prep.side_effect=RuntimeError('fixture');self.assert_cpu('item-stat prep failed');self.fight.assert_not_called()
    def test_fight_mismatch(self):
        self.fight.return_value={'ok':False};self.assert_cpu('fight parity failed')
    def test_fight_exception(self):
        self.fight.side_effect=RuntimeError('fixture');self.assert_cpu('fight parity failed')
    def test_progress_protocol_final_and_stop_not_replaced(self):
        text=status_text(worker='eseid-main',hero='mage',spec='fire',pool='mixed',targets=5,start=0,end=4,done=2,left=3,best=None,admission_policy='bare-top10')
        self.assertEqual(parse_progress(text+'\nBackend: CPU'),(2,3))
    def test_backend_metadata_persists_without_changing_legacy_result_fields(self):
        with TemporaryDirectory() as d, mock.patch.object(C,'_result_path',return_value=Path(d)/'out.json'):
            j=job(hybrid={'device':'cpu','gpu_fights':False,'fallback':'fixture'})
            p=C._write_result(j,C.Boards(),1,False,0);got=json.loads(Path(p).read_text(encoding='utf8'))
            self.assertEqual(got['hybrid'],j['hybrid']);self.assertEqual(got['worker'],j['worker'])
            self.assertFalse(got['admission_is_lossless']);self.assertFalse(got['global_optimum_proven'])
    def test_legacy_cpu_result_has_no_invented_hybrid_field(self):
        with TemporaryDirectory() as d, mock.patch.object(C,'_result_path',return_value=Path(d)/'out.json'):
            p=C._write_result(job(),C.Boards(),1,False,0);self.assertNotIn('hybrid',json.loads(Path(p).read_text(encoding='utf8')))


if __name__=='__main__':unittest.main()
