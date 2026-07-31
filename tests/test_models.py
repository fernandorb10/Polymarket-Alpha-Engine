from alpha_engine.models import ProbabilityReport

def test_probability_bounds():
 p=ProbabilityReport(probability_yes=.6,confidence=.7,thesis='x')
 assert p.probability_yes==.6
