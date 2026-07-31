from alpha_engine.strategy import kelly_binary

def test_kelly_no_edge(): assert kelly_binary(.5,.5)==0
def test_kelly_positive(): assert kelly_binary(.7,.5)>.39
