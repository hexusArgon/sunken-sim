import unittest
from types import SimpleNamespace
from farm.hybrid.mage_joint import refine

class JointTests(unittest.TestCase):
 def test_joint_synergy_beats_staged_and_first_ties(self):
  gear=(SimpleNamespace(rawcode='x'),)
  def many(bs):return [10. if 'a' in b.talents else (30. if 'y' in b.glyphs else 9.) for b in bs]
  r=refine(gear,['a','b'],['x','y'],1,1,1,many=many,batch_size=2)
  self.assertEqual(r['best']['talents'],('b',));self.assertEqual(r['best']['glyphs'],('y',));self.assertEqual(r['evaluated'],6)
  r=refine(gear,['a','b'],['x','y'],1,1,1,many=lambda bs:[1.]*len(bs))
  self.assertEqual(r['best']['talents'],('a',));self.assertEqual(r['best']['glyphs'],())
 def test_vectors_validation_and_batch_order(self):
  gear=(SimpleNamespace(rawcode='x'),)
  for points in ({'potency':21},{'bogus':1},{'luck':1.5},{'luck':-1},{'luck':20,'potency':20}):
   with self.assertRaises(ValueError):refine(gear,['a'],[],1,1,0,point_vectors=[points])
  r=refine(gear,['a'],[],1,1,0,point_vectors=[{}, {'potency':1}],many=lambda bs:[b.potency_points for b in bs],batch_size=1)
  self.assertEqual(r['best']['points']['potency'],1);self.assertFalse(r['exhaustive_esc'])
 def test_missing_or_nonfinite_scores_rejected(self):
  gear=(SimpleNamespace(rawcode='x'),)
  for many in (lambda bs:[],lambda bs:[float('nan')]*len(bs)):
   with self.assertRaises(ValueError):refine(gear,['a'],[],1,1,0,many=many)

 def test_budget_is_explicitly_partial(self):
  gear=(SimpleNamespace(rawcode='x'),)
  r=refine(gear,['a','b'],['x','y'],1,1,1,many=lambda bs:[1.]*len(bs),batch_size=2,max_seconds=0)
  self.assertFalse(r['complete']);self.assertEqual(r['evaluated'],2);self.assertEqual(r['total_candidates'],6)
 def test_resume_suffix_is_not_claimed_complete_domain(self):
  gear=(SimpleNamespace(rawcode='x'),)
  many=lambda bs:[(2 if 'b' in b.talents else 1)+(3 if 'y' in b.glyphs else 0) for b in bs]
  full=refine(gear,['a','b'],['x','y'],1,1,1,many=many)
  prefix=refine(gear,['a','b'],['x','y'],1,1,1,many=many,batch_size=2,max_seconds=0)
  suffix=refine(gear,['a','b'],['x','y'],1,1,1,many=many,candidate_start=prefix['evaluated'])
  self.assertFalse(suffix['complete']);self.assertTrue(suffix['range_complete'])
  best=max([prefix['best'],suffix['best']],key=lambda r:r['dps'])
  self.assertEqual(best,full['best']);self.assertEqual(prefix['evaluated']+suffix['evaluated'],full['total_candidates'])
  with self.assertRaises(ValueError):refine(gear,['a'],[],1,1,0,many=many,candidate_start=1)
