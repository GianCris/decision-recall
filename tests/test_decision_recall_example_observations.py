"""Additive editable examples: no change to capture, validation, or evaluation."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from decision_recall.product.case_api import RegisteredCaseAPI, registered_case_api
from decision_recall.product.candidate_plans import registered_candidate_plans
from decision_recall.product.example_observations import registered_example_observations
from decision_recall.product.registered_decisions import registered_decisions


class ExampleObservationTests(unittest.TestCase):
    def api(self, examples=None):
        return RegisteredCaseAPI(decisions=registered_decisions(), candidate_plans=registered_candidate_plans(), example_observations=examples)

    def test_examples_are_optional_input_only_and_not_t1_execution(self):
        with patch('decision_recall.product.case_api.reevaluate_decision', side_effect=AssertionError('metadata cannot run T1')):
            plain, configured = self.api(), registered_case_api()
            for case_id in ('D-104', 'D-205'):
                before, after = plain.preparation(case_id), configured.preparation(case_id)
                self.assertIsNone(before['example_observations'])
                self.assertEqual({k:v for k,v in before.items() if k != 'example_observations'},
                                 {k:v for k,v in after.items() if k != 'example_observations'})
                example = after['example_observations']
                self.assertEqual(set(example), {'world_time', 'observations'})
                for observation in example['observations']:
                    self.assertEqual(set(observation), {'metric_key','value','unit','window_days','observed_at'})
                self.assertTrue(after['current_match_labels'])

    def test_existing_validator_rejects_invalid_and_authority_bearing_config(self):
        examples = registered_example_observations()
        for key in ('safe_reuse_result', 'reason_codes', 'current_matches', 'authority', 'policy', 'thresholds'):
            invalid = deepcopy(examples)
            invalid['D-205'][key] = 'forged'
            with self.assertRaises(ValueError): self.api(invalid)
            invalid = deepcopy(examples)
            invalid['D-205']['observations'][0][key] = 'forged'
            with self.assertRaises(ValueError): self.api(invalid)
        invalid = deepcopy(examples)
        invalid['D-205']['observations'][0]['value'] = 2
        with self.assertRaises(ValueError): self.api(invalid)

    def test_examples_are_copied_and_do_not_mutate_registration(self):
        examples = registered_example_observations()
        api = self.api(examples)
        before = api.preparation('D-205')
        examples['D-205']['observations'][0]['value'] = 0
        returned = api.preparation('D-205')
        returned['example_observations']['observations'][0]['value'] = 0
        self.assertEqual(api.preparation('D-205'), before)

    def test_example_inputs_use_unchanged_capture_and_evaluation_path(self):
        plain, configured = self.api(), registered_case_api()
        for case_id, expected in (('D-104','insufficient_evidence'),('D-205','reuse_not_authorized')):
            p = configured.preparation(case_id)
            capture = {key:p[key] for key in ('decision_id','capture_session_id','profile_hash','gap_id','question_hash')}
            capture['answer'] = 'yes'
            self.assertEqual(plain.capture(case_id,capture), configured.capture(case_id,capture))
            request = {'capture':capture, **p['example_observations']}
            result = configured.reevaluate(case_id,request)
            self.assertEqual(plain.reevaluate(case_id,request),result)
            self.assertEqual(result['safe_reuse_result'],expected)


if __name__ == '__main__': unittest.main()
