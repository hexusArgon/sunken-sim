"""Reject clipped tapes; exact CPU fallback preserves row order/ESC/ring binding."""
import unittest
from unittest import mock
import torch
from farm.hybrid import mage_gpu_timeline as M


def push(buf,mask):
    M._push(torch,buf,torch.tensor(mask),0.,1.,2.,3.,4.,5.,M.K_AUTO)


class CapacityUnitTest(unittest.TestCase):
    def setUp(self):torch.set_num_threads(1)
    def test_exact_cap_accepted(self):
        with mock.patch.object(M,'MAX_EVENTS',3):
            buf=M._make_bufs(torch,torch.device('cpu'),1,torch.float64)
            for _ in range(3):push(buf,[True])
            self.assertEqual(len(M._buffers_to_events(buf)[0]),3);self.assertFalse(buf['overflow'][0])
    def test_one_over_cap_rejected_before_conversion(self):
        with mock.patch.object(M,'MAX_EVENTS',3):
            buf=M._make_bufs(torch,torch.device('cpu'),1,torch.float64)
            for _ in range(4):push(buf,[True])
            self.assertEqual(int(buf['length'][0]),3)
            with self.assertRaises(M.TimelineCapacityError) as caught:M._buffers_to_events(buf)
            self.assertEqual(caught.exception.reasons,{0:'event_capacity'})
    def test_real_default_boundary_and_inactive_full_rows(self):
        buf=M._make_bufs(torch,torch.device('cpu'),3,torch.float64)
        buf['length'][:]=torch.tensor([M.MAX_EVENTS-1,M.MAX_EVENTS,M.MAX_EVENTS])
        push(buf,[True,True,False]);self.assertEqual(buf['overflow'].tolist(),[False,True,False])
        self.assertEqual(buf['length'].tolist(),[M.MAX_EVENTS]*3)
    def test_mixed_capacity_fallback_only_rejected_rows_in_order(self):
        builds=[object(),object(),object()];keys=['Hydra','Living Bomb',None];partial=[('complete0',),None,('complete2',)];counts={}
        with mock.patch.object(M,'_mage_batch',side_effect=M.TimelineCapacityError({1:'event_capacity'},partial)),mock.patch.object(M,'_cpu_events_batch',return_value=[('exact1',)]) as cpu:
            got=M.generate_mage_timelines(torch,torch.device('cpu'),builds,'fire',5,keys,counts)
        self.assertEqual(got,[('complete0',),('exact1',),('complete2',)])
        cpu.assert_called_once_with([builds[1]],'fire',5,['Living Bomb'])
        self.assertEqual(counts['cpu_fallback_rows'],1);self.assertEqual(counts['vector_rows'],2);self.assertEqual(counts['event_capacity'],1)
    def test_mixed_step_event_reasons_and_bound_keys(self):
        bs=[object(),object(),object()];counts={}
        with mock.patch.object(M,'_mage_batch',side_effect=M.TimelineCapacityError({2:'step_limit',0:'event_capacity'},[None,('ok',),None])),mock.patch.object(M,'_cpu_events_batch',return_value=[('e0',),('e2',)]) as cpu:
            got=M.generate_mage_timelines(torch,torch.device('cpu'),bs,'fire',5,['Hydra',None,'Arcane Blast'],counts)
        cpu.assert_called_once_with([bs[0],bs[2]],'fire',5,['Hydra','Arcane Blast']);self.assertEqual(got,[('e0',),('ok',),('e2',)])
        self.assertEqual(counts['event_capacity'],1);self.assertEqual(counts['step_limit'],1)
    def test_capacity_without_complete_rows_falls_back_whole_batch(self):
        counts={};bs=[object(),object()]
        with mock.patch.object(M,'_mage_batch',side_effect=M.TimelineCapacityError({1:'event_capacity'})),mock.patch.object(M,'_cpu_events_batch',return_value=[('e0',),('e1',)]) as cpu:
            got=M.generate_mage_timelines(torch,torch.device('cpu'),bs,'fire',5,diagnostics=counts)
        self.assertEqual(got,[('e0',),('e1',)]);self.assertEqual(counts['vector_rows'],0);self.assertEqual(counts['capacity_batch'],1)
    def test_other_kernel_exception_labeled_exact_batch_fallback(self):
        counts={};bs=[object()]
        with mock.patch.object(M,'_mage_batch',side_effect=RuntimeError('queue overflow')),mock.patch.object(M,'_cpu_events_batch',return_value=[('exact',)]):
            self.assertEqual(M.generate_mage_timelines(torch,torch.device('cpu'),bs,'fire',5,diagnostics=counts),[('exact',)])
        self.assertEqual(counts['batch_exception:RuntimeError'],1);self.assertEqual(counts['cpu_fallback_rows'],1)
    def test_failed_cpu_fallback_propagates_never_partial_score(self):
        with mock.patch.object(M,'_mage_batch',side_effect=M.TimelineCapacityError({0:'event_capacity'},[None])),mock.patch.object(M,'_cpu_events_batch',side_effect=RuntimeError('exact failed')):
            with self.assertRaisesRegex(RuntimeError,'exact failed'):M.generate_mage_timelines(torch,torch.device('cpu'),[object()],'fire',5)
    def test_empty_batch(self):self.assertEqual(M.generate_mage_timelines(torch,torch.device('cpu'),[],'fire',5),[])
    def test_bad_keys_not_silently_scored(self):
        with self.assertRaises(ValueError):M.generate_mage_timelines(torch,torch.device('cpu'),[object()],'fire',5,[])


class DirectMLCapacityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from farm.hybrid.device import detect
        from farm.hybrid import registry
        from farm.catalog import _parts
        from sunken_sim.shadow import Build
        from sunken_sim.esc import apply_points,empty_points
        torch.set_num_threads(1);cls.device=detect('mage','fire')
        if not cls.device.gpu:raise unittest.SkipTest('real DirectML required')
        items=_parts('mage','fire','mixed',None,100)[5]
        a=tuple(items[c] for c in ('I04G','I06U','I0BR','I0D8','fgrd','sor8'))
        b=tuple(items[c] for c in ('I00D','I066','I06O','I0DF','I0J2','I0NT'))
        cls.builds=[]
        for gear,pts in ((a,{}),(a,{'haste':20,'potency':10}),(b,{'mana':20,'potency':10}),(b,{'luck':20,'potency':10})):
            p=empty_points();p.update(pts)
            cls.builds.append(apply_points(Build(frozenset({'I0KU','I0NZ','I0UP'}),frozenset({'I07B','I0H3','I0JA'}),gear,0,0),p))
        cls.keys=[None,None,'Hydra','Living Bomb']
        cls.baseline=M.generate_mage_timelines(torch,cls.device.handle,cls.builds,'fire',5,cls.keys)
    def test_mixed_actual_event_cap_and_exact_boundary_preserve_rows(self):
        sizes=[len(r[0]) for r in self.baseline];cap=min(sizes);self.assertGreater(max(sizes),cap)
        counts={}
        with mock.patch.object(M,'MAX_EVENTS',cap):
            got=M.generate_mage_timelines(torch,self.device.handle,self.builds,'fire',5,self.keys,counts)
        self.assertEqual(counts['vector_rows'],sum(n==cap for n in sizes));self.assertEqual(counts['cpu_fallback_rows'],sum(n>cap for n in sizes))
        exact=M._cpu_events_batch(self.builds,'fire',5,self.keys)
        for i,n in enumerate(sizes):self.assertEqual(got[i],self.baseline[i] if n==cap else exact[i])
    def test_actual_directml_compile_after_overflow_matches_fresh_cpu(self):
        from farm.hybrid import registry,engine
        from sunken_sim import mage
        ref=[mage.simulate(b,5,spec='fire',use_history=False).dps for b in self.builds]
        gpu=registry.make_engine(self.device,'mage','fire',5)
        with mock.patch.object(M,'MAX_EVENTS',1):got=gpu.dps_many(self.builds)
        self.assertTrue(engine.compare(ref,got)['ok'],engine.compare(ref,got));self.assertGreater(gpu.timeline_counts['event_capacity'],0)
        self.assertEqual(gpu.timeline_counts['vector_rows'],0)
    def test_actual_step_limit_falls_back_exact_with_policies(self):
        counts={}
        with mock.patch.object(M,'MAX_STEPS',1):got=M.generate_mage_timelines(torch,self.device.handle,self.builds,'fire',5,self.keys,counts)
        exact=M._cpu_events_batch(self.builds,'fire',5,self.keys)
        self.assertEqual(got,exact);self.assertEqual(counts['step_limit'],len(self.builds));self.assertEqual(counts['vector_rows'],0)


if __name__=='__main__':unittest.main()
